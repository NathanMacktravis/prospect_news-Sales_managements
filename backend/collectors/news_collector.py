"""
News Collector — fetches raw articles from free sources (DuckDuckGo + RSS)
with optional Tavily fallback if an API key is provided.

All sources are filtered to the past 7 days to ensure freshness.

Cost:
  - DuckDuckGo  : FREE, no API key (duckduckgo-search)
  - RSS         : FREE, no limits
  - Tavily      : optional — 1,000 req/month free (Starter plan)
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser
import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ─── Freshness window ─────────────────────────────────────────────────────────

MAX_ARTICLE_AGE_DAYS = int(os.getenv("MAX_ARTICLE_AGE_DAYS", "7"))


def _cutoff() -> datetime:
    """Return the oldest acceptable publication date (now - MAX_ARTICLE_AGE_DAYS)."""
    return datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string (RFC 2822 or ISO 8601) into a timezone-aware datetime."""
    if not date_str:
        return None
    # RFC 2822 (used by RSS feeds)
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # ISO 8601
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    return None


def _is_recent(date_str: str | None) -> bool:
    """Return True if the article is within the freshness window (or date unknown)."""
    dt = _parse_date(date_str)
    if dt is None:
        return True  # keep articles whose date couldn't be parsed
    return dt >= _cutoff()


# ─── Wealth-signal search queries ────────────────────────────────────────────

def _current_year() -> str:
    return str(datetime.now(timezone.utc).year)


def _search_queries() -> list[str]:
    """Build queries with the current year so results stay fresh."""
    year = _current_year()
    return [
        f"IPO founder CEO wealth {year}",
        f"M&A acquisition billion entrepreneur exit {year}",
        f"startup unicorn fundraising Series B C {year}",
        "billionaire family office new investment",
        "private equity deal founder liquidity event",
        "tech founder sold company proceeds",
    ]


# ─── Curated RSS feeds — 100% free ──────────────────────────────────────────

def _rss_feeds() -> list[str]:
    """RSS feeds with Google News URLs filtered to the past week."""
    return [
        # General financial news
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/technologyNews",
        "https://fortune.com/feed/",
        "https://www.forbes.com/investing/feed/",
        "https://www.forbes.com/entrepreneurs/feed/",
        "https://techcrunch.com/feed/",
        "https://venturebeat.com/feed/",
        # M&A / Private Equity
        "https://www.pehub.com/feed/",
        "https://pitchbook.com/news/rss.xml",
        # Startups & fundraising
        "https://eu.startups.com/feed",
        "https://sifted.eu/feed",
        # Google News — filtered to past week via tbs=qdr:w
        "https://news.google.com/rss/search?q=IPO+founder+billion&hl=en&gl=US&ceid=US:en&tbs=qdr:w",
        "https://news.google.com/rss/search?q=acquisition+merger+CEO+billion&hl=en&gl=US&ceid=US:en&tbs=qdr:w",
        "https://news.google.com/rss/search?q=startup+unicorn+fundraising&hl=en&gl=US&ceid=US:en&tbs=qdr:w",
        "https://news.google.com/rss/search?q=HNWI+UHNWI+wealth+management&hl=en&gl=US&ceid=US:en&tbs=qdr:w",
    ]


# ─── Models ──────────────────────────────────────────────────────────────────

class RawArticle(BaseModel):
    title: str
    url: str
    content: str
    source: str
    published_at: Optional[str] = None
    collected_at: str = ""

    def model_post_init(self, __context):
        if not self.collected_at:
            self.collected_at = datetime.now(timezone.utc).isoformat()


# ─── DuckDuckGo Collector (FREE — no API key) ─────────────────────────────────

class DuckDuckGoCollector:
    """
    DuckDuckGo News search — entirely free, no API key.
    Uses timelimit="w" to restrict results to the past week.
    """

    def search(self, query: str, max_results: int = 5) -> list[RawArticle]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("duckduckgo-search not installed. pip install duckduckgo-search")
            return []

        articles = []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(
                    query,
                    max_results=max_results,
                    timelimit="w",   # past 7 days
                ))
            for r in results:
                articles.append(RawArticle(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("body", ""),
                    source="duckduckgo",
                    published_at=r.get("date"),
                ))
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed for '{query}': {e}")
        return articles

    def collect_all(
        self,
        queries: list[str] | None = None,
        max_per_query: int = 5,
    ) -> list[RawArticle]:
        queries = queries or _search_queries()
        all_articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = self.search(query, max_results=max_per_query)
            for article in results:
                if article.url and article.url not in seen_urls:
                    seen_urls.add(article.url)
                    all_articles.append(article)
            time.sleep(1.0)  # avoid DDG rate-limit

        logger.info(f"DuckDuckGo collected {len(all_articles)} unique articles")
        return all_articles


# ─── Tavily Collector (optional — 1,000 req/month free) ──────────────────────

class TavilyCollector:
    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY is required")

    def search(self, query: str, max_results: int = 5) -> list[RawArticle]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "max_results": max_results,
            "topic": "news",
            "days": MAX_ARTICLE_AGE_DAYS,   # restrict to freshness window
        }
        try:
            resp = requests.post(self.BASE_URL, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Tavily search failed for '{query}': {e}")
            return []

        articles = []
        for result in data.get("results", []):
            articles.append(RawArticle(
                title=result.get("title", ""),
                url=result.get("url", ""),
                content=result.get("content", ""),
                source="tavily",
                published_at=result.get("published_date"),
            ))
        return articles

    def collect_all(
        self,
        queries: list[str] | None = None,
        max_per_query: int = 3,
    ) -> list[RawArticle]:
        queries = (queries or _search_queries())[:3]
        all_articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = self.search(query, max_results=max_per_query)
            for article in results:
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    all_articles.append(article)
            time.sleep(0.5)

        logger.info(f"Tavily collected {len(all_articles)} unique articles")
        return all_articles


# ─── RSS Collector (FREE — no limits) ────────────────────────────────────────

class RSSCollector:
    WEALTH_KEYWORDS = [
        "ipo", "acquisition", "merger", "fundraising", "billion", "million",
        "unicorn", "series a", "series b", "series c", "founder", "exit",
        "private equity", "hedge fund", "wealth", "fortune", "ceo appoint",
        "ceo named", "president named", "chairman", "spac", "listing",
        "sold company", "stake", "buyout", "deal", "investment round",
    ]

    def __init__(self, feeds: list[str] | None = None):
        self.feeds = feeds or _rss_feeds()

    def _is_relevant(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.WEALTH_KEYWORDS)

    def collect(self, max_per_feed: int = 10) -> list[RawArticle]:
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()
        stale_count = 0

        for feed_url in self.feeds:
            try:
                feed = feedparser.parse(feed_url)
            except Exception as e:
                logger.warning(f"RSS parse failed for {feed_url}: {e}")
                continue

            count = 0
            for entry in feed.entries:
                if count >= max_per_feed:
                    break

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                url = entry.get("link", "")

                if not url or url in seen_urls:
                    continue

                combined = f"{title} {summary}"
                if not self._is_relevant(combined):
                    continue

                published = entry.get("published") or entry.get("updated")

                # Skip articles outside the freshness window
                if not _is_recent(published):
                    stale_count += 1
                    continue

                articles.append(RawArticle(
                    title=title,
                    url=url,
                    content=summary,
                    source=feed.feed.get("title", feed_url),
                    published_at=published,
                ))
                seen_urls.add(url)
                count += 1

        if stale_count:
            logger.info(f"RSS skipped {stale_count} articles older than {MAX_ARTICLE_AGE_DAYS} days")
        logger.info(f"RSS collected {len(articles)} relevant articles")
        return articles


# ─── Unified Collector ────────────────────────────────────────────────────────

class NewsCollector:
    """
    Collection strategy (by cost priority):
      1. RSS          — FREE, unlimited       (primary source)
      2. DuckDuckGo   — FREE, no API key      (secondary source)
      3. Tavily       — optional, 1k req/mo   (if TAVILY_API_KEY provided)

    All sources are restricted to articles published within MAX_ARTICLE_AGE_DAYS
    (default: 7 days). Articles are sorted by recency before being returned so
    that the LLM extraction step sees the freshest content first.
    """

    def __init__(
        self,
        tavily_api_key: str | None = None,
        rss_feeds: list[str] | None = None,
        use_duckduckgo: bool = True,
        use_rss: bool = True,
        use_tavily: bool = False,
    ):
        self.use_duckduckgo = use_duckduckgo
        self.use_rss = use_rss
        self.use_tavily = use_tavily

        if use_duckduckgo:
            self.ddg = DuckDuckGoCollector()

        if use_rss:
            self.rss = RSSCollector(feeds=rss_feeds)

        if use_tavily:
            try:
                self.tavily = TavilyCollector(api_key=tavily_api_key)
            except ValueError:
                logger.info("Tavily disabled — no API key found")
                self.use_tavily = False

    def collect(
        self,
        max_ddg_per_query: int = 5,
        max_tavily_per_query: int = 3,
        max_rss_per_feed: int = 10,
    ) -> list[RawArticle]:
        articles: list[RawArticle] = []

        # 1. RSS (free)
        if self.use_rss:
            articles.extend(self.rss.collect(max_per_feed=max_rss_per_feed))

        # 2. DuckDuckGo (free)
        if self.use_duckduckgo:
            articles.extend(self.ddg.collect_all(max_per_query=max_ddg_per_query))

        # 3. Tavily (optional, limited quota)
        if self.use_tavily:
            articles.extend(self.tavily.collect_all(max_per_query=max_tavily_per_query))

        # Deduplicate by URL
        seen: set[str] = set()
        unique = []
        for a in articles:
            if a.url and a.url not in seen:
                seen.add(a.url)
                unique.append(a)

        # Sort by recency — most recent first so Claude sees freshest articles first
        def _sort_key(a: RawArticle) -> datetime:
            dt = _parse_date(a.published_at)
            return dt if dt is not None else _cutoff()

        unique.sort(key=_sort_key, reverse=True)

        logger.info(
            f"Total collected: {len(unique)} unique articles "
            f"(past {MAX_ARTICLE_AGE_DAYS} days)"
        )
        return unique
