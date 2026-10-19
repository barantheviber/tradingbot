"""Rewards bot: pure logic (no browser, no network)."""

import json
import random
from datetime import date
from pathlib import Path

import pytest

from rewards_bot.activities import ActivityReport, choose_answers, run_activities
from rewards_bot.browser import desired_user_agent, is_login_url
from rewards_bot.config import ConfigError, Settings, load_settings, settings_from_mapping
from rewards_bot.dashboard import (DashboardError, DashboardState, Progress, parse_dashboard,
                                   pending_activities)
from rewards_bot.queries import (QueryPool, collect_queries, parse_bing_related,
                                 parse_trends_rss, parse_wikipedia_top)
from rewards_bot.runner import RunSummary
from rewards_bot.scheduler import crontab_line, task_xml, windowless_python
from rewards_bot.searches import SearchReport, run_searches
from rewards_bot.util import AlreadyRunning, Pacer, RunLock, done_today, read_state, write_state

TODAY = date(2026, 10, 14)


def promo(offer_id, **kw):
    base = {"offerId": offer_id, "title": f"Title {offer_id}", "promotionType": "urlreward",
            "destinationUrl": f"https://www.bing.com/search?q={offer_id}", "complete": False,
            "pointProgress": 0, "pointProgressMax": 10}
    base.update(kw)
    return base


def payload(pc=(0, 90), mobile=(0, 60), daily=None, more=None, points=1000, day="10/14/2026"):
    counters = {}
    if pc is not None:
        counters["pcSearch"] = [{"pointProgress": pc[0], "pointProgressMax": pc[1]}]
    if mobile is not None:
        counters["mobileSearch"] = [{"pointProgress": mobile[0], "pointProgressMax": mobile[1]}]
    return {"dashboard": {
        "userStatus": {"availablePoints": points, "counters": counters},
        "dailySetPromotions": {day: daily or []},
        "morePromotions": more or [],
    }}


# -- config --------------------------------------------------------------------------

def test_defaults_are_valid(tmp_path):
    settings = load_settings(tmp_path / "missing.json")
    assert settings.browser == "msedge" and settings.headless
    assert settings.locale == "tr-TR"


def test_config_file_overrides_and_coerces(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"search_delay_seconds": [1, 2], "max_searches_per_run": 10,
                                "browser": "chrome", "data_dir": str(tmp_path / "d")}))
    settings = load_settings(path)
    assert settings.search_delay_seconds == (1.0, 2.0)
    assert settings.max_searches_per_run == 10
    assert settings.browser == "chrome"
    assert settings.profile_dir == tmp_path / "d" / "profile"


@pytest.mark.parametrize("data", [
    {"unknown_key": 1},
    {"browser": "firefox"},
    {"headless": "yes"},
    {"search_delay_seconds": [5, 1]},
    {"schedule_time": "25:00"},
    {"max_searches_per_run": 0},
    {"cooldown_minutes": -1},
])
def test_invalid_config_is_rejected(data):
    with pytest.raises(ConfigError):
        settings_from_mapping(data)


def test_example_config_is_valid():
    example = Path(__file__).resolve().parent.parent / "rewards_bot" / "config.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    settings_from_mapping(data)


# -- dashboard -----------------------------------------------------------------------

def test_parse_dashboard_counters_and_promotions():
    data = payload(pc=(30, 90), mobile=(0, 60), daily=[promo("A"), promo("B", complete=True)],
                   more=[promo("C", pointProgressMax=0), promo("D")])
    data["dashboard"]["userStatus"]["counters"]["pcSearch"].append(
        {"pointProgress": 0, "pointProgressMax": 12})  # Edge bonus row
    state = parse_dashboard(data, TODAY)
    assert state.available_points == 1000
    assert state.pc_search == Progress(30, 102)
    assert state.pc_search.remaining == 72
    assert state.mobile_search == Progress(0, 60)
    assert [p.offer_id for p in pending_activities(state)] == ["A", "D"]
    assert [p.offer_id for p in pending_activities(state, daily_set=False)] == ["D"]


def test_daily_set_only_for_today():
    state = parse_dashboard(payload(daily=[promo("old")], day="10/13/2026"), TODAY)
    assert state.daily_set == ()


def test_locked_hidden_and_unknown_types():
    data = payload(more=[
        promo("L", exclusiveLockedFeatureStatus="locked"),
        promo("U", attributes={"is_unlocked": "False"}),
        promo("H", attributes={"hidden": "True"}),
        promo("Q", promotionType="quiz"),
        promo("W", promotionType="welcometour"),
    ])
    state = parse_dashboard(data, TODAY)
    pending = pending_activities(state)
    assert [p.offer_id for p in pending] == ["Q", "W"]
    assert [p.supported for p in pending] == [True, False]


def test_missing_mobile_counter_and_bad_payload():
    state = parse_dashboard(payload(mobile=None), TODAY)
    assert state.mobile_search is None
    with pytest.raises(DashboardError):
        parse_dashboard({"error": "unauthorized"}, TODAY)


# -- queries -------------------------------------------------------------------------

TRENDS = """<?xml version="1.0"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<title>Daily Search Trends</title>
<item><title>galatasaray</title><ht:approx_traffic>1000+</ht:approx_traffic>
  <ht:news_item><ht:news_item_title>Derbi sonucu</ht:news_item_title></ht:news_item></item>
<item><title>deprem</title></item>
</channel></rss>"""


def test_parse_sources():
    assert parse_trends_rss(TRENDS) == ["galatasaray", "deprem", "Derbi sonucu"]
    assert parse_bing_related('["gs", ["gs maçı", "gs kadro", ""]]') == ["gs maçı", "gs kadro"]
    wiki = {"items": [{"articles": [{"article": "Anasayfa"}, {"article": "Özel:Ara"},
                                    {"article": "Mustafa_Kemal_Atatürk"}]}]}
    assert parse_wikipedia_top(json.dumps(wiki)) == ["Mustafa Kemal Atatürk"]


def test_collect_queries_survives_network_failures():
    def offline(url):
        raise OSError("offline")

    queries = collect_queries("tr", "TR", 20, fetch=offline, today=TODAY, rng=random.Random(1))
    assert len(queries) >= 20
    assert len({q.casefold() for q in queries}) == len(queries)


def test_collect_queries_uses_trends_first():
    def fetch(url):
        if "trends.google" in url:
            return TRENDS
        if "osjson" in url:
            return '["x", ["ilgili 1", "ilgili 2"]]'
        raise OSError("no wiki")

    queries = collect_queries("tr", "TR", 10, fetch=fetch, today=TODAY, rng=random.Random(1))
    assert {"galatasaray", "deprem", "Derbi sonucu", "ilgili 1", "ilgili 2"} <= set(queries)


def test_query_pool_never_repeats():
    pool = QueryPool(["a", "A", "b"], "tr", random.Random(3))
    seen = [pool.next() for _ in range(200)]
    assert seen[:2] == ["a", "b"]
    assert len(set(seen)) == len(seen)


# -- quiz ----------------------------------------------------------------------------

def test_choose_answers():
    rng = random.Random(0)
    eight = [{"iscorrectoption": "True" if i in (1, 4, 6) else "False"} for i in range(8)]
    assert choose_answers({}, eight, rng) == [1, 4, 6]
    four = [{"data-option": f"opt{i}"} for i in range(4)]
    assert choose_answers({"correctAnswer": "opt2"}, four, rng) == [2]
    assert choose_answers({"correctAnswer": "hash"}, [{"data-option": "x"}, None], rng) == [0]
    assert choose_answers({}, [None, None], rng) == []


# -- user agent / urls ---------------------------------------------------------------

def test_desired_user_agent():
    headless = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "HeadlessChrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0")
    assert "HeadlessChrome" not in desired_user_agent(headless, mobile=False)
    assert "Chrome/141.0.0.0 Safari" in desired_user_agent(headless, mobile=False)
    mobile = desired_user_agent(headless, mobile=True)
    assert "Mobile" in mobile and "Chrome/141.0.0.0" in mobile and "EdgA/141" in mobile
    normal = headless.replace("HeadlessChrome", "Chrome")
    assert desired_user_agent(normal, mobile=False) == normal


def test_is_login_url():
    assert is_login_url("https://login.live.com/oauth20_authorize.srf?x=1")
    assert not is_login_url("https://rewards.bing.com/")


# -- searches (fake session) ---------------------------------------------------------

class FakeSession:
    """Counters move as the fake searches happen; ``credit`` decides how many count."""

    def __init__(self, pc=(0, 30), mobile=(0, 15), credit=None):
        self.pc = list(pc)
        self.mobile = list(mobile) if mobile else None
        self.credit = credit or (lambda n: True)
        self.searches = 0
        self.signed_in = 0

    def read_dashboard(self):
        return DashboardState(
            available_points=500,
            pc_search=Progress(*self.pc),
            mobile_search=Progress(*self.mobile) if self.mobile else None,
            daily_set=(), more_promotions=())

    def ensure_bing_signed_in(self):
        self.signed_in += 1
        return True

    def search(self, session, query, pacer):
        self.searches += 1
        if self.credit(self.searches):
            self.pc[0] = min(self.pc[1], self.pc[0] + 3)


def fast_settings(**kw):
    base = dict(search_delay_seconds=(0, 0), cooldown_minutes=0, max_stalls=2,
                max_searches_per_run=40)
    base.update(kw)
    return settings_from_mapping(base)


def test_searches_fill_the_counter():
    session = FakeSession(pc=(0, 30))
    pool = QueryPool(["q"], "tr", random.Random(0))
    report = run_searches(session, fast_settings(), pool, "desktop", Pacer(sleep=lambda s: None),
                          search_fn=session.search)
    assert report.complete and report.searches == 10 and report.gained == 30
    assert session.signed_in == 1


def test_searches_slow_down_when_bing_paces():
    # Only every third search counts: the bot should switch to small batches.
    waits = []
    session = FakeSession(pc=(0, 18), credit=lambda n: n % 3 == 0)
    pacer = Pacer(sleep=lambda s: waits.append(s))
    report = run_searches(session, fast_settings(cooldown_minutes=15, max_searches_per_run=40),
                          QueryPool([], "tr"), "desktop", pacer, search_fn=session.search)
    assert report.complete
    assert 15 * 60 in waits


def test_searches_stop_when_nothing_is_credited():
    session = FakeSession(pc=(0, 30), credit=lambda n: False)
    report = run_searches(session, fast_settings(max_stalls=2), QueryPool([], "tr"), "desktop",
                          Pacer(sleep=lambda s: None), search_fn=session.search)
    assert not report.complete
    assert "artmıyor" in report.note
    assert report.searches == 10 + 3  # one full batch, then one slow batch


def test_searches_respect_cap_and_done_counters():
    session = FakeSession(pc=(0, 300))
    report = run_searches(session, fast_settings(max_searches_per_run=7), QueryPool([], "tr"),
                          "desktop", Pacer(sleep=lambda s: None), search_fn=session.search)
    assert report.searches == 7 and "sınır" in report.note

    done = FakeSession(pc=(30, 30))
    report = run_searches(done, fast_settings(), QueryPool([], "tr"), "desktop",
                          Pacer(sleep=lambda s: None), search_fn=done.search)
    assert report.searches == 0 and done.signed_in == 0

    no_mobile = FakeSession(mobile=None)
    report = run_searches(no_mobile, fast_settings(), QueryPool([], "tr"), "mobile",
                          Pacer(sleep=lambda s: None), search_fn=no_mobile.search)
    assert report.searches == 0 and "yok" in report.note


def test_searches_blind_when_counter_unreadable():
    class Unreadable(FakeSession):
        def read_dashboard(self):
            return None

    session = Unreadable()
    report = run_searches(session, fast_settings(fallback_desktop_searches=4), QueryPool([], "tr"),
                          "desktop", Pacer(sleep=lambda s: None), search_fn=session.search)
    assert report.searches == 4 and report.note == "sayaç okunamadı"


# -- activities (fake session) -------------------------------------------------------

class ActivitySession:
    def __init__(self, promos):
        self.promos = promos
        self.points = 100

    def read_dashboard(self):
        state = parse_dashboard(payload(daily=self.promos, points=self.points), TODAY)
        return state


def test_activities_open_supported_and_report_results():
    promos = [promo("A"), promo("B"), promo("W", promotionType="welcometour"),
              promo("DONE", complete=True)]
    session = ActivitySession(promos)
    opened = []

    def opener(sess, p, pacer):
        opened.append(p.offer_id)
        if p.offer_id == "A":
            promos[0]["complete"] = True
            sess.points += 10
        else:
            raise RuntimeError("kart yok")

    report = run_activities(session, fast_settings(), Pacer(sleep=lambda s: None), opener=opener)
    assert opened == ["A", "B"]
    assert report.completed == ["Title A"]
    assert report.failed == ["Title B"]
    assert report.skipped == ["Title W"]
    assert report.points_gained == 10


# -- scheduling / state ------------------------------------------------------------------

def test_task_xml_and_cron():
    xml = task_xml(r"C:\Py\pythonw.exe", r"C:\bot & co", "9:05", 60, user_id=r"PC\baran",
                   today=TODAY)
    assert "<StartBoundary>2026-10-14T09:05:00</StartBoundary>" in xml
    assert "<RandomDelay>PT60M</RandomDelay>" in xml
    assert r"C:\bot &amp; co" in xml
    assert "--once-per-day" in xml and "<StartWhenAvailable>true" in xml
    import xml.etree.ElementTree as ET
    ET.fromstring(xml.split("?>", 1)[1])  # well-formed
    assert crontab_line("/usr/bin/python3", "/opt/bot", "10:30").startswith("30 10 * * * ")
    assert windowless_python("/usr/bin/python3") == "/usr/bin/python3"


def test_run_lock(tmp_path):
    lock = tmp_path / "run.lock"
    with RunLock(lock):
        with pytest.raises(AlreadyRunning):
            with RunLock(lock):
                pass
    assert not lock.exists()
    lock.write_text("123")
    with RunLock(lock, stale_after=0):  # stale lock is replaced
        assert lock.exists()


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    assert read_state(path) == {}
    write_state(path, {"last_success_date": TODAY.isoformat()})
    assert done_today(read_state(path), TODAY)
    assert not done_today(read_state(path), date(2026, 10, 15))


def test_summary_lines():
    summary = RunSummary(start_points=100, end_points=250,
                         activities=ActivityReport(attempted=["a"], completed=["A"]),
                         searches=[SearchReport("desktop", searches=30, start=Progress(0, 90),
                                                end=Progress(90, 90))])
    text = "\n".join(summary.lines())
    assert "250" in text and "+150" in text and "1/1" in text and "90/90" in text
    assert summary.to_dict()["searches"] == {"desktop": 30}
