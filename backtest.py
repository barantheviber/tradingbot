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

Real market history for many pairs / timeframes: ``scripts/download_history.py``
and ``scripts/backtest_matrix.py`` (run weekly by the "Real-data backtest" workflow).
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
    entry_index: int = 0
    exit_index: int = 0
    risk_amount: float = 0.0

    @property
    def r_multiple(self) -> float:
        """PnL (after fees) in units of the risk planned at entry."""
        return self.pnl / self.risk_amount if self.risk_amount > 0 else 0.0


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


def run_backtest(
    df: pd.DataFrame,
    settings: Optional[Mapping[str, Any]] = None,
    starting_balance: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 5.0,
    stop_slippage_bps: float = 5.0,
    min_notional: float = 10.0,
    qty_step: Optional[float] = None,
    start_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Simulate the live bot's rules on ``df`` (closed candles, oldest first).

    Costs model a market-order bot like the live one:

    * every fill pays ``fee_rate`` (taker) on its notional;
    * every fill is ``slippage_bps`` worse than the reference price;
    * stop-loss exits pay an extra ``stop_slippage_bps``: the live bot notices
      a stop only on its next price poll, after the level was crossed;
    * orders below ``min_notional`` (exchange minimum) are skipped and the
      quantity is rounded down to ``qty_step`` when given.

    ``start_ms``: candles before this time only warm up the indicators; trading
    and every statistic start at the first candle at or after it (used for
    out-of-sample and per-year evaluation without losing the warm-up).
    """
    settings = {**default_settings_values(), **(settings or {})}
    params = StrategyParams.from_settings(settings)
    risk = RiskManager(lambda: settings)
    slip = slippage_bps / 10_000.0
    stop_slip = stop_slippage_bps / 10_000.0

    ind = compute_indicators(df.reset_index(drop=True), params)
    ts = ind["timestamp"].to_numpy(dtype="int64")
    opens, highs = ind["open"].to_numpy(float), ind["high"].to_numpy(float)
    lows, closes = ind["low"].to_numpy(float), ind["close"].to_numpy(float)
    atrs = ind["atr"].to_numpy(float)
    long_sig, short_sig = ind["long_signal"].to_numpy(bool), ind["short_signal"].to_numpy(bool)
    exit_long, exit_short = ind["exit_long"].to_numpy(bool), ind["exit_short"].to_numpy(bool)
    days = (ts // 86_400_000).tolist()
    first = int(np.searchsorted(ts, start_ms)) if start_ms is not None else 0

    cash = starting_balance  # realised equity
    position: Optional[BacktestTrade] = None
    trades: List[BacktestTrade] = []
    equity_curve: List[float] = []
    pending_entry: Optional[str] = None
    pending_exit = False
    skipped = {"daily_loss_limit": 0, "risk_rejected": 0, "min_notional": 0}
    day, day_start = None, starting_balance
    bars_in_market = 0

    def close(pos: BacktestTrade, raw_price: float, i: int, reason: str) -> None:
        nonlocal cash
        s = slip + (stop_slip if reason == "stop_loss" else 0.0)
        price = raw_price * (1 - s) if pos.side == "long" else raw_price * (1 + s)
        exit_fee = price * pos.quantity * fee_rate
        pos.exit_time, pos.exit_price, pos.exit_reason, pos.exit_index = _ts(ts[i]), price, reason, i
        pos.fees += exit_fee
        pos.pnl = unrealized_pnl(pos.side, pos.entry_price, price, pos.quantity) - pos.fees
        cash += pos.pnl
        trades.append(pos)

    for i in range(first, len(ts)):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if days[i] != day:  # UTC midnight reset
            open_upnl = (unrealized_pnl(position.side, position.entry_price, o, position.quantity) - position.fees
                         if position else 0.0)
            day, day_start = days[i], cash + open_upnl

        # 1) orders decided on the previous close fill at this open
        if position and pending_exit:
            close(position, o, i, "trend_flip")
            position = None
        if pending_entry and position is None:
            entry = o * (1 + slip) if pending_entry == "long" else o * (1 - slip)
            plan = risk.plan_trade("BT", pending_entry, entry, float(atrs[i - 1]), cash, [],
                                   day_start_equity=day_start, available_cash=cash, qty_step=qty_step)
            if not plan.allowed:
                skipped["risk_rejected"] += 1
            elif plan.notional < min_notional:
                skipped["min_notional"] += 1
            else:
                fee = entry * plan.quantity * fee_rate
                position = BacktestTrade(side=plan.side, entry_time=_ts(ts[i]), entry_price=entry,
                                         quantity=plan.quantity, stop_loss=plan.stop_loss,
                                         take_profit=plan.take_profit, fees=fee, initial_stop=plan.stop_loss,
                                         highest_price=entry, lowest_price=entry, entry_index=i,
                                         risk_amount=plan.risk_amount)
        pending_entry, pending_exit = None, False

        # 2) intra-candle stop / target (stop first if both touched: conservative; gaps fill at the open)
        if position:
            bars_in_market += 1
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
        if position and not np.isnan(atrs[i]):
            position.highest_price = max(position.highest_price, h)
            position.lowest_price = min(position.lowest_price, l)
            position.stop_loss = risk.trailing_stop_for(asdict(position), float(atrs[i]))

        # 4) signals on the closed candle -> act at next open
        if position:
            pending_exit = bool(exit_long[i]) if position.side == "long" else bool(exit_short[i])
        elif settings.get("trading_enabled", True) and (long_sig[i] or short_sig[i]):
            if is_daily_loss_limit_hit(day_start, cash, float(settings["daily_loss_limit_pct"])):
                skipped["daily_loss_limit"] += 1
            else:
                pending_entry = "long" if long_sig[i] else "short"

        upnl = unrealized_pnl(position.side, position.entry_price, c, position.quantity) if position else 0.0
        equity_curve.append(cash + upnl - (position.fees if position else 0.0))

    if position:  # mark-to-market close at the end
        close(position, float(closes[-1]), len(ts) - 1, "end_of_data")
        equity_curve[-1] = cash
    if not equity_curve:
        equity_curve = [starting_balance]

    closed = [{"pnl": t.pnl, "fees": t.fees, "closed_at": t.exit_time, "id": n} for n, t in enumerate(trades)]
    stats = compute_performance(closed, starting_balance)
    stats["final_equity"] = cash
    stats["return_pct"] = (cash / starting_balance - 1) * 100.0
    curve = np.array(equity_curve) if equity_curve else np.array([starting_balance])
    peak = np.maximum.accumulate(curve)
    stats["max_drawdown_mtm_pct"] = float(((peak - curve) / peak).max() * 100.0)
    stats["candles"] = len(ts) - first
    stats.update(_extra_stats(trades, ts[first:], curve, closes[first:], bars_in_market, starting_balance))
    stats["skipped_signals"] = skipped
    return {"trades": trades, "stats": stats, "equity_curve": equity_curve,
            "timestamps": ts[first:].tolist()}


def _extra_stats(trades: List[BacktestTrade], ts: np.ndarray, curve: np.ndarray, closes: np.ndarray,
                 bars_in_market: int, starting_balance: float) -> Dict[str, Any]:
    n = len(ts)
    out: Dict[str, Any] = {
        "exit_reasons": {},
        "avg_bars_held": float(np.mean([t.exit_index - t.entry_index + 1 for t in trades])) if trades else 0.0,
        "exposure_pct": bars_in_market / n * 100.0 if n else 0.0,
        "avg_r": float(np.mean([t.r_multiple for t in trades])) if trades else 0.0,
        "buy_hold_return_pct": (closes[-1] / closes[0] - 1) * 100.0 if n else 0.0,
    }
    for t in trades:
        out["exit_reasons"][t.exit_reason] = out["exit_reasons"].get(t.exit_reason, 0) + 1
    # daily mark-to-market returns -> annualised Sharpe (crypto trades 365 days a year)
    if n > 1:
        daily = pd.Series(curve, index=pd.to_datetime(ts, unit="ms", utc=True)).resample("1D").last().dropna()
        rets = daily.pct_change().dropna()
        out["sharpe"] = float(rets.mean() / rets.std() * np.sqrt(365)) if len(rets) > 1 and rets.std() > 0 else 0.0
        years = (ts[-1] - ts[0]) / (365.25 * 86_400_000)
        final = curve[-1]
        out["cagr_pct"] = ((final / starting_balance) ** (1 / years) - 1) * 100.0 if years > 0 and final > 0 else 0.0
    else:
        out["sharpe"], out["cagr_pct"] = 0.0, 0.0
    return out


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
    df = pd.read_csv(path)  # .csv or .csv.gz
    df.columns = [c.strip().lower() for c in df.columns]
    if not np.issubdtype(df["timestamp"].dtype, np.number):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).astype("int64") // 1_000_000
    elif df["timestamp"].max() > 1e14:  # microseconds (e.g. Binance dumps from 2025) -> ms
        df["timestamp"] = df["timestamp"] // 1000
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
    ap.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage on every fill (bps)")
    ap.add_argument("--stop-slippage-bps", type=float, default=5.0,
                    help="Extra slippage on stop-loss exits (bps), on top of --slippage-bps")
    ap.add_argument("--min-notional", type=float, default=10.0, help="Skip orders smaller than this (quote)")
    ap.add_argument("--json", help="Write the summary statistics to this JSON file")
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

    result = run_backtest(df, settings, args.balance, args.fee, args.slippage_bps,
                          stop_slippage_bps=args.stop_slippage_bps, min_notional=args.min_notional)
    s = result["stats"]
    print(f"Candles: {s['candles']}  {_ts(df['timestamp'].iloc[0])} -> {_ts(df['timestamp'].iloc[-1])}")
    print(format_performance(s))
    print(f"final_equity={s['final_equity']:.2f} return={s['return_pct']:.2f}% "
          f"max_dd_mark_to_market={s['max_drawdown_mtm_pct']:.2f}%")
    print(f"sharpe={s['sharpe']:.2f} cagr={s['cagr_pct']:.2f}% exposure={s['exposure_pct']:.1f}% "
          f"avg_r={s['avg_r']:.2f} buy_and_hold={s['buy_hold_return_pct']:.2f}% exits={s['exit_reasons']}")
    if args.json:
        import json

        with open(args.json, "w") as fh:
            json.dump(s, fh, indent=2, default=float)
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
