import socket
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
import httpx  # noqa: E402

import main  # noqa: E402
from local_runtime import LocalRuntime, RuntimeStartError  # noqa: E402

TOKEN = "runtime-token-0123456789"


class FakeEngine:
    def __init__(self, fail: bool = False):
        self._stop = threading.Event()
        self.fail = fail

    @property
    def stopping(self):
        return self._stop.is_set()

    def request_stop(self, reason=""):
        self._stop.set()

    def run(self):
        if self.fail:
            raise RuntimeError("boom")
        self._stop.wait(30)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def runtime_env(tmp_path, monkeypatch):
    port = _free_port()
    for key, value in {"API_TOKEN": TOKEN, "API_PORT": str(port), "API_HOST": "0.0.0.0",
                       "DB_PATH": str(tmp_path / "bot.db"), "LOG_DIR": str(tmp_path / "logs"),
                       "PAPER_TRADING": "true", "SYMBOLS": "BTC/USDT"}.items():
        monkeypatch.setenv(key, value)
    return tmp_path, port


def _wait_for(url, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return httpx.get(url, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=1)
        except httpx.TransportError:
            time.sleep(0.1)
    raise AssertionError("API did not start")


def test_runtime_serves_api_on_loopback_and_stops(runtime_env, monkeypatch):
    tmp_path, port = runtime_env
    engine = FakeEngine()
    monkeypatch.setattr(main, "build_engine", lambda config, state: engine)
    runtime = LocalRuntime(str(tmp_path / "missing.env"))
    runtime.start()
    try:
        resp = _wait_for(f"http://127.0.0.1:{port}/api/status")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"
        assert runtime.server_host == "127.0.0.1"  # API_HOST=0.0.0.0 is ignored
    finally:
        runtime.stop(timeout=15)
    assert not runtime.running
    assert engine.stopping
    assert runtime.status()["error"] is None


def test_engine_failure_stops_api_and_reports(runtime_env, monkeypatch):
    tmp_path, port = runtime_env
    monkeypatch.setattr(main, "build_engine", lambda config, state: FakeEngine(fail=True))
    runtime = LocalRuntime(str(tmp_path / "missing.env"))
    runtime.start()
    deadline = time.monotonic() + 15
    while runtime.running and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not runtime.running
    assert "boom" in runtime.status()["error"]


def test_short_token_is_rejected(runtime_env, monkeypatch):
    tmp_path, _ = runtime_env
    monkeypatch.setenv("API_TOKEN", "short")
    with pytest.raises(RuntimeStartError):
        LocalRuntime(str(tmp_path / "missing.env")).start()


def test_unparsable_value_is_a_start_error(runtime_env, monkeypatch):
    tmp_path, _ = runtime_env
    monkeypatch.setenv("POLL_INTERVAL_SEC", "often")
    with pytest.raises(RuntimeStartError, match="POLL_INTERVAL_SEC"):
        LocalRuntime(str(tmp_path / "missing.env")).start()
