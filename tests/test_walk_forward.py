import json

import pandas as pd
import pytest

from backtest import generate_synthetic_ohlcv
from scripts.walk_forward import decide, main, make_folds, parse_grid, parse_named, stitched_stats


def test_make_folds_rolls_and_clips_the_last_window():
    folds = make_folds("2021-01", "2026-08", fit_months=24, test_months=6, step_months=6)
    assert [f.test_label for f in folds] == [
        "2023-01..2023-06", "2023-07..2023-12", "2024-01..2024-06", "2024-07..2024-12",
        "2025-01..2025-06", "2025-07..2025-12", "2026-01..2026-06", "2026-07..2026-08"]
    assert folds[0].fit_label == "2021-01..2022-12"
    for f in folds:  # a window never tests on months it was fitted on
        assert f.fit_ms[1] == f.test_ms[0] and f.fit_ms[0] < f.fit_ms[1] < f.test_ms[1]
    assert folds[0].test_ms[0] == int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
    assert make_folds("2021-01", "2022-06", fit_months=24) == []


def test_parse_grid_and_named_baseline():
    grid = parse_grid("atr_sl_multiplier=2,3;risk_reward_ratio=5")
    assert grid == [{"atr_sl_multiplier": 2.0, "risk_reward_ratio": 5.0},
                    {"atr_sl_multiplier": 3.0, "risk_reward_ratio": 5.0}]
    name, overrides = parse_named("old:atr_sl_multiplier=1.5,rsi_long_max=70")
    assert name == "old" and overrides == {"atr_sl_multiplier": 1.5, "rsi_long_max": 70.0}


def test_stitched_stats_chains_windows():
    day = 86_400_000
    parts = [{"curve": [100.0, 110.0], "ts": [0, day]},
             {"curve": [50.0, 45.0], "ts": [2 * day, 3 * day]}]  # each window starts from its own balance
    s = stitched_stats(parts, starting_balance=1000.0)
    assert s["return_pct"] == pytest.approx((1.1 * 0.9 - 1) * 100)
    assert s["max_drawdown_pct"] == pytest.approx(10.0)
    assert stitched_stats([])["return_pct"] == 0.0


def _result(fixed_sharpes, refit_sharpes, late_from, fixed_all, refit_all, fixed_late, refit_late):
    folds = [{"fixed": {"mean_sharpe": a}, "refit": {"mean_sharpe": b}, "from_holdout": i >= late_from}
             for i, (a, b) in enumerate(zip(fixed_sharpes, refit_sharpes))]
    return {"folds": folds, "stitched": {"fixed": fixed_all, "refit": refit_all},
            "stitched_from_2024_07": {"fixed": fixed_late, "refit": refit_late}}


def test_decide_needs_all_windows_and_late_windows():
    good = {"mean_sharpe": 1.0, "worst_max_dd_pct": 10.0}
    bad = {"mean_sharpe": 0.2, "worst_max_dd_pct": 10.0}
    res = _result([0, 0, 0, 0], [1, 1, 1, 1], 2, bad, good, bad, good)
    assert decide(res)["adopt_refit"] is True
    # wins overall but loses after 2024-07 -> keep the defaults
    res = _result([0, 0, 0, 0, 1, 1], [1, 1, 1, 1, 0, 0], 4, bad, good, good, bad)
    d = decide(res)
    assert d["all"]["pass"] and not d["from_2024_07"]["pass"] and d["adopt_refit"] is False
    # higher Sharpe but a much deeper drawdown -> keep the defaults
    deep = {"mean_sharpe": 1.0, "worst_max_dd_pct": 13.0}
    res = _result([0, 0, 0, 0], [1, 1, 1, 1], 2, bad, deep, bad, deep)
    assert decide(res)["adopt_refit"] is False


def test_walk_forward_end_to_end_on_synthetic_data(tmp_path):
    data = tmp_path / "hist"
    data.mkdir()
    for i, pair in enumerate(("AAAUSDT", "BBBUSDT")):  # hourly candles, Nov 2023 .. Dec 2024
        generate_synthetic_ohlcv(24 * 400, seed=5 + i).to_csv(data / f"{pair}-1h.csv.gz", index=False,
                                                               compression="gzip")
    out = tmp_path / "out"
    rc = main(["--data", str(data), "--timeframe", "1h", "--first-month", "2024-01", "--last-month", "2024-11",
               "--fit-months", "4", "--test-months", "2", "--step-months", "2",
               "--grid", "atr_sl_multiplier=2,3;min_confirmations=2", "--out", str(out), "--workers", "1"])
    assert rc == 0
    res = json.loads((out / "walk_forward.json").read_text())
    assert res["grid_size"] == 2 and res["pairs"] == ["AAAUSDT", "BBBUSDT"]
    assert [f["test"] for f in res["folds"]] == ["2024-05..2024-06", "2024-07..2024-08", "2024-09..2024-10",
                                                 "2024-11..2024-11"]
    assert set(res["variants"]) == {"fixed", "refit", "previous_defaults"}
    assert res["folds"][0]["chosen"]["atr_sl_multiplier"] in (2.0, 3.0)
    assert "adopt_refit" in res["decision"] and "from_2024_07" in res["decision"]
    assert "Adopt refit" in (out / "summary.md").read_text()
