"""
Simple walk-forward backtest.

This is a sanity-check tool, not a full backtesting engine: it replays
historical OHLCV candle-by-candle through the exact same strategy.py and
risk_manager.py code the live bot uses (no separate "backtest strategy"),
so a quick pass here is representative of what bot_engine.py would have
done - only look-ahead-safe (each step only sees candles up to and
including that step; the same window trimming that drop_unclosed_candle
does in bot_engine.py).

Usage:
    python backtest.py --symbol BTC/USDT --timeframe 15m --limit 1500
    python backtest.py --csv path/to/ohlcv.csv

CSV format (if used) must have columns: timestamp,open,high,low,close,volume
(timestamp in milliseconds, same as ccxt's fetch_ohlcv).
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import pandas as pd

from config import config as default_config
from exchange_client import ExchangeClient
from risk_manager import RiskParams, compute_position_size, update_trailing_stop
from strategy import Side, StrategyParams, generate_signal

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    reason: str


def fetch_history_via_exchange(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    client = ExchangeClient(default_config)
    raw = client.fetch_ohlcv(symbol, timeframe, limit=limit)
    return pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])


def load_history_from_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def run_backtest(
    df: pd.DataFrame,
    strategy_params: StrategyParams,
    risk_params: RiskParams,
    starting_equity: float = 10_000.0,
) -> dict:
    equity = starting_equity
    equity_curve = [equity]
    trades: list[BacktestTrade] = []

    open_side: Side | None = None
    open_qty = 0.0
    open_entry = 0.0
    open_sl = 0.0
    open_tp = 0.0

    min_bars = strategy_params.min_bars_required

    for i in range(min_bars, len(df)):
        window = df.iloc[: i + 1]  # only candles up to and including i - no look-ahead
        row = window.iloc[-1]
        price = float(row["close"])

        # Manage an open position first (stop/target/trailing), using this
        # candle's close as the reference price - mirrors bot_engine.
        if open_side is not None:
            from strategy import atr as atr_fn

            atr_series = atr_fn(window, strategy_params.atr_period)
            current_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0

            hit_stop = (open_side == Side.LONG and price <= open_sl) or (
                open_side == Side.SHORT and price >= open_sl
            )
            hit_target = (open_side == Side.LONG and price >= open_tp) or (
                open_side == Side.SHORT and price <= open_tp
            )

            if hit_stop or hit_target:
                reason = "stop_loss" if hit_stop else "take_profit"
                if open_side == Side.LONG:
                    pnl = (price - open_entry) * open_qty
                else:
                    pnl = (open_entry - price) * open_qty
                equity += pnl
                trades.append(
                    BacktestTrade(
                        side=open_side.value,
                        entry_price=open_entry,
                        exit_price=price,
                        quantity=open_qty,
                        pnl=pnl,
                        reason=reason,
                    )
                )
                open_side = None
            elif current_atr > 0:
                open_sl = update_trailing_stop(open_side, open_sl, price, current_atr, risk_params)

        signal = generate_signal(window, strategy_params)

        if open_side is None and signal.is_actionable:
            atr_value = signal.indicators.atr
            try:
                sizing = compute_position_size(signal.side, price, atr_value, equity, risk_params)
            except ValueError:
                equity_curve.append(equity)
                continue
            open_side = signal.side
            open_qty = sizing.quantity
            open_entry = price
            open_sl = sizing.stop_loss
            open_tp = sizing.take_profit

        equity_curve.append(equity)

    # Force-close any position still open at the end of the data, at the
    # last available close, so PnL stats reflect it.
    if open_side is not None:
        price = float(df.iloc[-1]["close"])
        if open_side == Side.LONG:
            pnl = (price - open_entry) * open_qty
        else:
            pnl = (open_entry - price) * open_qty
        equity += pnl
        trades.append(
            BacktestTrade(
                side=open_side.value,
                entry_price=open_entry,
                exit_price=price,
                quantity=open_qty,
                pnl=pnl,
                reason="end_of_data",
            )
        )

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    peak = starting_equity
    max_drawdown_pct = 0.0
    running = starting_equity
    for p in pnls:
        running += p
        peak = max(peak, running)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - running) / peak * 100.0)

    return {
        "starting_equity": starting_equity,
        "final_equity": equity,
        "total_return_pct": (equity - starting_equity) / starting_equity * 100.0,
        "total_trades": len(trades),
        "win_rate_pct": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "max_drawdown_pct": max_drawdown_pct,
        "trades": trades,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="Quick strategy sanity-check backtest")
    parser.add_argument("--symbol", default=default_config.trading.symbol)
    parser.add_argument("--timeframe", default=default_config.trading.timeframe)
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--csv", default=None, help="Path to a local OHLCV CSV instead of fetching live")
    parser.add_argument("--equity", type=float, default=default_config.account.paper_starting_balance)
    args = parser.parse_args()

    if args.csv:
        df = load_history_from_csv(args.csv)
    else:
        df = fetch_history_via_exchange(args.symbol, args.timeframe, args.limit)

    strategy_params = StrategyParams(
        ema_trend_period=default_config.risk_defaults.ema_trend_period,
        rsi_period=default_config.risk_defaults.rsi_period,
        rsi_lower=default_config.risk_defaults.rsi_lower,
        rsi_upper=default_config.risk_defaults.rsi_upper,
        macd_fast=default_config.risk_defaults.macd_fast,
        macd_slow=default_config.risk_defaults.macd_slow,
        macd_signal=default_config.risk_defaults.macd_signal,
        volume_ma_period=default_config.risk_defaults.volume_ma_period,
        volume_confirmation_multiplier=default_config.risk_defaults.volume_confirmation_multiplier,
        donchian_period=default_config.risk_defaults.donchian_period,
        atr_period=default_config.risk_defaults.atr_period,
    )
    risk_params = RiskParams(
        risk_per_trade_pct=default_config.risk_defaults.risk_per_trade_pct,
        risk_reward_ratio=default_config.risk_defaults.risk_reward_ratio,
        atr_sl_multiplier=default_config.risk_defaults.atr_sl_multiplier,
        trailing_atr_multiplier=default_config.risk_defaults.trailing_atr_multiplier,
        max_daily_drawdown_pct=default_config.risk_defaults.max_daily_drawdown_pct,
        max_concurrent_positions=default_config.risk_defaults.max_concurrent_positions,
        max_exposure_per_symbol_pct=default_config.risk_defaults.max_exposure_per_symbol_pct,
    )

    results = run_backtest(df, strategy_params, risk_params, starting_equity=args.equity)

    print("\n=== Backtest Results ===")
    print(f"Bars used:          {len(df)}")
    print(f"Starting equity:    {results['starting_equity']:.2f}")
    print(f"Final equity:       {results['final_equity']:.2f}")
    print(f"Total return:       {results['total_return_pct']:.2f}%")
    print(f"Total trades:       {results['total_trades']}")
    print(f"Win rate:           {results['win_rate_pct']:.2f}%")
    print(f"Max drawdown:       {results['max_drawdown_pct']:.2f}%")
    print(
        "\nNOTE: past performance on historical data does not guarantee future "
        "results. This script is a sanity check, not a substitute for paper "
        "trading."
    )


if __name__ == "__main__":
    main()
