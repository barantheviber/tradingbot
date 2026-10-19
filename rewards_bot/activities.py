"""Daily set and "more activities" cards on the Rewards dashboard.

For each unfinished card the bot clicks the card itself on the dashboard, so
the site reports the activity the same way it does for a person. Cards that
cannot be found are opened through their link instead. Quiz and poll pages
are answered on a best-effort basis (Bing's classic quiz widget).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .browser import REWARDS_ACTIVITY_PAGES, SessionExpired
from .config import Settings
from .dashboard import Promotion, find_promotion, pending_activities
from .util import Pacer

log = logging.getLogger("rewards_bot.activities")

POLL_OPTIONS = ("#btoption0", "#btoption1")
QUIZ_START = "#rqStartQuiz"
QUIZ_DONE = "#quizCompleteContainer"
MAX_QUIZ_ROUNDS = 15

# Index of every link whose host, path and ?q= match the activity's link.
_FIND_LINKS_JS = """(target) => {
  const key = (u) => {
    try {
      const x = new URL(u, location.href);
      return (x.host.replace(/^www\\./, '') + x.pathname).toLowerCase() + '|' +
             (x.searchParams.get('q') || '').toLowerCase();
    } catch (e) { return null; }
  };
  const want = key(target);
  const out = [];
  if (!want) return out;
  document.querySelectorAll('a[href]').forEach((a, i) => { if (key(a.href) === want) out.push(i); });
  return out;
}"""

_QUIZ_INFO_JS = "() => (window._w && window._w.rewardsQuizRenderInfo) || null"

_QUIZ_OPTIONS_JS = """(n) => Array.from({length: n}, (_, i) => {
  const el = document.getElementById('rqAnswerOption' + i);
  return el ? {'data-option': el.getAttribute('data-option'),
               'iscorrectoption': el.getAttribute('iscorrectoption')} : null;
})"""


@dataclass
class ActivityReport:
    attempted: List[str] = field(default_factory=list)
    completed: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    points_gained: int = 0
    note: str = ""


def choose_answers(info: Mapping[str, Any], options: Sequence[Optional[Mapping[str, Any]]],
                   rng: random.Random) -> List[int]:
    """Which ``#rqAnswerOption{i}`` to click for the current question.

    Multi-answer quizzes mark the right options with ``iscorrectoption``;
    single-answer ones expose the answer's ``data-option`` in the page data.
    Anything else (e.g. "this or that") gets a random pick.
    """
    present = [i for i, opt in enumerate(options) if opt]
    if not present:
        return []
    marked = [i for i in present
              if str(options[i].get("iscorrectoption") or "").lower() == "true"]
    if marked:
        return marked
    correct = info.get("correctAnswer")
    if correct is not None:
        matches = [i for i in present if options[i].get("data-option") == str(correct)]
        if matches:
            return matches[:1]
    return [rng.choice(present)]


def _visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible()
    except Exception:
        return False


def _css_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def find_card(page, promo: Promotion):
    """The clickable element for ``promo`` on the current dashboard page, or None."""
    offer = _css_value(promo.offer_id)
    for selector in (f'[data-bi-id="{offer}"]', f'[data-offerid="{offer}"]',
                     f'[data-offer-id="{offer}"]', f'[data-id="{offer}"]'):
        locator = page.locator(selector).locator("visible=true").first
        if _visible(locator):
            return locator
    if promo.destination_url:
        try:
            indexes = page.evaluate(_FIND_LINKS_JS, promo.destination_url) or []
        except Exception:
            indexes = []
        for index in indexes:
            locator = page.locator("a[href]").nth(int(index))
            if _visible(locator):
                return locator
    if promo.title:
        locator = page.get_by_text(promo.title, exact=True).locator("visible=true").first
        if _visible(locator):
            return locator
    return None


def answer_quiz_page(tab, pacer: Pacer) -> str:
    """Answer a poll or the classic Bing quiz on ``tab``; returns what it found."""
    polls = [tab.locator(s).first for s in POLL_OPTIONS]
    visible_polls = [p for p in polls if _visible(p)]
    if visible_polls:
        pacer.rng.choice(visible_polls).click(timeout=10_000)
        pacer.pause(2, 4)
        return "poll"

    start = tab.locator(QUIZ_START).first
    if _visible(start):
        start.click(timeout=10_000)
        pacer.pause(2, 4)

    answered = False
    for _ in range(MAX_QUIZ_ROUNDS):
        if _visible(tab.locator(QUIZ_DONE).first):
            break
        info = tab.evaluate(_QUIZ_INFO_JS)
        if not isinstance(info, dict):
            break
        count = int(info.get("numberOfOptions") or 0)
        options = tab.evaluate(_QUIZ_OPTIONS_JS, count) if count > 0 else []
        picks = choose_answers(info, options, pacer.rng)
        if not picks:
            break
        for index in picks:
            try:
                tab.locator(f"#rqAnswerOption{index}").click(timeout=5_000)
            except Exception as exc:
                log.debug("Seçenek %d tıklanamadı: %s", index, exc)
            pacer.pause(1.5, 3)
        answered = True
        pacer.pause(2, 4)
    return "quiz" if answered else "none"


def _wait_new_page(context, pages_before: int, page, seconds: float = 10.0):
    for _ in range(int(seconds * 2)):
        if len(context.pages) > pages_before:
            return context.pages[-1]
        page.wait_for_timeout(500)
    return None


def open_activity(session, promo: Promotion, pacer: Pacer) -> None:
    card = None
    for url in REWARDS_ACTIVITY_PAGES:
        session.goto(url)
        if session.on_login_page():
            raise SessionExpired("Microsoft oturumu kapalı; `python -m rewards_bot login` çalıştırın.")
        card = find_card(session.page, promo)
        if card is not None:
            break

    page = session.page
    tab = None
    if card is not None:
        pages_before = len(session.context.pages)
        try:
            card.scroll_into_view_if_needed(timeout=5_000)
            card.click(timeout=10_000)
            tab = _wait_new_page(session.context, pages_before, page) or page
        except Exception as exc:
            log.debug("Kart tıklanamadı: %s", exc)
    if tab is None:
        if not promo.destination_url:
            raise RuntimeError("panelde kart bulunamadı ve görevin bağlantısı yok")
        log.info("Kart panelde bulunamadı, görev bağlantısı doğrudan açılıyor")
        tab = session.context.new_page()
        session.goto(promo.destination_url, page=tab)

    try:
        try:
            tab.wait_for_load_state("domcontentloaded", timeout=30_000)
        except Exception:
            pass
        if promo.promotion_type == "quiz":
            result = answer_quiz_page(tab, pacer)
            log.debug("Test sayfası: %s", result)
        pacer.pause(6, 12)
    finally:
        if tab is not page:
            try:
                tab.close()
            except Exception:
                pass


OpenFn = Callable[[Any, Promotion, Pacer], None]


def run_activities(session, settings: Settings, pacer: Pacer,
                   opener: OpenFn = open_activity) -> ActivityReport:
    report = ActivityReport()
    state = session.read_dashboard()
    if state is None:
        report.note = "görev listesi okunamadı"
        log.warning("Görevler: %s", report.note)
        return report
    todo = pending_activities(state, settings.daily_set, settings.more_activities)
    if not todo:
        report.note = "yapılacak görev yok"
        log.info("Görevler: %s", report.note)
        return report

    log.info("Görevler: %d yapılacak", len(todo))
    for promo in todo:
        label = promo.title or promo.offer_id
        if not promo.supported:
            report.skipped.append(label)
            log.info("Atlandı (desteklenmeyen tür '%s'): %s", promo.promotion_type, label)
            continue
        log.info("Görev: %s (%d puan)", label, promo.max_points - promo.points)
        report.attempted.append(promo.offer_id)
        try:
            opener(session, promo, pacer)
        except SessionExpired:
            raise
        except Exception as exc:
            log.warning("Görev açılamadı (%s): %s", label, str(exc).splitlines()[0] if str(exc) else exc)
        pacer.pause(3, 8)

    after = session.read_dashboard()
    if after is None:
        report.note = "sonuç okunamadı"
        return report
    titles: Dict[str, str] = {p.offer_id: (p.title or p.offer_id) for p in todo}
    for offer_id in report.attempted:
        promo = find_promotion(after, offer_id)
        if promo is not None and (promo.complete or promo.points >= promo.max_points):
            report.completed.append(titles[offer_id])
        else:
            report.failed.append(titles[offer_id])
    report.points_gained = max(0, after.available_points - state.available_points)
    log.info("Görevler: %d/%d tamamlandı (+%d puan)", len(report.completed),
             len(report.attempted), report.points_gained)
    return report
