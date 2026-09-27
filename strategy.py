"""
Signal generation logic - completely independent from execution.

This module only looks at OHLCV data (as a pandas DataFrame of *closed*
candles) and a set of parameters, and returns a Signal. It never touches
the exchange, the database, or an order book. That separation is what lets
the exact same code run in bot_engine.py (live/paper) and backtest.py.

Confirmation layers combined (all must agree for an entry signal):
  1. Trend filter    - EMA(ema_trend_period): price above => long bias,
                        below => short bias.
  2. Momentum        - RSI(rsi_period) inside [rsi_lower, rsi_upper] is
                        considered "healthy" (not overbought/oversold
                        against the trade direction).
  3. MACD + volume   - MACD line crossing its signal line in the trend
                        direction, confirmed by volume above its moving
                        average (volume_confirmation_multiplier).
  4. Volatility      - Donchian channel breakout (close breaking the prior
                        N-period high/low) in the trend direction, with
                        ATR available for downstream risk sizing.

A signal only fires when every layer agrees; otherwise the result is a
"no trade" (side=None) signal, which still carries the computed indicator
values for logging/dashboard purposes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class StrategyParams:
    ema_trend_period: int = 200
    rsi_period: int = 14
    rsi_lower: float = 40.0
    rsi_upper: float = 70.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_ma_period: int = 20
    volume_confirmation_multiplier: float = 1.2
    donchian_period: int = 20
    atr_period: int = 14

    @property
    def min_bars_required(self) -> int:
        return (
            max(
                self.ema_trend_period,
                self.rsi_period,
                self.macd_slow + self.macd_signal,
                self.volume_ma_period,
                self.donchian_period,
                self.atr_period,
            )
            + 5
        )


@dataclass
class IndicatorSnapshot:
    close: float
    ema_trend: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    macd_hist_prev: float
    volume: float
    volume_ma: float
    atr: float
    donchian_high: float
    donchian_low: float
    donchian_high_prev: float
    donchian_low_prev: float


@dataclass
class Signal:
    side: Optional[Side]
    reasons: list[str] = field(default_factory=list)
    indicators: Optional[IndicatorSnapshot] = None

    @property
    def is_actionable(self) -> bool:
        return self.side is not None


# ---------------------------------------------------------------------
# Indicator building blocks (pure functions - reused by backtest.py)
# ---------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # Where avg_loss is 0 and avg_gain > 0, RSI should be 100.
    result = result.where(avg_loss != 0, 100.0)
    return result


def macd(series: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def donchian(df: pd.DataFrame, period: int):
    high = df["high"].rolling(window=period).max()
    low = df["low"].rolling(window=period).min()
    return high, low


# ---------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------
def compute_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """
    Returns a copy of df with indicator columns appended. Expects columns:
    timestamp, open, high, low, close, volume (standard ccxt OHLCV shape,
    already converted to a DataFrame).
    """
    out = df.copy()
    out["ema_trend"] = ema(out["close"], params.ema_trend_period)
    out["rsi"] = rsi(out["close"], params.rsi_period)
    macd_line, signal_line, hist = macd(
        out["close"], params.macd_fast, params.macd_slow, params.macd_signal
    )
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["volume_ma"] = out["volume"].rolling(window=params.volume_ma_period).mean()
    out["atr"] = atr(out, params.atr_period)
    donchian_high, donchian_low = donchian(out, params.donchian_period)
    out["donchian_high"] = donchian_high
    out["donchian_low"] = donchian_low
    return out


def generate_signal(df: pd.DataFrame, params: StrategyParams) -> Signal:
    """
    df must contain only *closed* candles (the caller - bot_engine.py or
    backtest.py - is responsible for dropping any still-forming candle to
    avoid look-ahead bias). The signal is evaluated on the last row.
    """
    if len(df) < params.min_bars_required:
        return Signal(side=None, reasons=["insufficient_history"])

    enriched = compute_indicators(df, params)
    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]

    if last[["ema_trend", "rsi", "macd", "macd_signal", "atr", "donchian_high", "donchian_low"]].isna().any():
        return Signal(side=None, reasons=["indicators_warming_up"])

    snapshot = IndicatorSnapshot(
        close=float(last["close"]),
        ema_trend=float(last["ema_trend"]),
        rsi=float(last["rsi"]),
        macd=float(last["macd"]),
        macd_signal=float(last["macd_signal"]),
        macd_hist=float(last["macd_hist"]),
        macd_hist_prev=float(prev["macd_hist"]),
        volume=float(last["volume"]),
        volume_ma=float(last["volume_ma"]) if not pd.isna(last["volume_ma"]) else 0.0,
        atr=float(last["atr"]),
        donchian_high=float(last["donchian_high"]),
        donchian_low=float(last["donchian_low"]),
        donchian_high_prev=float(prev["donchian_high"]) if not pd.isna(prev["donchian_high"]) else float(last["donchian_high"]),
        donchian_low_prev=float(prev["donchian_low"]) if not pd.isna(prev["donchian_low"]) else float(last["donchian_low"]),
    )

    reasons: list[str] = []

    # 1. Trend filter
    trend_long = snapshot.close > snapshot.ema_trend
    trend_short = snapshot.close < snapshot.ema_trend

    # 2. Momentum filter (healthy zone, not extreme against direction)
    momentum_ok = params.rsi_lower <= snapshot.rsi <= params.rsi_upper
    momentum_long_ok = momentum_ok
    momentum_short_ok = momentum_ok

    # 3. MACD crossover (hist crossing zero) + volume confirmation
    macd_cross_up = snapshot.macd_hist_prev <= 0 < snapshot.macd_hist
    macd_cross_down = snapshot.macd_hist_prev >= 0 > snapshot.macd_hist
    volume_confirmed = snapshot.volume > snapshot.volume_ma * params.volume_confirmation_multiplier

    # 4. Volatility breakout (Donchian)
    breakout_up = snapshot.close > snapshot.donchian_high_prev
    breakout_down = snapshot.close < snapshot.donchian_low_prev

    long_ok = trend_long and momentum_long_ok and macd_cross_up and volume_confirmed and breakout_up
    short_ok = trend_short and momentum_short_ok and macd_cross_down and volume_confirmed and breakout_down

    if long_ok:
        reasons = [
            "trend:long (close>EMA200)",
            f"rsi:{snapshot.rsi:.1f} in range",
            "macd:bullish cross",
            "volume:confirmed",
            "donchian:breakout up",
        ]
        return Signal(side=Side.LONG, reasons=reasons, indicators=snapshot)

    if short_ok:
        reasons = [
            "trend:short (close<EMA200)",
            f"rsi:{snapshot.rsi:.1f} in range",
            "macd:bearish cross",
            "volume:confirmed",
            "donchian:breakout down",
        ]
        return Signal(side=Side.SHORT, reasons=reasons, indicators=snapshot)

    # No trade - explain why, for logging/dashboard visibility.
    if not (trend_long or trend_short):
        reasons.append("trend:flat/undefined")
    if not momentum_long_ok:
        reasons.append(f"rsi:{snapshot.rsi:.1f} out of range")
    if not (macd_cross_up or macd_cross_down):
        reasons.append("macd:no fresh cross")
    if not volume_confirmed:
        reasons.append("volume:not confirmed")
    if not (breakout_up or breakout_down):
        reasons.append("donchian:no breakout")

    return Signal(side=None, reasons=reasons, indicators=snapshot)
