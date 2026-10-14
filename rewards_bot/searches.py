"""Bing searches until the desktop / mobile search counters are full.

The counters on the dashboard are the source of truth: the bot searches in
batches, re-reads the counter, and slows down to a few searches per cooldown
when Bing stops crediting every search.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import quote_plus, urlparse

from .browser import BING_HOME, SessionExpired
from .config import Settings
from .dashboard import DashboardState, Progress
from .queries import QueryPool
from .util import Pacer

log = logging.getLogger("rewards_bot.searches")

POINTS_PER_SEARCH = 3
SLOW_BATCH = 3
MAX_CONSECUTIVE_ERRORS = 5
BING_SEARCH = "https://www.bing.com/search?q={query}&form=QBLH"
PLATFORM_NAMES = {"desktop": "Masaüstü", "mobile": "Mobil"}


@dataclass
class SearchReport:
    platform: str
    searches: int = 0
    start: Optional[Progress] = None
    end: Optional[Progress] = None
    note: str = ""

    @property
    def gained(self) -> int:
        if self.start is None or self.end is None:
            return 0
        return max(0, self.end.points - self.start.points)

    @property
    def complete(self) -> bool:
        return self.end is not None and self.end.done


def counter_for(platform: str, state: Optional[DashboardState]) -> Optional[Progress]:
    if state is None:
        return None
    return state.pc_search if platform == "desktop" else state.mobile_search


def perform_search(session, query: str, pacer: Pacer) -> None:
    """Type the query into Bing's search box; fall back to the results URL."""
    page = session.page
    box = page.locator("#sb_form_q").first
    try:
        on_bing = (urlparse(page.url).hostname or "").endswith("bing.com")
        if not on_bing or not box.is_visible():
            session.goto(BING_HOME)
            session.dismiss_consent()
        box.click(timeout=5_000)
        box.fill("")
        page.keyboard.type(query, delay=pacer.rng.randint(40, 110))
        pacer.pause(0.3, 1.2)
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
            page.keyboard.press("Enter")
    except Exception as exc:
        log.debug("Arama kutusu kullanılamadı (%s), sonuç sayfası açılıyor", exc)
        session.goto(BING_SEARCH.format(query=quote_plus(query)))
    try:
        page.mouse.wheel(0, pacer.rng.randint(300, 1400))
    except Exception:
        pass


SearchFn = Callable[[object, str, Pacer], None]


def run_searches(session, settings: Settings, pool: QueryPool, platform: str,
                 pacer: Pacer, search_fn: SearchFn = perform_search) -> SearchReport:
    name = PLATFORM_NAMES[platform]
    report = SearchReport(platform)
    state = session.read_dashboard()
    progress = counter_for(platform, state)
    report.start = report.end = progress

    if state is not None and progress is None:
        report.note = "bu hesapta bu arama türü yok"
        log.info("%s arama: %s", name, report.note)
        return report
    if progress is not None and progress.done:
        report.note = "zaten tamamlanmış"
        log.info("%s arama: %s (%d/%d)", name, report.note, progress.points, progress.maximum)
        return report

    session.ensure_bing_signed_in()
    cap = settings.max_searches_per_run
    errors = 0

    def search_once() -> bool:
        nonlocal errors
        query = pool.next()
        try:
            search_fn(session, query, pacer)
            errors = 0
        except SessionExpired:
            raise
        except Exception as exc:
            errors += 1
            log.warning("Arama başarısız (%s): %s", query, str(exc).splitlines()[0] if str(exc) else exc)
            if errors >= MAX_CONSECUTIVE_ERRORS:
                return False
        report.searches += 1
        log.info("%s arama %d: %s", name, report.searches, query)
        pacer.pause(*settings.search_delay_seconds)
        return True

    if progress is None:
        fallback = (settings.fallback_desktop_searches if platform == "desktop"
                    else settings.fallback_mobile_searches)
        count = min(cap, fallback)
        log.warning("%s arama: puan sayacı okunamadı, %d arama yapılacak", name, count)
        for _ in range(count):
            if not search_once():
                break
        report.note = "sayaç okunamadı"
        return report

    log.info("%s arama: %d/%d puan, %d puan kaldı", name, progress.points,
             progress.maximum, progress.remaining)
    slow = False
    stalls = 0
    while not progress.done and report.searches < cap:
        batch = SLOW_BATCH if slow else math.ceil(progress.remaining / POINTS_PER_SEARCH)
        batch = max(1, min(batch, cap - report.searches))
        for _ in range(batch):
            if not search_once():
                report.note = "arka arkaya çok fazla hata"
                return report
        pacer.pause(5, 10)  # the counter lags a few seconds behind
        new = counter_for(platform, session.read_dashboard())
        if new is None:
            report.note = "sayaç okunamadı"
            break
        gained = new.points - progress.points
        progress = report.end = new
        log.info("%s arama: %d/%d puan (+%d)", name, new.points, new.maximum, max(gained, 0))
        if progress.done:
            break
        if gained <= 0:
            stalls += 1
            if stalls >= settings.max_stalls:
                report.note = "puan artmıyor, bugünlük durduruldu"
                break
            slow = True
            log.info("%s arama: puan artmadı, %g dk beklenip yeniden denenecek",
                     name, settings.cooldown_minutes)
            pacer.wait_minutes(settings.cooldown_minutes)
            continue
        stalls = 0
        if not slow and gained < batch * POINTS_PER_SEARCH / 2:
            # Only a few searches counted: Bing is pacing this account.
            slow = True
            log.info("%s arama: Bing aramaları yavaş sayıyor, her %g dakikada %d arama yapılacak",
                     name, settings.cooldown_minutes, SLOW_BATCH)
        if slow:
            pacer.wait_minutes(settings.cooldown_minutes)

    if not progress.done and not report.note and report.searches >= cap:
        report.note = f"çalıştırma başına {cap} arama sınırına ulaşıldı"
    return report
