"""Walk-forward evaluation: do the settings hold up window by window, and does re-fitting help?

Rolling windows over the history (default: 24 months to fit, the next 6 months
to test, moved forward 6 months at a time). In every window:

* ``fixed``  - the bot's current defaults, unchanged, on the test months;
* ``refit``  - the grid combination with the best mean Sharpe across all pairs on
  the fit months, then run on the test months (it never sees them);
* baselines given with ``--baseline`` (for example the previous defaults).

Candles before a window only warm up the indicators; each window starts flat
with the same balance. Test windows are then chained per pair into one
out-of-sample equity curve. Costs are those of ``backtest_matrix.COST``.

    python scripts/walk_forward.py --data data/history --timeframe 4h --out walk-forward
"""

from __future__ import annotations

import argparse
import glob
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import _parse_overrides, load_csv, run_backtest  # noqa: E402
from scripts.backtest_matrix import COST, market_of  # noqa: E402

DEFAULT_GRID = ("atr_sl_multiplier=2,2.5,3,3.5,4;trailing_atr_multiplier=3,4,5,6;"
                "risk_reward_ratio=3,5,10,20;rsi_long_max=70,100")
PREVIOUS_DEFAULTS = "previous_defaults:atr_sl_multiplier=1.5,risk_reward_ratio=2,trailing_atr_multiplier=2,rsi_long_max=70"
HOLDOUT_START = "2024-07"  # the fixed defaults were tuned on months before this (see docs/backtest-raporu.md)


@dataclass(frozen=True)
class Fold:
    fit_start: pd.Period
    fit_end: pd.Period  # exclusive
    test_start: pd.Period
    test_end: pd.Period  # exclusive

    @staticmethod
    def _ms(p: pd.Period) -> int:
        return int(p.start_time.tz_localize("UTC").timestamp() * 1000)

    @property
    def fit_ms(self) -> Tuple[int, int]:
        return self._ms(self.fit_start), self._ms(self.fit_end)

    @property
    def test_ms(self) -> Tuple[int, int]:
        return self._ms(self.test_start), self._ms(self.test_end)

    @property
    def test_label(self) -> str:
        return f"{self.test_start.strftime('%Y-%m')}..{(self.test_end - 1).strftime('%Y-%m')}"

    @property
    def fit_label(self) -> str:
        return f"{self.fit_start.strftime('%Y-%m')}..{(self.fit_end - 1).strftime('%Y-%m')}"


def make_folds(first_month: str, last_month: str, fit_months: int = 24, test_months: int = 6,
               step_months: int = 6) -> List[Fold]:
    """Rolling windows; the last test window may be shorter (it stops at ``last_month``)."""
    first, last = pd.Period(first_month, freq="M"), pd.Period(last_month, freq="M")
    folds: List[Fold] = []
    fit_start = first
    while True:
        test_start = fit_start + fit_months
        if test_start > last:
            break
        test_end = min(test_start + test_months, last + 1)
        folds.append(Fold(fit_start, test_start, test_start, test_end))
        fit_start += step_months
    return folds


def parse_grid(spec: str) -> List[Dict[str, Any]]:
    """'a=1,2;b=3' -> [{'a':1,'b':3}, {'a':2,'b':3}] (values coerced to the setting types)."""
    keys, values = [], []
    for part in [p for p in spec.split(";") if p.strip()]:
        key, _, vals = part.partition("=")
        keys.append(key.strip())
        values.append([v.strip() for v in vals.split(",") if v.strip()])
    return [_parse_overrides([f"{k}={v}" for k, v in zip(keys, combo)]) for combo in itertools.product(*values)]


def parse_named(text: str) -> Tuple[str, Dict[str, Any]]:
    name, _, spec = text.partition(":")
    return name.strip(), _parse_overrides([x for x in spec.split(",") if x.strip()])


# ------------------------------------------------------------------ workers
_DATA: Dict[str, pd.DataFrame] = {}


def _frame(path: str) -> pd.DataFrame:
    if path not in _DATA:
        _DATA[path] = load_csv(path)
    return _DATA[path]


def _run(args: Tuple[str, Dict[str, Any], int, int, bool]) -> Dict[str, Any]:
    path, overrides, start_ms, end_ms, keep_curve = args
    df = _frame(path)
    res = run_backtest(df[df["timestamp"] < end_ms], overrides, **COST, start_ms=start_ms)
    s = res["stats"]
    out = {k: s[k] for k in ("trades", "win_rate_pct", "profit_factor", "return_pct", "max_drawdown_mtm_pct",
                             "sharpe", "buy_hold_return_pct")}
    if keep_curve:
        out["curve"] = [float(x) for x in res["equity_curve"]]
        out["ts"] = [int(x) for x in res["timestamps"]]
    return out


def _mean(rows: Sequence[Dict[str, Any]], key: str) -> float:
    return float(np.mean([r[key] for r in rows])) if rows else 0.0


def stitched_stats(parts: Sequence[Dict[str, Any]], starting_balance: float = 10_000.0) -> Dict[str, float]:
    """Chain one pair's test windows into one equity curve (each window rescaled to where the last ended)."""
    values: List[float] = []
    stamps: List[int] = []
    level = starting_balance
    for part in parts:
        curve = np.asarray(part["curve"], dtype=float)
        if curve.size == 0:
            continue
        scaled = curve / curve[0] * level if curve[0] > 0 else curve
        values.extend(scaled.tolist())
        stamps.extend(part["ts"])
        level = float(scaled[-1])
    if not values:
        return {"return_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0}
    arr = np.asarray(values)
    peak = np.maximum.accumulate(arr)
    daily = pd.Series(arr, index=pd.to_datetime(stamps, unit="ms", utc=True)).resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(365)) if len(rets) > 1 and rets.std() > 0 else 0.0
    return {"return_pct": (arr[-1] / starting_balance - 1) * 100.0,
            "max_drawdown_pct": float(((peak - arr) / peak).max() * 100.0), "sharpe": sharpe}


# ------------------------------------------------------------------ main flow
def walk_forward(files: List[str], folds: List[Fold], grid: List[Dict[str, Any]],
                 baselines: List[Tuple[str, Dict[str, Any]]], workers: int) -> Dict[str, Any]:
    pairs = [market_of(f)[0] for f in files]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        # 1) fit: every grid combination on every pair, per fold
        fit_jobs = [(f, combo, *fold.fit_ms, False) for fold in folds for combo in grid for f in files]
        fit_stats = list(pool.map(_run, fit_jobs, chunksize=8))
        chosen: List[Dict[str, Any]] = []
        n, g = len(files), len(grid)
        for k, fold in enumerate(folds):
            scores = []
            for j in range(g):
                rows = fit_stats[(k * g + j) * n:(k * g + j + 1) * n]
                scores.append((_mean(rows, "sharpe"), _mean(rows, "return_pct"), j))
            best = max(scores)
            chosen.append({"params": grid[best[2]], "fit_mean_sharpe": best[0], "fit_mean_return_pct": best[1]})

        # 2) test: fixed defaults, refit choice and baselines on every pair, per fold
        variants = [("fixed", lambda k: {})] + [("refit", lambda k: chosen[k]["params"])] + \
                   [(name, (lambda ov: lambda k: ov)(ov)) for name, ov in baselines]
        test_jobs, keys = [], []
        for k, fold in enumerate(folds):
            for name, params_for in variants:
                for f, pair in zip(files, pairs):
                    test_jobs.append((f, params_for(k), *fold.test_ms, True))
                    keys.append((k, name, pair))
        test_stats = list(pool.map(_run, test_jobs, chunksize=4))

    by: Dict[Tuple[int, str, str], Dict[str, Any]] = dict(zip(keys, test_stats))
    names = [v[0] for v in variants]
    fold_rows = []
    for k, fold in enumerate(folds):
        row: Dict[str, Any] = {"fit": fold.fit_label, "test": fold.test_label, "chosen": chosen[k]["params"],
                               "fit_mean_sharpe": chosen[k]["fit_mean_sharpe"],
                               "from_holdout": bool(fold.test_start >= pd.Period(HOLDOUT_START, freq="M"))}
        for name in names:
            rows = [by[(k, name, p)] for p in pairs]
            row[name] = {"mean_return_pct": _mean(rows, "return_pct"), "mean_sharpe": _mean(rows, "sharpe"),
                         "mean_max_dd_pct": _mean(rows, "max_drawdown_mtm_pct"),
                         "positive": int(sum(r["return_pct"] > 0 for r in rows)), "trades": int(sum(r["trades"] for r in rows))}
        row["buy_hold_mean_pct"] = _mean([by[(k, "fixed", p)] for p in pairs], "buy_hold_return_pct")
        fold_rows.append(row)

    def stitched(name: str, fold_ids: Sequence[int]) -> Dict[str, Any]:
        per_pair = {p: stitched_stats([by[(k, name, p)] for k in fold_ids]) for p in pairs}
        vals = list(per_pair.values())
        return {"mean_return_pct": _mean(vals, "return_pct"), "mean_max_dd_pct": _mean(vals, "max_drawdown_pct"),
                "worst_max_dd_pct": max(v["max_drawdown_pct"] for v in vals), "mean_sharpe": _mean(vals, "sharpe"),
                "positive": int(sum(v["return_pct"] > 0 for v in vals)), "pairs": per_pair}

    all_ids = list(range(len(folds)))
    late_ids = [k for k, row in enumerate(fold_rows) if row["from_holdout"]]
    return {"pairs": pairs, "folds": fold_rows, "variants": names,
            "stitched": {name: stitched(name, all_ids) for name in names},
            "stitched_from_2024_07": {name: stitched(name, late_ids) for name in names} if late_ids else {},
            "latest_choice": chosen[-1]["params"] if chosen else {}}


def _checks(fixed: Dict[str, Any], refit: Dict[str, Any], folds: Sequence[Dict[str, Any]],
            dd_tolerance_pct: float) -> Dict[str, Any]:
    wins = sum(f["refit"]["mean_sharpe"] > f["fixed"]["mean_sharpe"] for f in folds)
    checks = {
        "higher_sharpe": refit["mean_sharpe"] > fixed["mean_sharpe"],
        "wins_majority": wins > len(folds) / 2,
        "drawdown_ok": refit["worst_max_dd_pct"] <= fixed["worst_max_dd_pct"] + dd_tolerance_pct,
    }
    return {"refit_window_wins": int(wins), "windows": len(folds), "checks": checks, "pass": all(checks.values())}


def decide(result: Dict[str, Any], dd_tolerance_pct: float = 2.0) -> Dict[str, Any]:
    """Rule fixed before the run: re-fitting replaces the defaults only if, over all test windows AND
    over the windows from ``HOLDOUT_START`` on (where the fixed defaults had no look-ahead), its
    chained out-of-sample mean Sharpe is higher, it wins more than half of the windows, and its
    worst drawdown is not more than ``dd_tolerance_pct`` points worse."""
    out = {"all": _checks(result["stitched"]["fixed"], result["stitched"]["refit"], result["folds"], dd_tolerance_pct)}
    late = [f for f in result["folds"] if f["from_holdout"]]
    if late and result.get("stitched_from_2024_07"):
        out["from_2024_07"] = _checks(result["stitched_from_2024_07"]["fixed"], result["stitched_from_2024_07"]["refit"],
                                      late, dd_tolerance_pct)
    out["adopt_refit"] = all(v["pass"] for v in out.values())
    return out


def _p(params: Dict[str, Any]) -> str:
    short = {"atr_sl_multiplier": "sl", "trailing_atr_multiplier": "trail", "risk_reward_ratio": "rr",
             "rsi_long_max": "rsi_max"}
    return " ".join(f"{short.get(k, k)}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in params.items())


def summary_markdown(result: Dict[str, Any], decision: Dict[str, Any], timeframe: str, grid_size: int) -> str:
    names = result["variants"]
    lines = [f"# Walk-forward ({timeframe}, {len(result['pairs'])} pairs, {grid_size} grid combinations)", "",
             "## Windows (test months only; means across pairs)", "",
             "| fit | test | refit choice | " + " | ".join(f"{n} return % / Sharpe / >0" for n in names) + " | buy & hold % |",
             "|---|---|---|" + "---|" * len(names) + "---|"]
    for f in result["folds"]:
        cells = [f"{f[n]['mean_return_pct']:.2f} / {f[n]['mean_sharpe']:.2f} / {f[n]['positive']}" for n in names]
        lines.append(f"| {f['fit']} | {f['test']} | {_p(f['chosen'])} | " + " | ".join(cells)
                     + f" | {f['buy_hold_mean_pct']:.1f} |")
    for title, key in (("All test windows chained", "stitched"), ("Test windows from 2024-07 chained", "stitched_from_2024_07")):
        if not result.get(key):
            continue
        lines += ["", f"## {title}", "", "| variant | mean return % | mean max DD % | worst max DD % | mean Sharpe | pairs > 0 |",
                  "|---|---|---|---|---|---|"]
        for n in names:
            s = result[key][n]
            lines.append(f"| {n} | {s['mean_return_pct']:.2f} | {s['mean_max_dd_pct']:.2f} | {s['worst_max_dd_pct']:.2f} | "
                         f"{s['mean_sharpe']:.2f} | {s['positive']}/{len(result['pairs'])} |")
    lines += ["", "## Decision", ""]
    for key, label in (("all", "All windows"), ("from_2024_07", "Windows from 2024-07")):
        if key in decision:
            d = decision[key]
            lines.append(f"- {label}: refit beat fixed in {d['refit_window_wins']} of {d['windows']} windows; "
                         f"checks {d['checks']}.")
    lines += ["", f"Adopt refit: **{decision['adopt_refit']}**. Latest window's choice: {_p(result['latest_choice'])}."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Walk-forward evaluation of the strategy defaults")
    ap.add_argument("--data", action="append", default=[], help="Directory with history files (repeatable)")
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--first-month", default="2021-01")
    ap.add_argument("--last-month", default=None, help="Last complete month in the data (default: from the data)")
    ap.add_argument("--fit-months", type=int, default=24)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--step-months", type=int, default=6)
    ap.add_argument("--grid", default=DEFAULT_GRID, help="key=v1,v2;key=v1,v2 (cartesian product)")
    ap.add_argument("--baseline", action="append", default=None, metavar="NAME:KEY=VAL,KEY=VAL")
    ap.add_argument("--out", default="walk-forward-results")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args(argv)

    files = sorted({f for d in (args.data or ["data/history"])
                    for f in glob.glob(os.path.join(d, f"*-{args.timeframe}.csv*"))})
    if not files:
        print("No data files found", file=sys.stderr)
        return 1
    last = args.last_month
    if last is None:
        last_ts = min(int(load_csv(f)["timestamp"].iloc[-1]) for f in files)
        last_day = pd.Timestamp(last_ts, unit="ms")
        last_period = pd.Period(last_day, freq="M")
        # use only complete months
        last = (last_period if (last_day + pd.Timedelta(days=1)).month != last_day.month else last_period - 1).strftime("%Y-%m")
    folds = make_folds(args.first_month, last, args.fit_months, args.test_months, args.step_months)
    if not folds:
        print("Not enough history for one window", file=sys.stderr)
        return 1
    grid = parse_grid(args.grid)
    baselines = [parse_named(b) for b in (args.baseline if args.baseline is not None else [PREVIOUS_DEFAULTS])]
    result = walk_forward(files, folds, grid, baselines, args.workers)
    decision = decide(result)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "walk_forward.json"), "w") as fh:
        json.dump({"timeframe": args.timeframe, "costs": COST, "grid_size": len(grid), "decision": decision,
                   **result}, fh, indent=1, default=float)
    md = summary_markdown(result, decision, args.timeframe, len(grid))
    with open(os.path.join(args.out, "summary.md"), "w") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
