import pandas as pd
import pytest

from backtest import generate_synthetic_ohlcv, run_backtest
from config import default_settings_values
from exchange_client import drop_unclosed_candles
from strategy import StrategyParams, compute_indicators, generate_signal


def test_params_from_settings_types_and_clamps():
    s = default_settings_values()
    s.update({"ema_trend_period": 50.0, "min_confirmations": 9, "unknown": 1})
    p = StrategyParams.from_settings(s)
    assert p.ema_trend_period == 50 and isinstance(p.ema_trend_period, int)
    assert p.min_confirmations == 3


def test_no_look_ahead_indicators_do_not_change_when_future_is_appended():
    df = generate_synthetic_ohlcv(1200, seed=3)
    params = StrategyParams.from_settings({**default_settings_values(), "min_confirmations": 2})
    full = compute_indicators(df, params)
    cut = 900
    partial = compute_indicators(df.iloc[:cut], params)
    cols = ["ema_trend", "rsi", "macd", "atr", "donchian_high", "volume_ma", "long_signal", "short_signal"]
    pd.testing.assert_frame_equal(full[cols].iloc[:cut].reset_index(drop=True), partial[cols].reset_index(drop=True))


def test_generate_signal_warmup_hold():
    df = generate_synthetic_ohlcv(100)
    sig = generate_signal(df, StrategyParams())
    assert sig.action == "hold" and "warmup" in sig.reasons


def test_signals_fire_and_respect_trend_filter():
    df = generate_synthetic_ohlcv(4000, seed=7)
    params = StrategyParams.from_settings({**default_settings_values(), "min_confirmations": 2,
                                           "allow_short": True})
    ind = compute_indicators(df, params)
    longs, shorts = ind[ind["long_signal"]], ind[ind["short_signal"]]
    assert len(longs) > 0 and len(shorts) > 0
    assert (longs["close"] > longs["ema_trend"]).all()
    assert (shorts["close"] < shorts["ema_trend"]).all()
    assert (longs["long_confirmations"] >= 2).all()


def test_short_disabled_by_default():
    df = generate_synthetic_ohlcv(3000, seed=7)
    ind = compute_indicators(df, StrategyParams.from_settings(default_settings_values()))
    assert not ind["short_signal"].any()


def test_drop_unclosed_candles():
    df = pd.DataFrame({"timestamp": [0, 60_000, 120_000], "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                       "volume": 1.0})
    out = drop_unclosed_candles(df, 60_000, now_ms=150_000)  # candle @120k closes at 180k -> dropped
    assert out["timestamp"].tolist() == [0, 60_000]


def test_backtest_smoke_and_accounting():
    df = generate_synthetic_ohlcv(3000, seed=11)
    res = run_backtest(df, {"min_confirmations": 2}, starting_balance=10_000)
    stats = res["stats"]
    assert stats["trades"] == len(res["trades"]) > 0
    # cash is accumulated trade by trade; compare with tolerance for float summation order
    assert stats["final_equity"] == pytest.approx(10_000 + sum(t.pnl for t in res["trades"]))
    for t in res["trades"]:
        assert t.exit_reason in {"stop_loss", "take_profit", "trend_flip", "end_of_data"}
        # risk per trade never exceeds 1% of starting-ish equity by more than fees + slippage noise
        assert t.quantity * abs(t.entry_price - t.initial_stop) <= 0.011 * 2 * 10_000


def test_regime_filters_only_remove_signals():
    from strategy import StrategyParams, compute_indicators

    df = generate_synthetic_ohlcv(3000, seed=5)
    base = compute_indicators(df, StrategyParams(min_confirmations=2))
    for extra in ({"ema_slope_bars": 24}, {"adx_min": 25.0}, {"min_atr_pct": 3.0}):
        filt = compute_indicators(df, StrategyParams(min_confirmations=2, **extra))
        assert (filt["long_signal"] <= base["long_signal"]).all(), extra
        assert filt["long_signal"].sum() < base["long_signal"].sum(), extra
    assert "adx" in compute_indicators(df, StrategyParams(adx_min=20.0)).columns


def test_regime_filter_settings_are_clamped():
    from strategy import StrategyParams

    p = StrategyParams.from_settings({"ema_slope_bars": -5, "adx_period": 0, "adx_min": -1, "min_atr_pct": -2})
    assert (p.ema_slope_bars, p.adx_period, p.adx_min, p.min_atr_pct) == (0, 1, 0.0, 0.0)
