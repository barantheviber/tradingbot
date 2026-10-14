"""One full run: activities, desktop searches, then mobile searches."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional

from .activities import ActivityReport, run_activities
from .browser import BrowserSession
from .config import Settings
from .queries import QueryPool, collect_queries
from .searches import PLATFORM_NAMES, SearchReport, run_searches
from .util import Pacer

log = logging.getLogger("rewards_bot.runner")

PARTS = ("activities", "desktop", "mobile")


@dataclass
class RunSummary:
    start_points: Optional[int] = None
    end_points: Optional[int] = None
    activities: Optional[ActivityReport] = None
    searches: List[SearchReport] = field(default_factory=list)

    @property
    def gained(self) -> Optional[int]:
        if self.start_points is None or self.end_points is None:
            return None
        return self.end_points - self.start_points

    def lines(self) -> List[str]:
        out = []
        if self.end_points is not None:
            gained = f" (bugünkü çalıştırma: +{self.gained})" if self.gained is not None else ""
            out.append(f"Toplam puan: {self.end_points}{gained}")
        if self.activities is not None:
            a = self.activities
            if a.attempted or a.skipped:
                out.append(f"Görevler: {len(a.completed)}/{len(a.attempted)} tamamlandı"
                           + (f", {len(a.skipped)} atlandı" if a.skipped else ""))
                for title in a.failed:
                    out.append(f"  - tamamlanamadı: {title}")
            elif a.note:
                out.append(f"Görevler: {a.note}")
        for report in self.searches:
            line = f"{PLATFORM_NAMES[report.platform]} arama: {report.searches} arama"
            if report.end is not None:
                line += f", sayaç {report.end.points}/{report.end.maximum}"
            if report.note:
                line += f" ({report.note})"
            out.append(line)
        return out

    def to_dict(self) -> dict:
        return {
            "start_points": self.start_points,
            "end_points": self.end_points,
            "activities_completed": len(self.activities.completed) if self.activities else 0,
            "searches": {r.platform: r.searches for r in self.searches},
            "summary": self.lines(),
        }


def run_once(settings: Settings, parts: Optional[Iterable[str]] = None,
             headless: Optional[bool] = None, pacer: Optional[Pacer] = None,
             today: Optional[date] = None) -> RunSummary:
    pacer = pacer or Pacer()
    today = today or date.today()
    wanted = set(parts or PARTS)
    summary = RunSummary()

    searching = (("desktop" in wanted and settings.desktop_searches)
                 or ("mobile" in wanted and settings.mobile_searches))
    queries = (collect_queries(settings.language, settings.country,
                               settings.max_searches_per_run * 2, rng=pacer.rng)
               if searching else [])
    pool = QueryPool(queries, settings.language, pacer.rng)

    run_mobile = "mobile" in wanted and settings.mobile_searches
    with BrowserSession(settings, mobile=False, headless=headless, today=today) as session:
        session.open_rewards()
        state = session.read_dashboard()
        if state is None:
            log.warning("Rewards paneli okunamadı; yalnızca aramalar yapılacak.")
        else:
            summary.start_points = summary.end_points = state.available_points
            log.info("Başlangıç puanı: %d", state.available_points)

        if "activities" in wanted and (settings.daily_set or settings.more_activities) and state:
            summary.activities = run_activities(session, settings, pacer)
        if "desktop" in wanted and settings.desktop_searches:
            summary.searches.append(run_searches(session, settings, pool, "desktop", pacer))

        latest = session.read_dashboard()
        if latest is not None:
            summary.end_points = latest.available_points
            mobile = latest.mobile_search
            if run_mobile and (mobile is None or mobile.done):
                note = "bu hesapta bu arama türü yok" if mobile is None else "zaten tamamlanmış"
                summary.searches.append(SearchReport("mobile", start=mobile, end=mobile, note=note))
                log.info("Mobil arama: %s", note)
                run_mobile = False

    if run_mobile:
        with BrowserSession(settings, mobile=True, headless=headless, today=today) as session:
            session.open_rewards()
            summary.searches.append(run_searches(session, settings, pool, "mobile", pacer))
            final = session.read_dashboard()
            if final is not None:
                summary.end_points = final.available_points

    for line in summary.lines():
        log.info(line)
    return summary
