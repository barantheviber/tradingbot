import pytest

from risk_manager import (
    DailyPnLTracker,
    RiskLimitExceeded,
    RiskParams,
    check_exposure_limit,
    check_max_positions,
    compute_position_size,
    update_trailing_stop,
)
from strategy import Side


def make_params(**overrides) -> RiskParams:
    defaults = dict(
        risk_per_trade_pct=1.0,
        risk_reward_ratio=2.0,
        atr_sl_multiplier=1.5,
        trailing_atr_multiplier=1.5,
        max_daily_drawdown_pct=5.0,
        max_concurrent_positions=3,
        max_exposure_per_symbol_pct=20.0,
    )
    defaults.update(overrides)
    return RiskParams(**defaults)


class TestComputePositionSize:
    def test_long_position_sizing_math(self):
        params = make_params(risk_per_trade_pct=1.0, atr_sl_multiplier=2.0, risk_reward_ratio=2.0)
        # equity=10_000 -> risk_amount=100; atr=10 -> stop_distance=20
        # quantity = 100 / 20 = 5
        result = compute_position_size(
            side=Side.LONG, entry_price=1000.0, atr_value=10.0, account_equity=10_000.0, params=params
        )
        assert result.quantity == pytest.approx(5.0)
        assert result.stop_loss == pytest.approx(1000.0 - 20.0)
        assert result.take_profit == pytest.approx(1000.0 + 20.0 * 2.0)
        assert result.risk_amount == pytest.approx(100.0)
        assert result.stop_distance == pytest.approx(20.0)

    def test_short_position_sl_tp_on_correct_sides(self):
        params = make_params(atr_sl_multiplier=1.0, risk_reward_ratio=3.0)
        result = compute_position_size(
            side=Side.SHORT, entry_price=500.0, atr_value=5.0, account_equity=10_000.0, params=params
        )
        assert result.stop_loss == pytest.approx(500.0 + 5.0)
        assert result.take_profit == pytest.approx(500.0 - 5.0 * 3.0)

    def test_raises_on_non_positive_atr(self):
        params = make_params()
        with pytest.raises(ValueError):
            compute_position_size(Side.LONG, 100.0, 0.0, 10_000.0, params)

    def test_raises_on_non_positive_entry_price(self):
        params = make_params()
        with pytest.raises(ValueError):
            compute_position_size(Side.LONG, 0.0, 5.0, 10_000.0, params)


class TestTrailingStop:
    def test_long_trailing_stop_only_moves_up(self):
        params = make_params(trailing_atr_multiplier=1.0)
        # price rose - stop should move up.
        new_stop = update_trailing_stop(Side.LONG, current_stop=90.0, current_price=110.0, atr_value=5.0, params=params)
        assert new_stop == pytest.approx(105.0)

        # price then drops - stop must NOT move back down.
        new_stop_2 = update_trailing_stop(Side.LONG, current_stop=new_stop, current_price=95.0, atr_value=5.0, params=params)
        assert new_stop_2 == pytest.approx(new_stop)

    def test_short_trailing_stop_only_moves_down(self):
        params = make_params(trailing_atr_multiplier=1.0)
        new_stop = update_trailing_stop(Side.SHORT, current_stop=110.0, current_price=90.0, atr_value=5.0, params=params)
        assert new_stop == pytest.approx(95.0)

        new_stop_2 = update_trailing_stop(Side.SHORT, current_stop=new_stop, current_price=105.0, atr_value=5.0, params=params)
        assert new_stop_2 == pytest.approx(new_stop)


class TestExposureAndPositionLimits:
    def test_exposure_limit_raises_when_exceeded(self):
        params = make_params(max_exposure_per_symbol_pct=10.0)
        with pytest.raises(RiskLimitExceeded):
            check_exposure_limit(symbol_notional=500.0, trade_notional=600.0, account_equity=10_000.0, params=params)

    def test_exposure_limit_allows_within_bounds(self):
        params = make_params(max_exposure_per_symbol_pct=20.0)
        # (500 + 600) / 10000 = 11% <= 20% -> should not raise
        check_exposure_limit(symbol_notional=500.0, trade_notional=600.0, account_equity=10_000.0, params=params)

    def test_max_positions_raises_when_at_limit(self):
        params = make_params(max_concurrent_positions=2)
        with pytest.raises(RiskLimitExceeded):
            check_max_positions(open_position_count=2, params=params)

    def test_max_positions_allows_below_limit(self):
        params = make_params(max_concurrent_positions=2)
        check_max_positions(open_position_count=1, params=params)


class TestDailyPnLTracker:
    def test_halts_trading_once_drawdown_limit_hit(self):
        params = make_params(max_daily_drawdown_pct=5.0)
        tracker = DailyPnLTracker(starting_equity=10_000.0)
        tracker.record_realized_pnl(-600.0)  # 6% loss
        assert tracker.drawdown_pct() == pytest.approx(6.0)
        assert tracker.trading_halted(params) is True

    def test_does_not_halt_below_limit(self):
        params = make_params(max_daily_drawdown_pct=5.0)
        tracker = DailyPnLTracker(starting_equity=10_000.0)
        tracker.record_realized_pnl(-200.0)  # 2% loss
        assert tracker.trading_halted(params) is False

    def test_profit_does_not_count_as_drawdown(self):
        params = make_params(max_daily_drawdown_pct=5.0)
        tracker = DailyPnLTracker(starting_equity=10_000.0)
        tracker.record_realized_pnl(500.0)
        assert tracker.drawdown_pct() == pytest.approx(0.0)
        assert tracker.trading_halted(params) is False
