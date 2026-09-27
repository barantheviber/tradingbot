import pytest

from risk_manager import (
    RiskManager,
    calculate_position_size,
    calculate_sl_tp,
    check_exit,
    daily_loss_pct,
    is_daily_loss_limit_hit,
    update_trailing_stop,
)
from config import default_settings_values


# ------------------------------------------------------------ sizing
def test_position_size_risks_exact_percentage():
    # 10k equity, 1% risk = 100; stop distance 50 -> 2 units
    qty = calculate_position_size(10_000, entry=1_000, stop=950, risk_pct=1.0)
    assert qty == pytest.approx(2.0)
    assert qty * (1_000 - 950) == pytest.approx(100.0)


def test_position_size_same_for_short_side():
    assert calculate_position_size(10_000, 1_000, 1_050, 1.0) == pytest.approx(2.0)


def test_position_size_capped_by_max_notional():
    # uncapped would be 2 units (2000 notional); cap at 1500 notional -> 1.5 units
    assert calculate_position_size(10_000, 1_000, 950, 1.0, max_notional=1_500) == pytest.approx(1.5)


def test_position_size_rounded_down_to_step():
    assert calculate_position_size(10_000, 1_000, 970, 1.0, qty_step=0.01) == pytest.approx(3.33)


@pytest.mark.parametrize("equity,entry,stop,risk", [(0, 100, 90, 1), (1000, 100, 100, 1), (1000, 100, 90, 0),
                                                     (-5, 100, 90, 1)])
def test_position_size_degenerate_inputs_return_zero(equity, entry, stop, risk):
    assert calculate_position_size(equity, entry, stop, risk) == 0.0


def test_wider_atr_means_smaller_position():
    small_atr = calculate_position_size(10_000, 100, calculate_sl_tp(100, 1, "long", 1.5, 2)[0], 1)
    big_atr = calculate_position_size(10_000, 100, calculate_sl_tp(100, 4, "long", 1.5, 2)[0], 1)
    assert big_atr == pytest.approx(small_atr / 4)


# ------------------------------------------------------------ SL / TP
def test_sl_tp_long_default_two_to_one():
    sl, tp = calculate_sl_tp(100.0, atr=2.0, side="long", atr_multiplier=1.5, risk_reward=2.0)
    assert sl == pytest.approx(97.0)
    assert tp == pytest.approx(106.0)
    assert (tp - 100) / (100 - sl) == pytest.approx(2.0)


def test_sl_tp_short():
    sl, tp = calculate_sl_tp(100.0, 2.0, "short", 1.5, 3.0)
    assert sl == pytest.approx(103.0)
    assert tp == pytest.approx(91.0)


def test_sl_tp_rejects_invalid():
    with pytest.raises(ValueError):
        calculate_sl_tp(100, 0, "long", 1.5, 2)
    with pytest.raises(ValueError):
        calculate_sl_tp(10, 10, "long", 1.5, 2)  # stop below zero
    with pytest.raises(ValueError):
        calculate_sl_tp(100, 1, "sideways", 1.5, 2)


def test_check_exit():
    assert check_exit("long", 96, 97, 106) == "stop_loss"
    assert check_exit("long", 106.5, 97, 106) == "take_profit"
    assert check_exit("long", 100, 97, 106) is None
    assert check_exit("short", 103.5, 103, 91) == "stop_loss"
    assert check_exit("short", 90, 103, 91) == "take_profit"


# ------------------------------------------------------------ trailing
def test_trailing_stop_long_only_moves_up():
    stop = 97.0
    # not activated yet (needs 1R = 3 move)
    stop = update_trailing_stop("long", stop, 100, 97, extreme_price=102, atr=1, atr_multiplier=2, activation_r=1)
    assert stop == 97.0
    stop = update_trailing_stop("long", stop, 100, 97, extreme_price=110, atr=1, atr_multiplier=2, activation_r=1)
    assert stop == pytest.approx(108.0)
    # bigger ATR would put the candidate lower -> must not loosen
    stop2 = update_trailing_stop("long", stop, 100, 97, extreme_price=110, atr=5, atr_multiplier=2, activation_r=1)
    assert stop2 == pytest.approx(108.0)


def test_trailing_stop_short_only_moves_down():
    stop = update_trailing_stop("short", 103, 100, 103, extreme_price=90, atr=1, atr_multiplier=2, activation_r=1)
    assert stop == pytest.approx(92.0)
    assert update_trailing_stop("short", stop, 100, 103, 90, 10, 2, 1) == pytest.approx(92.0)


def test_trailing_never_below_initial_stop_when_price_falls():
    assert update_trailing_stop("long", 97, 100, 97, extreme_price=100, atr=1, atr_multiplier=2,
                                activation_r=0) == 98  # 100 - 2 > 97, tightens
    assert update_trailing_stop("long", 97, 100, 97, extreme_price=100, atr=3, atr_multiplier=2,
                                activation_r=0) == 97  # candidate 94 < 97 -> keep


# ------------------------------------------------------------ daily loss
def test_daily_loss_limit():
    assert daily_loss_pct(10_000, 9_500) == pytest.approx(5.0)
    assert daily_loss_pct(10_000, 10_500) == 0.0
    assert is_daily_loss_limit_hit(10_000, 9_500, 5.0)
    assert not is_daily_loss_limit_hit(10_000, 9_501, 5.0)
    assert not is_daily_loss_limit_hit(10_000, 5_000, 0)  # 0 disables


# ------------------------------------------------------------ RiskManager
def _rm(**overrides):
    settings = {**default_settings_values(), **overrides}
    return RiskManager(lambda: settings)


def test_plan_trade_ok():
    plan = _rm().plan_trade("BTC/USDT", "long", 100.0, 2.0, equity=10_000, open_positions=[])
    assert plan.allowed
    # defaults: stop 3 ATR, take-profit 10R
    assert plan.stop_loss == pytest.approx(94.0)
    assert plan.take_profit == pytest.approx(160.0)
    # 1% of 10k = 100 risk / 6 distance = 16.67 units = 1667 notional, under the 25% cap
    assert plan.notional == pytest.approx(10_000 / 6)
    assert plan.risk_amount == pytest.approx(100.0)


def test_plan_trade_caps_notional_at_symbol_exposure():
    plan = _rm(atr_sl_multiplier=1.5, risk_reward_ratio=2.0).plan_trade("BTC/USDT", "long", 100.0, 2.0,
                                                                          equity=10_000, open_positions=[])
    assert plan.stop_loss == pytest.approx(97.0)
    assert plan.take_profit == pytest.approx(106.0)
    # 1% of 10k = 100 risk / 3 distance = 33.33 units = 3333 notional > 25% cap (2500) -> capped
    assert plan.notional == pytest.approx(2_500.0)
    assert plan.risk_amount <= 100.0 + 1e-9


def test_plan_trade_blocks_on_max_positions():
    positions = [{"symbol": s, "quantity": 1, "entry_price": 1} for s in ("A", "B", "C")]
    plan = _rm().plan_trade("D", "long", 100, 2, 10_000, positions)
    assert not plan.allowed and "max open positions" in plan.reason


def test_plan_trade_blocks_on_daily_loss():
    plan = _rm().plan_trade("A", "long", 100, 2, equity=9_400, open_positions=[], day_start_equity=10_000)
    assert not plan.allowed and "daily loss" in plan.reason


def test_plan_trade_respects_symbol_exposure():
    positions = [{"symbol": "A", "quantity": 25, "entry_price": 100}]  # 2500 already = 25% cap
    plan = _rm(max_open_positions=5).plan_trade("A", "long", 100, 2, 10_000, positions)
    assert not plan.allowed and "exposure" in plan.reason
    plan_other = _rm(max_open_positions=5).plan_trade("B", "long", 100, 2, 10_000, positions)
    assert plan_other.allowed


def test_plan_trade_limited_by_available_cash():
    plan = _rm().plan_trade("A", "long", 100, 2, 10_000, [], available_cash=500)
    assert plan.allowed and plan.notional == pytest.approx(500)


def test_settings_are_read_live():
    settings = default_settings_values()
    rm = RiskManager(lambda: settings)
    assert rm.plan_trade("A", "long", 100, 2, 10_000, []).stop_loss == pytest.approx(94)
    settings["atr_sl_multiplier"] = 2.0
    assert rm.plan_trade("A", "long", 100, 2, 10_000, []).stop_loss == pytest.approx(96)
