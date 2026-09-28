from config import legacy_env_warnings


def test_legacy_env_vars_are_reported(monkeypatch):
    for name in ("SYMBOL", "EXCHANGE_API_KEY", "RSI_LOWER"):
        monkeypatch.delenv(name, raising=False)
    assert legacy_env_warnings() == []
    monkeypatch.setenv("SYMBOL", "ETH/USDT")
    monkeypatch.setenv("EXCHANGE_API_KEY", "x")
    monkeypatch.setenv("RSI_LOWER", "40")
    warnings = legacy_env_warnings()
    assert len(warnings) == 3
    assert any("SYMBOL" in w and "SYMBOLS" in w for w in warnings)


import pytest

from config import Config, ConfigError, load_config


def test_bad_numeric_env_value_gives_clear_error(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL_SEC", "30s")
    with pytest.raises(ConfigError, match="POLL_INTERVAL_SEC"):
        load_config(env_file=None)


def test_default_config_is_valid():
    assert Config().validate() == []


@pytest.mark.parametrize("field,value,needle", [
    ("timeframe", "1hour", "TIMEFRAME"),
    ("paper_starting_balance", 0.0, "PAPER_STARTING_BALANCE"),
    ("paper_fee_rate", 0.5, "PAPER_FEE_RATE"),
    ("max_retries", -1, "MAX_RETRIES"),
    ("retry_max_delay", 0.5, "RETRY_MAX_DELAY"),
    ("symbols", ["BTCUSDT"], "SYMBOLS"),
])
def test_invalid_values_are_reported(field, value, needle):
    cfg = Config(**{field: value})
    assert any(needle in p for p in cfg.validate())


@pytest.mark.parametrize("value", ["ture", "paper", "flase", "2"])
def test_unrecognised_paper_trading_value_never_selects_live(monkeypatch, value):
    monkeypatch.setenv("PAPER_TRADING", value)
    with pytest.raises(ConfigError, match="PAPER_TRADING"):
        load_config(env_file=None)


@pytest.mark.parametrize("value,expected", [("false", False), ("0", False), ("TRUE", True), ("", True)])
def test_paper_trading_recognised_values(monkeypatch, value, expected):
    monkeypatch.setenv("PAPER_TRADING", value)
    assert load_config(env_file=None).paper_trading is expected
