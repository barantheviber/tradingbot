"""Quick historical sanity check of the strategy + risk logic.

Uses exactly the same ``strategy.compute_indicators`` and ``risk_manager``
functions as the live bot. Execution model (no look-ahead):

* a signal is computed on the close of candle ``i``;
* the order fills at the *open* of candle ``i+1`` (+ slippage, + fee);
* stop-loss / take-profit are checked against each candle's high/low; if
  both are touched in the same candle the stop is assumed first
  (conservative); gaps through a level fill at the open;
* the trailing stop is updated after each closed candle and applies from
  the next candle on.

Examples::

    python backtest.py --synthetic 3000
    python backtest.py --symbol BTC/USDT --timeframe 1h --days 180
    python backtest.py --csv data/btc_1h.csv --db data/tradingbot.db --set risk_reward_ratio=3
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from config import DEFAULT_SETTINGS, default_settings_values
from performance import compute_performance, format_performance
from risk_manager import RiskManager, is_daily_loss_limit_hit, unrealized_pnl
from state_manager import coerce_to_type
from strategy import StrategyParams, compute_indicators


@dataclass
class BacktestTrade:
    side: str
    entry_time: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    exit_time: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    fees: float = 0.0
    pnl: float = 0.0
    initial_stop: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


def run_backtest(
    df: pd.DataFrame,
    settings: Optional[Mapping[str, Any]] = None,
    starting_balance: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 5.0,
) -> Dict[str, Any]:
    settings = {**default_settings_values(), **(settings or {})}
    params = StrategyParams.from_settings(settings)
    risk = RiskManager(lambda: settings)
    slip = slippage_bps / 10_000.0

    ind = compute_indicators(df.reset_index(drop=True), params)
    cash = starting_balance  # realised equity
    position: Optional[BacktestTrade] = None
    trades: List[BacktestTrade] = []
    equity_curve: List[float] = []
    pending_entry: Optional[str] = None
    pending_exit = False
    day, day_start = None, starting_balance

    def close(pos: BacktestTrade, raw_price: float, i: int, reason: str) -> None:
        nonlocal cash
        price = raw_price * (1 - slip) if pos.side == "long" else raw_price * (1 + slip)
        exit_fee = price * pos.quantity * fee_rate
        pos.exit_time, pos.exit_price, pos.exit_reason = _ts(ind.at[i, "timestamp"]), price, reason
        pos.fees += exit_fee
        pos.pnl = unrealized_pnl(pos.side, pos.entry_price, price, pos.quantity) - pos.fees
        cash += pos.pnl
        trades.append(pos)

    for i in range(len(ind)):
        row = ind.iloc[i]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        today = _ts(row["timestamp"])[:10]
        if today != day:  # UTC midnight reset
            open_upnl = unrealized_pnl(position.side, position.entry_price, o, position.quantity) if position else 0.0
            day, day_start = today, cash + open_upnl

        # 1) orders decided on the previous close fill at this open
        if position and pending_exit:
            close(position, o, i, "trend_flip")
            position = None
        if pending_entry and position is None:
            prev_atr = float(ind.at[i - 1, "atr"])
            entry = o * (1 + slip) if pending_entry == "long" else o * (1 - slip)
            equity_now = cash
            plan = risk.plan_trade("BT", pending_entry, entry, prev_atr, equity_now, [],
                                   day_start_equity=day_start, available_cash=cash)
            if plan.allowed:
                fee = entry * plan.quantity * fee_rate
                position = BacktestTrade(side=plan.side, entry_time=_ts(row["timestamp"]), entry_price=entry,
                                         quantity=plan.quantity, stop_loss=plan.stop_loss,
                                         take_profit=plan.take_profit, fees=fee, initial_stop=plan.stop_loss,
                                         highest_price=entry, lowest_price=entry)
        pending_entry, pending_exit = None, False

        # 2) intra-candle stop / target
        if position:
            p = position
            if p.side == "long":
                if l <= p.stop_loss:
                    close(p, min(o, p.stop_loss), i, "stop_loss")
                    position = None
                elif h >= p.take_profit:
                    close(p, max(o, p.take_profit), i, "take_profit")
                    position = None
            else:
                if h >= p.stop_loss:
                    close(p, max(o, p.stop_loss), i, "stop_loss")
                    position = None
                elif l <= p.take_profit:
                    close(p, min(o, p.take_profit), i, "take_profit")
                    position = None

        # 3) trailing stop on the closed candle
        if position and pd.notna(row["atr"]):
            position.highest_price = max(position.highest_price, h)
            position.lowest_price = min(position.lowest_price, l)
            position.stop_loss = risk.trailing_stop_for(asdict(position), float(row["atr"]))

        # 4) signals on the closed candle -> act at next open
        if position:
            pending_exit = bool(row["exit_long"]) if position.side == "long" else bool(row["exit_short"])
        elif settings.get("trading_enabled", True):
            if not is_daily_loss_limit_hit(day_start, cash, float(settings["daily_loss_limit_pct"])):
                if bool(row["long_signal"]):
                    pending_entry = "long"
                elif bool(row["short_signal"]):
                    pending_entry = "short"

        upnl = unrealized_pnl(position.side, position.entry_price, c, position.quantity) if position else 0.0
        equity_curve.append(cash + upnl - (position.fees if position else 0.0))

    if position:  # mark-to-market close at the end
        close(position, float(ind.iloc[-1]["close"]), len(ind) - 1, "end_of_data")
        equity_curve[-1] = cash

    closed = [{"pnl": t.pnl, "fees": t.fees, "closed_at": t.exit_time, "id": n} for n, t in enumerate(trades)]
    stats = compute_performance(closed, starting_balance)
    stats["final_equity"] = cash
    stats["return_pct"] = (cash / starting_balance - 1) * 100.0
    curve = np.array(equity_curve) if equity_curve else np.array([starting_balance])
    peak = np.maximum.accumulate(curve)
    stats["max_drawdown_mtm_pct"] = float(((peak - curve) / peak).max() * 100.0)
    stats["candles"] = len(ind)
    return {"trades": trades, "stats": stats, "equity_curve": equity_curve}


# ----------------------------------------------------------------- data
def generate_synthetic_ohlcv(n: int = 2000, seed: int = 7, start_price: float = 100.0,
                             timeframe_ms: int = 3_600_000) -> pd.DataFrame:
    """Random-walk candles with trending regimes and volume bursts (for demos/tests)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-0.0015, 0.0, 0.002], size=n // 100 + 1), 100)[:n]
    rets = drift + rng.normal(0, 0.01, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0, 0.006, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(10, 0.4, n) * (1 + 2 * (np.abs(rets) > 0.015))
    ts = 1_700_000_000_000 + np.arange(n, dtype=np.int64) * timeframe_ms
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high, "low": low, "close": close,
                         "volume": volume})


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if not np.issubdtype(df["timestamp"].dtype, np.number):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).astype("int64") // 1_000_000
    return df[["timestamp", "open", "high", "low", "close", "volume"]].astype(float).astype({"timestamp": "int64"})


def fetch_history(symbol: str, timeframe: str, days: int, exchange_id: str) -> pd.DataFrame:
    from exchange_client import ExchangeClient, drop_unclosed_candles, ohlcv_to_frame

    client = ExchangeClient(exchange_id)
    tf_ms = client.timeframe_ms(timeframe)
    since = client.milliseconds() - days * 86_400_000
    rows: List[list] = []
    while True:
        batch = client.call("fetch_ohlcv", symbol, timeframe, since, 1000)
        if not batch:
            break
        rows.extend(batch)
        next_since = batch[-1][0] + tf_ms
        if next_since <= since or len(batch) < 2:
            break
        since = next_since
        if since >= client.milliseconds():
            break
    return drop_unclosed_candles(ohlcv_to_frame(rows), tf_ms, client.milliseconds())


def _parse_overrides(items: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items:
        key, _, value = item.partition("=")
        key = key.strip()
        if key not in DEFAULT_SETTINGS:
            raise SystemExit(f"Unknown setting: {key}")
        out[key] = coerce_to_type(value.strip(), type(DEFAULT_SETTINGS[key][0]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest the strategy on historical OHLCV")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--csv", help="CSV with timestamp,open,high,low,close,volume")
    src.add_argument("--synthetic", type=int, metavar="N", help="Use N synthetic candles (offline)")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--exchange", default=None, help="ccxt exchange id (default: EXCHANGE_ID or binance)")
    ap.add_argument("--db", help="Read strategy/risk settings from this state DB")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="Override a setting")
    ap.add_argument("--balance", type=float, default=10_000.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--trades-csv", help="Write the trade list to this CSV")
    args = ap.parse_args(argv)

    settings: Dict[str, Any] = default_settings_values()
    if args.db:
        from state_manager import StateManager

        settings.update(StateManager(args.db).get_all_settings())
    settings.update(_parse_overrides(args.set))

    if args.csv:
        df = load_csv(args.csv)
    elif args.synthetic:
        df = generate_synthetic_ohlcv(args.synthetic)
    else:
        import os

        df = fetch_history(args.symbol, args.timeframe, args.days,
                           (args.exchange or os.getenv("EXCHANGE_ID") or "binance").lower())
    if df.empty:
        print("No data.")
        return 1

    result = run_backtest(df, settings, args.balance, args.fee, args.slippage_bps)
    s = result["stats"]
    print(f"Candles: {s['candles']}  {_ts(df['timestamp'].iloc[0])} -> {_ts(df['timestamp'].iloc[-1])}")
    print(format_performance(s))
    print(f"final_equity={s['final_equity']:.2f} return={s['return_pct']:.2f}% "
          f"max_dd_mark_to_market={s['max_drawdown_mtm_pct']:.2f}%")
    if args.trades_csv and result["trades"]:
        with open(args.trades_csv, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(asdict(result["trades"][0]).keys()))
            writer.writeheader()
            for t in result["trades"]:
                writer.writerow(asdict(t))
        print(f"Trades written to {args.trades_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
