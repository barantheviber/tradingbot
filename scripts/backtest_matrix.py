"""Run backtest.py's simulation over many pairs, timeframes and periods.

Reads every ``*.csv.gz`` / ``*.csv`` in ``--data`` (see download_history.py),
runs each settings variant on:

* ``full``    - the whole history;
* ``in``      - everything before ``--split`` (the development period);
* ``out``     - from ``--split`` on (out-of-sample; earlier candles only warm up indicators);
* ``<year>``  - each calendar year on its own (with ``--yearly``).

and writes ``results.json`` plus a Markdown summary (``summary.md``) to ``--out``.
Variants are the bot's current defaults plus ``--variant name:key=value,key=value``.

    python scripts/backtest_matrix.py --data data/history --out backtest-results --split 2024-07-01 --yearly
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import _parse_overrides, load_csv, run_backtest  # noqa: E402

COST = {"fee_rate": 0.001, "slippage_bps": 5.0, "stop_slippage_bps": 5.0, "min_notional": 10.0}
KEYS = ["trades", "win_rate_pct", "profit_factor", "return_pct", "cagr_pct", "max_drawdown_mtm_pct", "sharpe",
        "avg_r", "exposure_pct", "buy_hold_return_pct", "fees", "exit_reasons", "avg_bars_held"]


def market_of(path: str) -> Tuple[str, str]:
    name = os.path.basename(path).split(".")[0]  # BTCUSDT-1h
    pair, tf = name.rsplit("-", 1)
    return pair, tf


def periods(df: pd.DataFrame, split: str, yearly: bool) -> List[Tuple[str, pd.DataFrame, Any]]:
    ts = df["timestamp"]
    split_ms = int(pd.Timestamp(split, tz="UTC").timestamp() * 1000)
    out = [("full", df, None), ("in", df[ts < split_ms], None), ("out", df, split_ms)]
    if yearly:
        years = pd.to_datetime(ts, unit="ms", utc=True).dt.year
        for y in sorted(years.unique()):
            end_ms = int(pd.Timestamp(f"{y + 1}-01-01", tz="UTC").timestamp() * 1000)
            start_ms = int(pd.Timestamp(f"{y}-01-01", tz="UTC").timestamp() * 1000)
            out.append((str(y), df[ts < end_ms], start_ms))
    return out


def _job(args: Tuple[str, str, Dict[str, Any], str, bool]) -> List[Dict[str, Any]]:
    path, variant, overrides, split, yearly = args
    pair, tf = market_of(path)
    df = load_csv(path)
    rows = []
    for period, part, start_ms in periods(df, split, yearly):
        if len(part) < 300:
            continue
        stats = run_backtest(part, overrides, **COST, start_ms=start_ms)["stats"]
        if stats["candles"] < 100:
            continue
        rows.append({"variant": variant, "pair": pair, "timeframe": tf, "period": period,
                     **{k: stats[k] for k in KEYS}})
    return rows


def _fmt(v: Any, nd: int = 2) -> str:
    if isinstance(v, float):
        return "inf" if v == float("inf") else f"{v:.{nd}f}"
    return str(v)


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Across markets: means are equal-weighted per pair/timeframe."""
    pf = [min(r["profit_factor"], 10.0) for r in rows if r["trades"] > 0]
    return {
        "markets": len(rows),
        "trades": int(sum(r["trades"] for r in rows)),
        "mean_sharpe": float(np.mean([r["sharpe"] for r in rows])) if rows else 0.0,
        "mean_return_pct": float(np.mean([r["return_pct"] for r in rows])) if rows else 0.0,
        "mean_max_dd_pct": float(np.mean([r["max_drawdown_mtm_pct"] for r in rows])) if rows else 0.0,
        "worst_max_dd_pct": float(max([r["max_drawdown_mtm_pct"] for r in rows], default=0.0)),
        "mean_profit_factor": float(np.mean(pf)) if pf else 0.0,
        "mean_win_rate_pct": float(np.mean(wins)) if (wins := [r["win_rate_pct"] for r in rows if r["trades"]]) else 0.0,
        "positive_markets": int(sum(r["return_pct"] > 0 for r in rows)),
    }


def summary_markdown(rows: List[Dict[str, Any]], split: str, cost: Dict[str, Any]) -> str:
    variants = list(dict.fromkeys(r["variant"] for r in rows))
    lines = [f"# Real-data backtest", "",
             f"Costs: fee {cost['fee_rate'] * 100:.2f}% per fill, slippage {cost['slippage_bps']} bps per fill, "
             f"+{cost['stop_slippage_bps']} bps on stop exits. Out-of-sample from {split}.", ""]
    lines += ["## Variants across all markets", "",
              "| variant | period | markets | trades | mean Sharpe | mean return % | mean max DD % | worst max DD % "
              "| mean PF | mean win % | markets > 0 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in variants:
        for period in ("full", "in", "out"):
            sel = [r for r in rows if r["variant"] == v and r["period"] == period]
            if not sel:
                continue
            a = aggregate(sel)
            lines.append(f"| {v} | {period} | {a['markets']} | {a['trades']} | {_fmt(a['mean_sharpe'])} | "
                         f"{_fmt(a['mean_return_pct'])} | {_fmt(a['mean_max_dd_pct'])} | "
                         f"{_fmt(a['worst_max_dd_pct'])} | {_fmt(a['mean_profit_factor'])} | "
                         f"{_fmt(a['mean_win_rate_pct'], 1)} | {a['positive_markets']}/{a['markets']} |")
    for v in variants:
        lines += ["", f"## `{v}` per market", "",
                  "| pair | tf | period | trades | win % | PF | return % | max DD % | Sharpe | avg R | exposure % "
                  "| buy & hold % |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted((r for r in rows if r["variant"] == v),
                        key=lambda r: (r["pair"], r["timeframe"], r["period"] not in ("full", "in", "out"),
                                       r["period"])):
            lines.append(f"| {r['pair']} | {r['timeframe']} | {r['period']} | {r['trades']} | "
                         f"{_fmt(r['win_rate_pct'], 1)} | {_fmt(r['profit_factor'])} | {_fmt(r['return_pct'])} | "
                         f"{_fmt(r['max_drawdown_mtm_pct'])} | {_fmt(r['sharpe'])} | {_fmt(r['avg_r'])} | "
                         f"{_fmt(r['exposure_pct'], 1)} | {_fmt(r['buy_hold_return_pct'], 1)} |")
    return "\n".join(lines) + "\n"


def parse_variant(text: str) -> Tuple[str, Dict[str, Any]]:
    name, _, spec = text.partition(":")
    items = [x for x in spec.split(",") if x.strip()]
    return name.strip(), _parse_overrides(items)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest many markets and periods")
    ap.add_argument("--data", default="data/history")
    ap.add_argument("--out", default="backtest-results")
    ap.add_argument("--split", default="2024-07-01", help="Out-of-sample start (UTC date)")
    ap.add_argument("--yearly", action="store_true", help="Also evaluate every calendar year separately")
    ap.add_argument("--variant", action="append", default=[], metavar="NAME:KEY=VAL,KEY=VAL")
    ap.add_argument("--no-defaults", action="store_true", help="Skip the current-defaults variant")
    ap.add_argument("--timeframes", default="", help="Only these timeframes (comma separated)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.data, "*.csv.gz")) + glob.glob(os.path.join(args.data, "*.csv")))
    if args.timeframes:
        wanted = {t.strip() for t in args.timeframes.split(",")}
        files = [f for f in files if market_of(f)[1] in wanted]
    if not files:
        print(f"No data files in {args.data}", file=sys.stderr)
        return 1
    variants = ([] if args.no_defaults else [("defaults", {})]) + [parse_variant(v) for v in args.variant]
    jobs = [(f, name, ov, args.split, args.yearly) for name, ov in variants for f in files]
    rows: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for part in pool.map(_job, jobs):
            rows.extend(part)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "results.json"), "w") as fh:
        json.dump({"split": args.split, "costs": COST, "variants": {n: o for n, o in variants}, "rows": rows},
                  fh, indent=1, default=float)
    md = summary_markdown(rows, args.split, COST)
    with open(os.path.join(args.out, "summary.md"), "w") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
