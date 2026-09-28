"""The status API explains the automatic brake so the apps can show why entries stopped."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.server import create_app  # noqa: E402
from backtest import generate_synthetic_ohlcv  # noqa: E402
from config import Config  # noqa: E402
from tests.test_safety_halt import _engine, _lose, _state  # noqa: E402

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _halt(client):
    return client.get("/api/status", headers=AUTH).json()["safety_halt"]


@pytest.fixture
def state(tmp_path):
    return _state(tmp_path / "t.db")


@pytest.fixture
def client(state):
    return TestClient(create_app(Config(symbols=["BTC/USDT"], api_token=TOKEN), state))


def test_off_by_default(client):
    halt = _halt(client)
    assert halt["active"] is False and halt["kind"] is None
    assert halt["drawdown_limit_pct"] == 15.0 and halt["losing_streak_limit"] == 15


def test_losing_streak_trip_from_the_real_engine(state, client):
    state.set_setting("max_losing_streak_halt", 3)
    engine = _engine(state, generate_synthetic_ohlcv(300))
    _lose(engine, 0.01, n=3)
    engine.tick()
    halt = _halt(client)
    assert halt["active"] is True and halt["kind"] == "losing_streak"
    assert halt["losing_streak_at_halt"] == 3 and halt["losing_streak_limit"] == 3
    assert halt["since"] is not None


def test_drawdown_kind_and_numbers(state, client):
    state.set_setting("safety_halt_active", True)
    state.set_state("safety_halt:paper", {"reason": "drawdown 16.00% from peak 10000.00 >= 15%", "at": 1.0,
                                          "drawdown_pct": 16.0, "losing_streak": 1})
    halt = _halt(client)
    assert halt["kind"] == "drawdown" and halt["drawdown_pct"] == 16.0


def test_set_by_hand_is_manual(state, client):
    state.set_setting("safety_halt_active", True)
    halt = _halt(client)
    assert halt["active"] is True and halt["kind"] == "manual"


def test_brake_limits_are_bounded(client):
    put = lambda key, value: client.put(f"/api/settings/{key}", headers=AUTH, json={"value": value}).status_code  # noqa: E731
    assert put("max_drawdown_halt_pct", 101) == 422
    assert put("max_drawdown_halt_pct", -1) == 422
    assert put("max_drawdown_halt_pct", 0) == 200
    assert put("max_losing_streak_halt", 101) == 422
    assert put("max_losing_streak_halt", 2.5) == 422
    assert put("max_losing_streak_halt", 20) == 200
    assert put("safety_halt_active", False) == 200
