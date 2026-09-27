import time

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from api.server import create_app  # noqa: E402
from config import DEFAULT_SETTINGS, Config  # noqa: E402
from state_manager import StateManager  # noqa: E402

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeCandles:
    calls = 0

    def fetch_ohlcv(self, symbol, timeframe, limit):
        FakeCandles.calls += 1
        return pd.DataFrame({"timestamp": [1_000, 2_000], "open": [1.0, 2.0], "high": [2.0, 3.0],
                             "low": [0.5, 1.5], "close": [1.5, 2.5], "volume": [10.0, 20.0]})


@pytest.fixture
def env():
    config = Config(symbols=["BTC/USDT", "ETH/USDT"], api_token=TOKEN, api_key="SECRET-KEY-XYZ",
                    api_secret="SECRET-SECRET-XYZ")
    state = StateManager(":memory:")
    state.seed_default_settings(DEFAULT_SETTINGS)
    client = TestClient(create_app(config, state, candle_factory=FakeCandles))
    return config, state, client


def _open(state, **kw):
    fields = dict(symbol="BTC/USDT", side="long", quantity=0.5, entry_price=100.0, stop_loss=95.0,
                  take_profit=110.0, mode="paper", fees=0.05)
    fields.update(kw)
    return state.open_position(**fields)


def test_requires_token(env):
    _, _, client = env
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/status", headers=AUTH).status_code == 200


def test_create_app_refuses_empty_token():
    with pytest.raises(ValueError):
        create_app(Config(api_token=""), StateManager(":memory:"))


def test_status_reports_daily_limit_and_hides_keys(env):
    config, state, client = env
    state.set_state("bot_status", {"status": "running", "mode": "paper"})
    state.set_state("heartbeat", {"ts": time.time(), "equity": 9_400.0, "prices": {}})
    state.get_or_create_day_start_equity("paper", 10_000.0)
    resp = client.get("/api/status", headers=AUTH)
    body = resp.json()
    assert body["mode"] == "paper" and body["bot_running"] is True
    assert body["today_pnl"] == pytest.approx(-600.0)
    assert body["entries_halted_by_daily_limit"] is True  # 6% >= 5%
    assert "SECRET" not in resp.text and TOKEN not in resp.text


def test_stale_heartbeat_means_not_running(env):
    _, state, client = env
    state.set_state("bot_status", {"status": "running"})
    state.set_state("heartbeat", {"ts": time.time() - 3600, "equity": 1.0, "prices": {}})
    assert client.get("/api/status", headers=AUTH).json()["bot_running"] is False


def test_positions_and_close_queues_command(env):
    _, state, client = env
    pid = _open(state)
    state.update_position(pid, stop_loss=101.0)  # trailed
    state.set_state("heartbeat", {"ts": time.time(), "equity": 1.0, "prices": {"BTC/USDT": 104.0}})
    pos = client.get("/api/positions", headers=AUTH).json()["positions"][0]
    assert pos["unrealized_pnl"] == pytest.approx(0.5 * 4 - 0.05)
    assert pos["trailing_active"] is True and pos["trailing_stop"] == 101.0
    assert pos["close_pending"] is False

    resp = client.post(f"/api/positions/{pid}/close", headers=AUTH)
    assert resp.status_code == 202
    cmd_id = resp.json()["command_id"]
    again = client.post(f"/api/positions/{pid}/close", headers=AUTH).json()
    assert again["already_queued"] is True and again["command_id"] == cmd_id
    pending = state.get_pending_commands()
    assert len(pending) == 1 and pending[0]["command"] == "close_position"
    assert pending[0]["payload"]["position_id"] == pid
    assert state.get_position(pid)["status"] == "open"  # the API never closes it itself
    assert client.get("/api/positions", headers=AUTH).json()["positions"][0]["close_pending"] is True
    assert client.get(f"/api/commands/{cmd_id}", headers=AUTH).json()["status"] == "pending"


def test_close_unknown_or_other_mode_is_404(env):
    _, state, client = env
    live_pid = _open(state, mode="live")
    assert client.post("/api/positions/999/close", headers=AUTH).status_code == 404
    assert client.post(f"/api/positions/{live_pid}/close", headers=AUTH).status_code == 404
    assert state.get_pending_commands() == []


def test_trades_and_pnl(env):
    _, state, client = env
    for pnl in (10.0, -4.0):
        pid = _open(state)
        state.mark_position_closed(pid, exit_price=100.0, pnl=pnl, fees=0.1, reason="take_profit")
    trades = client.get("/api/trades?limit=1", headers=AUTH).json()["trades"]
    assert len(trades) == 1
    pnl = client.get("/api/pnl", headers=AUTH).json()
    assert pnl["trades"] == 2 and pnl["total_pnl"] == pytest.approx(6.0)
    assert pnl["profit_factor"] == pytest.approx(2.5)


def test_pnl_infinite_profit_factor_is_json_safe(env):
    _, state, client = env
    pid = _open(state)
    state.mark_position_closed(pid, exit_price=110.0, pnl=5.0, fees=0.1, reason="take_profit")
    body = client.get("/api/pnl", headers=AUTH).json()
    assert body["profit_factor"] is None and body["profit_factor_infinite"] is True


def test_settings_validation(env):
    _, state, client = env
    settings = client.get("/api/settings", headers=AUTH).json()["settings"]
    assert {s["key"] for s in settings} == set(DEFAULT_SETTINGS)
    ok = client.put("/api/settings/risk_per_trade_pct", headers=AUTH, json={"value": "0.5"})
    assert ok.status_code == 200 and ok.json()["value"] == 0.5
    assert state.get_setting("risk_per_trade_pct") == 0.5
    assert client.put("/api/settings/risk_per_trade_pct", headers=AUTH, json={"value": -1}).status_code == 422
    assert client.put("/api/settings/rsi_period", headers=AUTH, json={"value": 1.5}).status_code == 422
    assert client.put("/api/settings/macd_fast", headers=AUTH, json={"value": 40}).status_code == 422
    assert client.put("/api/settings/trading_enabled", headers=AUTH, json={"value": 1}).status_code == 422
    assert client.put("/api/settings/trading_enabled", headers=AUTH, json={"value": False}).status_code == 200
    assert client.put("/api/settings/paper_trading", headers=AUTH, json={"value": False}).status_code == 404
    assert client.put("/api/settings/api_key", headers=AUTH, json={"value": "x"}).status_code == 404
    assert client.put("/api/settings/rsi_period", headers=AUTH, json={}).status_code == 422
    assert state.get_setting("macd_fast") == 12


def test_logs_after_id(env):
    _, state, client = env
    state.log_event("INFO", "signal", "one")
    state.log_event("INFO", "trade", "two")
    logs = client.get("/api/logs?limit=10", headers=AUTH).json()["logs"]
    assert [e["message"] for e in logs][:2] == ["two", "one"]
    newer = client.get(f"/api/logs?after_id={logs[-1]['id']}", headers=AUTH).json()["logs"]
    assert all(e["id"] > logs[-1]["id"] for e in newer)
    only_trade = client.get("/api/logs?category=trade", headers=AUTH).json()["logs"]
    assert [e["message"] for e in only_trade] == ["two"]


def test_candles_only_for_configured_symbols(env):
    _, _, client = env
    body = client.get("/api/candles?symbol=BTC/USDT&limit=50", headers=AUTH).json()
    assert body["candles"][0] == {"t": 1000, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10.0}
    assert client.get("/api/candles?symbol=DOGE/USDT", headers=AUTH).status_code == 400
    assert client.get("/api/candles?timeframe=bad", headers=AUTH).status_code == 400


def test_no_route_can_open_orders_or_switch_mode(env):
    _, _, client = env
    paths = {r.path for r in client.app.routes}
    assert not any("order" in p or "mode" in p or "live" in p for p in paths)


def test_websocket_auth_and_updates(env):
    _, state, client = env
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws?token=wrong") as ws:
            ws.receive_json()
    _open(state)
    with client.websocket_connect(f"/api/ws?token={TOKEN}") as ws:
        first = ws.receive_json()
        assert first["type"] == "status" and first["data"]["open_positions"] == 1
        assert ws.receive_json()["type"] == "positions"
        state.log_event("INFO", "trade", "new event")
        msg = ws.receive_json()
        assert msg["type"] == "logs" and msg["data"][0]["message"] == "new event"
