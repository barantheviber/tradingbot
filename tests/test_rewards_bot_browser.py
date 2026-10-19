"""Rewards bot end to end in a real headless browser, against a local fake of
rewards.bing.com and bing.com (no Microsoft account or network needed).

Skipped when Playwright or a Chromium build is not available (e.g. in CI).
"""

import json
import os
import random
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright.sync_api")

from rewards_bot import activities, browser, runner, searches  # noqa: E402
from rewards_bot.config import settings_from_mapping  # noqa: E402
from rewards_bot.util import Pacer  # noqa: E402

TODAY = date.today()
CHROMIUM = os.environ.get("REWARDS_TEST_CHROMIUM", "/opt/pw-browsers/chromium")

DASHBOARD_HTML = """<!doctype html><html><body>
<a data-bi-id="DS_click" href="/dest/1" target="_blank"
   onclick="fetch('/api/report?offer=DS_click')">Click card</a>
<div style="cursor:pointer" onclick="fetch('/api/report?offer=MP_title'); window.open('/dest/2')">
  <span>Find me by title</span></div>
<a data-bi-id="DS_poll" href="/poll" target="_blank">Poll card</a>
</body></html>"""

POLL_HTML = """<!doctype html><html><body>
<div id="btoption0" onclick="fetch('/api/report?offer=DS_poll')">Yes</div>
<div id="btoption1" onclick="fetch('/api/report?offer=DS_poll')">No</div>
</body></html>"""

SEARCH_HTML = """<!doctype html><html><body>
<form action="/search"><input id="sb_form_q" name="q"></form><p>results</p>
<div style="height:3000px"></div></body></html>"""


class FakeMicrosoft:
    def __init__(self):
        self.pc = 0
        self.mobile = 0
        self.points = 1000
        self.done = set()
        self.queries = []
        self.user_agents = []
        self.lock = threading.Lock()

    def payload(self):
        def promo(offer_id, title, kind, url):
            return {"offerId": offer_id, "title": title, "promotionType": kind,
                    "destinationUrl": url, "complete": offer_id in self.done,
                    "pointProgress": 10 if offer_id in self.done else 0, "pointProgressMax": 10}
        return {"dashboard": {
            "userStatus": {"availablePoints": self.points, "counters": {
                "pcSearch": [{"pointProgress": self.pc, "pointProgressMax": 15}],
                "mobileSearch": [{"pointProgress": self.mobile, "pointProgressMax": 9}]}},
            "dailySetPromotions": {TODAY.strftime("%m/%d/%Y"): [
                promo("DS_click", "Click card", "urlreward", "https://example.invalid/1"),
                promo("DS_poll", "Poll card", "quiz", "https://example.invalid/poll"),
            ]},
            "morePromotions": [
                promo("MP_title", "Find me by title", "urlreward", "https://example.invalid/2"),
            ]}}


def make_handler(fake: FakeMicrosoft):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, ctype="text/html", status=200, headers=()):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            signed_in = "_U=" in (self.headers.get("Cookie") or "")
            with fake.lock:
                if url.path == "/rewards/":
                    return self.send(DASHBOARD_HTML)
                if url.path == "/rewards/earn":
                    return self.send("<html><body>new dashboard, no cards</body></html>")
                if url.path == "/api/getuserinfo":
                    return self.send(json.dumps(fake.payload()), "application/json")
                if url.path == "/api/report":
                    offer = query.get("offer", [""])[0]
                    if offer not in fake.done:
                        fake.done.add(offer)
                        fake.points += 10
                    return self.send("{}", "application/json")
                if url.path == "/signin":
                    return self.send("", status=302, headers=[
                        ("Set-Cookie", "_U=token; Path=/"), ("Location", "/bing/")])
                if url.path in ("/bing/", "/search"):
                    q = query.get("q", [""])[0]
                    if url.path == "/search" and q and signed_in:
                        ua = self.headers.get("User-Agent", "")
                        fake.queries.append(q)
                        fake.user_agents.append(ua)
                        if "Mobile" in ua:
                            fake.mobile = min(9, fake.mobile + 3)
                        else:
                            fake.pc = min(15, fake.pc + 3)
                        fake.points += 3
                    return self.send(SEARCH_HTML)
                if url.path == "/poll":
                    return self.send(POLL_HTML)
                return self.send("<html><body>destination</body></html>")

    return Handler


@pytest.fixture
def fake_site(monkeypatch):
    fake = FakeMicrosoft()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fake))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    pages = (f"{base}/rewards/earn", f"{base}/rewards/")
    for module, name, value in [
        (browser, "REWARDS_HOME", f"{base}/rewards/"),
        (browser, "USERINFO_API", f"{base}/api/getuserinfo"),
        (browser, "BING_HOME", f"{base}/bing/"),
        (browser, "BING_SIGNIN", f"{base}/signin"),
        (browser, "REWARDS_ACTIVITY_PAGES", pages),
        (activities, "REWARDS_ACTIVITY_PAGES", pages),
        (searches, "BING_HOME", f"{base}/bing/"),
        (searches, "BING_SEARCH", f"{base}/search?q={{query}}"),
        (runner, "collect_queries", lambda *a, **k: [f"sorgu {i}" for i in range(50)]),
    ]:
        monkeypatch.setattr(module, name, value)
    yield fake
    server.shutdown()


def test_full_run_against_fake_site(fake_site, tmp_path):
    if not os.path.exists(CHROMIUM):
        pytest.skip("Chromium not available")
    settings = settings_from_mapping({
        "browser": "chromium", "executable_path": CHROMIUM, "data_dir": str(tmp_path / "data"),
        "log_dir": str(tmp_path / "logs"), "search_delay_seconds": [0, 0], "cooldown_minutes": 0,
        "max_searches_per_run": 10})
    try:
        summary = runner.run_once(settings, pacer=Pacer(random.Random(0), sleep=lambda s: None),
                                  today=TODAY)
    except browser.BrowserStartError as exc:
        pytest.skip(f"browser cannot start here: {exc}")

    assert fake_site.done == {"DS_click", "DS_poll", "MP_title"}
    assert summary.activities.completed == ["Click card", "Poll card", "Find me by title"]
    assert fake_site.pc == 15 and fake_site.mobile == 9
    by_platform = {r.platform: r for r in summary.searches}
    assert by_platform["desktop"].complete and by_platform["desktop"].searches == 5
    assert by_platform["mobile"].complete and by_platform["mobile"].searches == 3
    assert len(set(fake_site.queries)) == len(fake_site.queries) == 8
    assert not any("Headless" in ua for ua in fake_site.user_agents)
    assert sum("Mobile" in ua for ua in fake_site.user_agents) == 3
    assert summary.end_points == 1000 + 30 + 8 * 3


def test_expired_session_is_reported(fake_site, monkeypatch, tmp_path):
    if not os.path.exists(CHROMIUM):
        pytest.skip("Chromium not available")
    monkeypatch.setattr(browser, "LOGIN_HOSTS", ("127.0.0.1",))
    settings = settings_from_mapping({
        "browser": "chromium", "executable_path": CHROMIUM, "data_dir": str(tmp_path / "data")})
    with pytest.raises(browser.SessionExpired):
        runner.run_once(settings, pacer=Pacer(sleep=lambda s: None), today=TODAY)
