from config import DEFAULT_SETTINGS
from dashboard.logic import apply_setting_changes, dashboard_is_local_only
from state_manager import StateManager


def test_only_loopback_addresses_count_as_local():
    assert dashboard_is_local_only("127.0.0.1") and dashboard_is_local_only("localhost")
    for address in (None, "", "0.0.0.0", "192.168.1.5", "::"):
        assert not dashboard_is_local_only(address)


def test_settings_form_uses_api_validation(tmp_path):
    state = StateManager(str(tmp_path / "t.db"))
    state.seed_default_settings(DEFAULT_SETTINGS)
    current = state.get_all_settings()
    changed, errors = apply_setting_changes(state, current, {
        **current,
        "risk_per_trade_pct": 250.0,            # out of range
        "macd_fast": current["macd_slow"] + 5,  # cross-field violation
        "rsi_period": 21,                       # valid
    })
    assert changed == ["rsi_period"]
    assert len(errors) == 2
    assert state.get_setting("risk_per_trade_pct") == current["risk_per_trade_pct"]
    assert state.get_setting("rsi_period") == 21
