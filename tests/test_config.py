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
