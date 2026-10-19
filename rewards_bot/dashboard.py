"""Parsing of the Rewards dashboard JSON (rewards.bing.com/api/getuserinfo).

Pure functions only, so they can be tested without a browser.

Relevant shape of the payload::

    {"dashboard": {
        "userStatus": {
            "availablePoints": 1234,
            "counters": {
                "pcSearch":     [{"pointProgress": 30, "pointProgressMax": 90}, ...],
                "mobileSearch": [{"pointProgress": 0,  "pointProgressMax": 60}]}},
        "dailySetPromotions": {"10/14/2026": [<promotion>, ...]},
        "morePromotions": [<promotion>, ...]}}

A promotion carries offerId, title, promotionType, destinationUrl, complete,
pointProgress, pointProgressMax and a few lock flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, List, Mapping, Optional, Tuple

DATE_KEY_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%d.%m.%Y")

# Activity types the bot knows how to open; anything else is left alone.
SUPPORTED_PROMOTION_TYPES = ("urlreward", "quiz")


class DashboardError(ValueError):
    pass


@dataclass(frozen=True)
class Progress:
    points: int
    maximum: int

    @property
    def remaining(self) -> int:
        return max(0, self.maximum - self.points)

    @property
    def done(self) -> bool:
        return self.remaining == 0


@dataclass(frozen=True)
class Promotion:
    offer_id: str
    title: str
    promotion_type: str
    destination_url: str
    complete: bool
    points: int
    max_points: int
    locked: bool

    @property
    def pending(self) -> bool:
        return (not self.complete and not self.locked
                and self.max_points > 0 and self.points < self.max_points)

    @property
    def supported(self) -> bool:
        return self.promotion_type in SUPPORTED_PROMOTION_TYPES


@dataclass(frozen=True)
class DashboardState:
    available_points: int
    pc_search: Optional[Progress]
    mobile_search: Optional[Progress]
    daily_set: Tuple[Promotion, ...]
    more_promotions: Tuple[Promotion, ...]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def parse_counter(entries: Any) -> Optional[Progress]:
    """Sum a search counter; desktop can have two entries (Bing + Edge bonus)."""
    if not isinstance(entries, list) or not entries:
        return None
    rows = [e for e in entries if isinstance(e, Mapping)]
    if not rows:
        return None
    return Progress(points=sum(_int(e.get("pointProgress")) for e in rows),
                    maximum=sum(_int(e.get("pointProgressMax")) for e in rows))


def parse_promotion(raw: Any) -> Optional[Promotion]:
    if not isinstance(raw, Mapping):
        return None
    offer_id = str(raw.get("offerId") or raw.get("name") or "").strip()
    if not offer_id:
        return None
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), Mapping) else {}
    locked = (
        str(raw.get("exclusiveLockedFeatureStatus") or "").lower() == "locked"
        or str(attributes.get("is_unlocked", "true")).strip().lower() == "false"
        or _truthy(attributes.get("hidden", False))
    )
    return Promotion(
        offer_id=offer_id,
        title=str(raw.get("title") or "").strip(),
        promotion_type=str(raw.get("promotionType") or "").strip().lower(),
        destination_url=str(raw.get("destinationUrl") or "").strip(),
        complete=_truthy(raw.get("complete", False)),
        points=_int(raw.get("pointProgress")),
        max_points=_int(raw.get("pointProgressMax")),
        locked=locked,
    )


def _parse_date_key(key: str) -> Optional[date]:
    for fmt in DATE_KEY_FORMATS:
        try:
            return datetime.strptime(key.strip(), fmt).date()
        except ValueError:
            continue
    return None


def daily_set_for(day_map: Any, today: date) -> List[Mapping[str, Any]]:
    if not isinstance(day_map, Mapping):
        return []
    for key, items in day_map.items():
        if _parse_date_key(str(key)) == today and isinstance(items, list):
            return items
    return []


def _promotions(items: Iterable[Any]) -> Tuple[Promotion, ...]:
    parsed = (parse_promotion(item) for item in items)
    return tuple(p for p in parsed if p is not None)


def parse_dashboard(payload: Any, today: date) -> DashboardState:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("dashboard"), Mapping):
        raise DashboardError("yanıtta 'dashboard' alanı yok (oturum kapalı olabilir)")
    dashboard = payload["dashboard"]
    status = dashboard.get("userStatus") if isinstance(dashboard.get("userStatus"), Mapping) else {}
    counters = status.get("counters") if isinstance(status.get("counters"), Mapping) else {}
    more = dashboard.get("morePromotions")
    return DashboardState(
        available_points=_int(status.get("availablePoints")),
        pc_search=parse_counter(counters.get("pcSearch")),
        mobile_search=parse_counter(counters.get("mobileSearch")),
        daily_set=_promotions(daily_set_for(dashboard.get("dailySetPromotions"), today)),
        more_promotions=_promotions(more if isinstance(more, list) else []),
    )


def pending_activities(state: DashboardState, daily_set: bool = True,
                       more_promotions: bool = True) -> List[Promotion]:
    """Unfinished, unlocked activities worth points, without duplicates."""
    chosen: List[Promotion] = []
    seen = set()
    groups = ((daily_set, state.daily_set), (more_promotions, state.more_promotions))
    for enabled, promotions in groups:
        if not enabled:
            continue
        for promo in promotions:
            if promo.pending and promo.offer_id not in seen:
                seen.add(promo.offer_id)
                chosen.append(promo)
    return chosen


def find_promotion(state: DashboardState, offer_id: str) -> Optional[Promotion]:
    for promo in state.daily_set + state.more_promotions:
        if promo.offer_id == offer_id:
            return promo
    return None
