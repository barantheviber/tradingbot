"""Search queries: today's Google Trends, Bing related searches, Wikipedia's
most read pages, and a built-in list when none of those can be reached.
"""

from __future__ import annotations

import json
import logging
import random
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from datetime import date, timedelta
from typing import Callable, Deque, Iterable, List, Optional, Sequence

log = logging.getLogger("rewards_bot.queries")

TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
BING_RELATED = "https://api.bing.com/osjson.aspx?query={query}"
WIKIPEDIA_TOP = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                 "{lang}.wikipedia/all-access/{year}/{month:02d}/{day:02d}")
USER_AGENT = "rewards-bot/1.0 (kisisel kullanim)"

# Pages that are always on top of the Wikipedia charts but make odd searches.
_WIKI_SKIP = {"main_page", "anasayfa", "ana_sayfa", "wikipedia", "-"}

FALLBACK_QUERIES = {
    "tr": [
        "hava durumu", "döviz kurları", "altın fiyatları", "süper lig puan durumu",
        "kolay yemek tarifleri", "mercimek çorbası tarifi", "en iyi telefonlar",
        "istanbul gezilecek yerler", "kapadokya balon turu", "film önerileri",
        "dizi önerileri", "kitap önerileri", "akşam yemeği tarifleri", "kahvaltı tarifleri",
        "evde spor hareketleri", "sağlıklı beslenme", "uyku düzeni nasıl sağlanır",
        "python öğrenme", "excel formülleri", "ingilizce kelime öğrenme",
        "bilgisayar hızlandırma", "laptop önerileri", "oyun bilgisayarı",
        "uzay haberleri", "deprem son dakika", "elektrikli araçlar", "güneş paneli fiyatları",
        "antalya tatil", "kamp malzemeleri", "bisiklet önerileri", "kedi bakımı",
        "köpek eğitimi", "bitki bakımı", "kahve çeşitleri", "türk kahvesi nasıl yapılır",
        "pilav tarifi", "baklava tarifi", "basketbol sonuçları", "formula 1 takvimi",
        "şampiyonlar ligi", "borsa istanbul", "kripto para haberleri", "yapay zeka nedir",
        "müze kart", "tiyatro oyunları", "konser takvimi", "namaz vakitleri",
        "trafik durumu", "otobüs bileti", "uçak bileti", "nöbetçi eczane",
    ],
    "en": [
        "weather forecast", "exchange rates", "gold price", "football results",
        "easy dinner recipes", "best smartphones", "travel destinations", "movie recommendations",
        "book recommendations", "home workout", "healthy breakfast ideas", "how to sleep better",
        "learn python", "excel formulas", "laptop deals", "space news", "electric cars",
        "solar panels cost", "camping gear", "best hiking trails", "cat care tips",
        "dog training", "houseplant care", "coffee brewing methods", "banana bread recipe",
        "basketball scores", "formula 1 calendar", "champions league", "stock market today",
        "what is artificial intelligence", "museum exhibitions", "concert tickets",
        "nearest pharmacy", "flight tickets", "train schedule", "world news",
    ],
}

_VARIANT_SUFFIXES = {
    "tr": ["nedir", "haberleri", "fiyatları", "nasıl yapılır", "yorumları", "son dakika"],
    "en": ["meaning", "news", "price", "how to", "reviews", "latest"],
}

Fetch = Callable[[str], str]


def http_get(url: str, timeout: float = 15.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - fixed https URLs
        return response.read().decode("utf-8", errors="replace")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_trends_rss(xml_text: str) -> List[str]:
    """Trend keywords first, then the related news headlines."""
    root = ET.fromstring(xml_text)
    keywords: List[str] = []
    headlines: List[str] = []
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        for child in item:
            if _local_name(child.tag) == "title" and (child.text or "").strip():
                keywords.append(child.text.strip())
        for node in item.iter():
            if _local_name(node.tag) == "news_item_title" and (node.text or "").strip():
                headlines.append(node.text.strip())
    return keywords + headlines


def parse_bing_related(json_text: str) -> List[str]:
    data = json.loads(json_text)
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return [s.strip() for s in data[1] if isinstance(s, str) and s.strip()]
    return []


def parse_wikipedia_top(json_text: str, limit: int = 60) -> List[str]:
    data = json.loads(json_text)
    titles: List[str] = []
    for block in data.get("items", []) if isinstance(data, dict) else []:
        for row in block.get("articles", []):
            article = str(row.get("article", ""))
            if not article or ":" in article or article.lower() in _WIKI_SKIP:
                continue
            titles.append(article.replace("_", " "))
            if len(titles) >= limit:
                return titles
    return titles


def dedupe(queries: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for query in queries:
        query = " ".join(query.split())
        key = query.casefold()
        if query and key not in seen and len(query) <= 120:
            seen.add(key)
            result.append(query)
    return result


def collect_queries(language: str, country: str, needed: int,
                    fetch: Fetch = http_get, today: Optional[date] = None,
                    rng: Optional[random.Random] = None) -> List[str]:
    """Gather at least ``needed`` distinct queries, freshest sources first."""
    rng = rng or random.Random()
    today = today or date.today()
    trends: List[str] = []
    related: List[str] = []
    wiki: List[str] = []

    try:
        trends = parse_trends_rss(fetch(TRENDS_RSS.format(geo=urllib.parse.quote(country))))
    except Exception as exc:  # network, XML: any failure just means fewer sources
        log.warning("Google Trends okunamadı: %s", exc)

    for keyword in trends[:10]:
        if len(dedupe(trends + related)) >= needed:
            break
        try:
            related += parse_bing_related(fetch(BING_RELATED.format(query=urllib.parse.quote(keyword))))
        except Exception as exc:
            log.debug("Bing ilgili aramalar okunamadı (%s): %s", keyword, exc)

    if len(dedupe(trends + related)) < needed:
        day = today - timedelta(days=2)  # the pageview API lags about a day
        try:
            wiki = parse_wikipedia_top(fetch(WIKIPEDIA_TOP.format(
                lang=urllib.parse.quote(language), year=day.year, month=day.month, day=day.day)))
        except Exception as exc:
            log.warning("Wikipedia listesi okunamadı: %s", exc)

    fresh = dedupe(trends + related + wiki)
    rng.shuffle(fresh)
    fallback = list(FALLBACK_QUERIES.get(language, FALLBACK_QUERIES["en"]))
    rng.shuffle(fallback)
    queries = dedupe(fresh + fallback)
    log.info("%d arama sorgusu hazır (trend: %d, ilgili: %d, wikipedia: %d)",
             len(queries), len(trends), len(related), len(wiki))
    return queries


class QueryPool:
    """Hands out each query once; when the list runs dry it makes variants."""

    def __init__(self, queries: Sequence[str], language: str = "tr",
                 rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()
        self._queue: Deque[str] = deque(dedupe(queries))
        self._base = dedupe(list(self._queue)
                            + FALLBACK_QUERIES.get(language, FALLBACK_QUERIES["en"]))
        self._suffixes = _VARIANT_SUFFIXES.get(language, _VARIANT_SUFFIXES["en"])
        self._used = set()

    def next(self) -> str:
        while self._queue:
            query = self._queue.popleft()
            if query.casefold() not in self._used:
                self._used.add(query.casefold())
                return query
        for _ in range(50):
            query = f"{self._rng.choice(self._base)} {self._rng.choice(self._suffixes)}"
            if query.casefold() not in self._used:
                self._used.add(query.casefold())
                return query
        return self._rng.choice(self._base)
