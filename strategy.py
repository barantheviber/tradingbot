"""Signal generation - pure functions, no I/O, no exchange, no state.

The same code is used by the live engine and by ``backtest.py``:

* ``compute_indicators(df, params)`` adds indicator and signal columns. Every
  column at row ``i`` depends only on rows ``<= i`` (the Donchian channel is
  shifted by one so the current candle is compared with the *previous* N
  candles). Callers must pass **closed candles only**.
* ``generate_signal(df, params)`` evaluates the last (most recent closed)
  row and returns a ``Signal`` explaining each confirmation layer.

Confirmation layers
-------------------
1. Trend filter (mandatory): close above / below EMA(``ema_trend_period``).
2. Momentum: RSI inside a configurable range (avoids chasing extremes).
3. MACD + volume: a MACD/signal cross within the last N candles, MACD still
   on the right side, and volume above its average x factor.
4. Volatility breakout: close beyond the previous Donchian channel plus an
   optional ATR buffer.

A signal fires when the trend filter passes and at least
``min_confirmations`` of layers 2-4 agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd


@dataclass
class StrategyParams:
    ema_trend_period: int = 200
    rsi_period: int = 14
    rsi_long_min: float = 45.0
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0
    rsi_short_max: float = 55.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_cross_lookback: int = 3
    volume_ma_period: int = 20
    volume_factor: float = 1.2
    atr_period: int = 14
    donchian_period: int = 20
    breakout_atr_buffer: float = 0.0
    min_confirmations: int = 3
    allow_short: bool = False
    exit_on_trend_flip: bool = True
    # regime filters (0 = off); mandatory like the trend filter when enabled
    ema_slope_bars: int = 0
    adx_period: int = 14
    adx_min: float = 0.0
    min_atr_pct: float = 0.0

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "StrategyParams":
        """Build from the state_manager settings dict; unknown keys are ignored."""
        kwargs = {}
        for f in fields(cls):
            if f.name in settings and settings[f.name] is not None:
                default = getattr(cls, f.name)
                kwargs[f.name] = type(default)(settings[f.name])
        params = cls(**kwargs)
        params.min_confirmations = int(min(3, max(1, params.min_confirmations)))
        params.macd_cross_lookback = max(1, params.macd_cross_lookback)
        params.ema_slope_bars = max(0, params.ema_slope_bars)
        params.adx_period = max(1, params.adx_period)
        params.adx_min = max(0.0, params.adx_min)
        params.min_atr_pct = max(0.0, params.min_atr_pct)
        return params

    @property
    def warmup(self) -> int:
        """Minimum number of closed candles before signals are meaningful."""
        return max(self.ema_trend_period, self.macd_slow + self.macd_signal, self.donchian_period + 1,
                   self.volume_ma_period + 1, self.rsi_period, self.atr_period,
                   self.ema_trend_period + self.ema_slope_bars, 2 * self.adx_period) + 5


@dataclass
class Signal:
    action: str  # "long" | "short" | "hold"
    timestamp: int = 0
    close: float = 0.0
    atr: float = 0.0
    exit_long: bool = False
    exit_short: bool = False
    reasons: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_entry(self) -> bool:
        return self.action in ("long", "short")


# --------------------------------------------------------------- indicators
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0.0, 100.0)  # no losses at all -> RSI 100
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int, slow: int, signal: int):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd_line, signal_line, macd_line - signal_line


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder's Average Directional Index (trend strength, direction-agnostic)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr_smooth = atr(df, period)
    alpha = 1.0 / period
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean() / tr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean() / tr_smooth
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def compute_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Return a copy of ``df`` with indicator + signal columns (closed candles only)."""
    out = df.copy()
    close = out["close"]

    out["ema_trend"] = ema(close, params.ema_trend_period)
    out["rsi"] = rsi(close, params.rsi_period)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(close, params.macd_fast, params.macd_slow,
                                                             params.macd_signal)
    out["atr"] = atr(out, params.atr_period)
    # previous N candles only -> the current candle can break out of it
    out["donchian_high"] = out["high"].rolling(params.donchian_period).max().shift(1)
    out["donchian_low"] = out["low"].rolling(params.donchian_period).min().shift(1)
    out["volume_ma"] = out["volume"].rolling(params.volume_ma_period).mean().shift(1)

    above = out["macd"] > out["macd_signal"]
    below = out["macd"] < out["macd_signal"]
    cross_up = above & ~above.shift(1, fill_value=False)
    cross_down = below & ~below.shift(1, fill_value=False)
    lb = params.macd_cross_lookback
    recent_up = cross_up.astype(int).rolling(lb, min_periods=1).max().astype(bool)
    recent_down = cross_down.astype(int).rolling(lb, min_periods=1).max().astype(bool)
    volume_ok = out["volume"] > out["volume_ma"] * params.volume_factor

    buffer = out["atr"] * params.breakout_atr_buffer

    # --- layer flags (NaN comparisons evaluate to False -> safe during warm-up)
    out["trend_long"] = close > out["ema_trend"]
    out["trend_short"] = close < out["ema_trend"]

    # --- optional regime filters (mandatory when enabled, like the trend filter)
    regime_long = pd.Series(True, index=out.index)
    regime_short = pd.Series(True, index=out.index)
    if params.ema_slope_bars > 0:
        prev_ema = out["ema_trend"].shift(params.ema_slope_bars)
        regime_long &= out["ema_trend"] > prev_ema
        regime_short &= out["ema_trend"] < prev_ema
    if params.adx_min > 0:
        out["adx"] = adx(out, params.adx_period)
        strong = out["adx"] >= params.adx_min
        regime_long &= strong
        regime_short &= strong
    if params.min_atr_pct > 0:
        volatile = out["atr"] / close * 100.0 >= params.min_atr_pct
        regime_long &= volatile
        regime_short &= volatile
    out["regime_long"] = regime_long
    out["regime_short"] = regime_short
    out["mom_long"] = out["rsi"].between(params.rsi_long_min, params.rsi_long_max)
    out["mom_short"] = out["rsi"].between(params.rsi_short_min, params.rsi_short_max)
    out["macdvol_long"] = recent_up & above & volume_ok
    out["macdvol_short"] = recent_down & below & volume_ok
    out["breakout_long"] = close > (out["donchian_high"] + buffer)
    out["breakout_short"] = close < (out["donchian_low"] - buffer)

    long_conf = out[["mom_long", "macdvol_long", "breakout_long"]].sum(axis=1)
    short_conf = out[["mom_short", "macdvol_short", "breakout_short"]].sum(axis=1)
    out["long_confirmations"] = long_conf
    out["short_confirmations"] = short_conf

    valid = pd.Series(np.arange(len(out)) >= params.warmup - 1, index=out.index)
    valid &= out[["ema_trend", "rsi", "macd_signal", "atr", "donchian_high", "volume_ma"]].notna().all(axis=1)

    out["long_signal"] = valid & out["trend_long"] & regime_long & (long_conf >= params.min_confirmations)
    short_raw = valid & out["trend_short"] & regime_short & (short_conf >= params.min_confirmations)
    out["short_signal"] = short_raw if params.allow_short else False
    out["exit_long"] = bool(params.exit_on_trend_flip) & valid & out["trend_short"]
    out["exit_short"] = bool(params.exit_on_trend_flip) & valid & out["trend_long"]
    return out


def generate_signal(df: pd.DataFrame, params: StrategyParams) -> Signal:
    """Evaluate the most recent closed candle in ``df``."""
    if df is None or len(df) < params.warmup:
        return Signal(action="hold", reasons={"warmup": f"need {params.warmup} candles, have {0 if df is None else len(df)}"})
    ind = compute_indicators(df, params)
    return signal_from_row(ind.iloc[-1])


def signal_from_row(row: pd.Series) -> Signal:
    """Turn a row of ``compute_indicators`` output into a ``Signal``."""
    action = "long" if bool(row["long_signal"]) else "short" if bool(row["short_signal"]) else "hold"
    reasons = {
        "close": _r(row["close"]),
        "ema_trend": _r(row["ema_trend"]),
        "rsi": _r(row["rsi"]),
        "macd": _r(row["macd"]),
        "macd_signal": _r(row["macd_signal"]),
        "volume": _r(row["volume"]),
        "volume_ma": _r(row["volume_ma"]),
        "donchian_high": _r(row["donchian_high"]),
        "donchian_low": _r(row["donchian_low"]),
        "atr": _r(row["atr"]),
        "long": {"trend": bool(row["trend_long"]), "momentum": bool(row["mom_long"]),
                 "macd_volume": bool(row["macdvol_long"]), "breakout": bool(row["breakout_long"])},
        "short": {"trend": bool(row["trend_short"]), "momentum": bool(row["mom_short"]),
                  "macd_volume": bool(row["macdvol_short"]), "breakout": bool(row["breakout_short"])},
    }
    return Signal(
        action=action,
        timestamp=int(row["timestamp"]),
        close=float(row["close"]),
        atr=float(row["atr"]) if pd.notna(row["atr"]) else 0.0,
        exit_long=bool(row["exit_long"]),
        exit_short=bool(row["exit_short"]),
        reasons=reasons,
    )


def _r(value: Any, nd: int = 6) -> Any:
    try:
        return None if pd.isna(value) else round(float(value), nd)
    except (TypeError, ValueError):
        return value
