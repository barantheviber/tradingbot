"""The mobile and desktop apps share one TypeScript file describing the API.
These tests fail when the two copies drift apart, or when the API returns
fields the file does not declare (or stops returning ones it does)."""

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.demo import DEMO_TOKEN, build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MOBILE_TYPES = ROOT / "mobile" / "src" / "api" / "types.ts"
DESKTOP_TYPES = ROOT / "desktop" / "shared" / "apiTypes.ts"
AUTH = {"Authorization": f"Bearer {DEMO_TOKEN}"}


def interface_fields(name: str) -> set:
    src = MOBILE_TYPES.read_text(encoding="utf-8")
    m = re.search(r"export interface %s \{(.*?)\n\}" % name, src, re.S)
    assert m, f"interface {name} not found"
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", m.group(1), flags=re.S)
    return set(re.findall(r"^\s*(\w+)\??:", body, re.M))


def test_mobile_and_desktop_share_the_same_types_file():
    assert MOBILE_TYPES.read_bytes() == DESKTOP_TYPES.read_bytes(), (
        "mobile/src/api/types.ts and desktop/shared/apiTypes.ts must be identical; copy one over the other")


@pytest.fixture(scope="module")
def client():
    _, _, app = build()
    return TestClient(app)


@pytest.mark.parametrize("interface,path,pick", [
    ("Status", "/api/status", lambda b: b),
    ("Position", "/api/positions", lambda b: b["positions"][0]),
    ("Trade", "/api/trades", lambda b: b["trades"][0]),
    ("Pnl", "/api/pnl", lambda b: b),
    ("Candle", "/api/candles", lambda b: b["candles"][0]),
    ("Setting", "/api/settings", lambda b: b["settings"][0]),
    ("LogEvent", "/api/logs", lambda b: b["logs"][0]),
])
def test_api_fields_match_the_types_file(client, interface, path, pick):
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 200
    assert set(pick(resp.json())) == interface_fields(interface)


def test_close_and_command_fields_match(client):
    pid = client.get("/api/positions", headers=AUTH).json()["positions"][0]["id"]
    close = client.post(f"/api/positions/{pid}/close", headers=AUTH).json()
    assert set(close) == interface_fields("CloseResult")
    cmd = client.get(f"/api/commands/{close['command_id']}", headers=AUTH).json()
    assert set(cmd) == interface_fields("Command")
