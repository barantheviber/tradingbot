import io
import zipfile

import pandas as pd
import pytest

from backtest import generate_synthetic_ohlcv, load_csv, run_backtest
from scripts.backtest_matrix import aggregate, periods
from scripts.download_history import last_complete_month, months_between, pair_code, parse_kline_csv


def test_start_ms_only_trades_after_start():
    df = generate_synthetic_ohlcv(3000, seed=11)
    start = int(df["timestamp"].iloc[1500])
    res = run_backtest(df, {"min_confirmations": 2}, start_ms=start)
    assert res["stats"]["candles"] == 1500
    assert res["trades"] and all(pd.Timestamp(t.entry_time) >= pd.Timestamp(start, unit="ms", tz="UTC")
                                 for t in res["trades"])


def test_costs_reduce_pnl_and_stop_slippage_applies_to_stops_only():
    df = generate_synthetic_ohlcv(3000, seed=11)
    free = run_backtest(df, {"min_confirmations": 2}, fee_rate=0, slippage_bps=0, stop_slippage_bps=0)
    costly = run_backtest(df, {"min_confirmations": 2}, fee_rate=0.001, slippage_bps=5, stop_slippage_bps=20)
    assert costly["stats"]["final_equity"] < free["stats"]["final_equity"]
    for t in costly["trades"]:
        if t.exit_reason == "stop_loss" and t.side == "long":
            assert t.exit_price <= t.stop_loss * (1 - 0.0025) + 1e-9
    assert all(t.risk_amount > 0 for t in costly["trades"])


def test_min_notional_skips_tiny_orders():
    df = generate_synthetic_ohlcv(3000, seed=11)
    res = run_backtest(df, {"min_confirmations": 2}, starting_balance=100, min_notional=1_000)
    assert res["stats"]["trades"] == 0 and res["stats"]["skipped_signals"]["min_notional"] > 0


def test_parse_binance_kline_csv_handles_header_and_microseconds():
    ms_row = "1735689600000,1,2,0.5,1.5,10,1735693199999,0,0,0,0,0\n"
    us_row = "1735693200000000,1.5,2,1,1.8,12,1735696799999999,0,0,0,0,0\n"
    header = "open_time,open,high,low,close,volume,close_time,a,b,c,d,e\n"
    df = parse_kline_csv((header + ms_row + us_row).encode())
    assert df["timestamp"].tolist() == [1735689600000, 1735693200000]
    assert df["close"].tolist() == [1.5, 1.8]


def test_download_helpers(tmp_path):
    assert months_between("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
    assert last_complete_month(pd.Timestamp("2026-09-27", tz="UTC").to_pydatetime()) == "2026-08"
    assert pair_code("btc/usdt:USDT") == "BTCUSDT"
    path = tmp_path / "X-1h.csv.gz"
    generate_synthetic_ohlcv(50).to_csv(path, index=False, compression="gzip")
    assert len(load_csv(str(path))) == 50


def test_matrix_periods_and_aggregate():
    df = generate_synthetic_ohlcv(24 * 800, seed=3)  # ~2.2 years of hourly candles from Nov 2023
    names = [p[0] for p in periods(df, "2025-01-01", yearly=True)]
    assert names[:3] == ["full", "in", "out"] and "2024" in names
    rows = [{"trades": 2, "sharpe": 1.0, "return_pct": 5.0, "max_drawdown_mtm_pct": 3.0, "profit_factor": 2.0,
             "win_rate_pct": 50.0},
            {"trades": 0, "sharpe": 0.0, "return_pct": 0.0, "max_drawdown_mtm_pct": 0.0, "profit_factor": 0.0,
             "win_rate_pct": 0.0}]
    a = aggregate(rows)
    assert a["positive_markets"] == 1 and a["mean_win_rate_pct"] == pytest.approx(50.0)


def test_stopped_trades_lose_at_most_the_risk_budget():
    # risk budget = qty * (stop distance + round-trip costs); a stop that fills at its level stays within it
    df = generate_synthetic_ohlcv(3000, seed=11)
    res = run_backtest(df, {"min_confirmations": 2, "max_symbol_exposure_pct": 100.0},
                       fee_rate=0.001, slippage_bps=5, stop_slippage_bps=5)
    stops = [t for t in res["trades"] if t.exit_reason == "stop_loss" and t.stop_loss == t.initial_stop
             and t.exit_price >= t.stop_loss * (1 - 0.0011)]  # no gap through the stop
    assert stops
    for t in stops:
        assert -t.pnl <= t.risk_amount * 1.0001
