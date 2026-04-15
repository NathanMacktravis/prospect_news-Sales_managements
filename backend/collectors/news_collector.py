"""
News Collector — fetches raw articles from free sources (DuckDuckGo + RSS)
with optional Tavily fallback if an API key is provided.

Coût :
  - DuckDuckGo  : GRATUIT, sans clé API (duckduckgo-search)
  - RSS         : GRATUIT, aucune limite
  - Tavily      : optionnel — 1 000 req/mois gratuits (plan Starter)
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ─── Wealth-signal search queries ────────────────────────────────────────────
# Utilisées par DuckDuckGo (gratuit) ET Tavily (optionnel)
SEARCH_QUERIES = [
    "IPO founder CEO wealth 2025",
    "M&A acquisition billion entrepreneur exit",
    "startup unicorn fundraising Series B C",
    "billionaire family office new investment",
    "private equity deal founder liquidity event",
    "tech founder sold company proceeds",
]

# ─── Curated RSS feeds — 100 % gratuits ──────────────────────────────────────
RSS_FEEDS = [
    # Actualités financières générales
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
    # Startups & levées de fonds
    "https://eu.startups.com/feed",
    "https://sifted.eu/feed",
    # Google News (RSS gratuit, no key)
    "https://news.google.com/rss/search?q=IPO+founder+billion&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=acquisition+merger+CEO+billion&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=startup+unicorn+fundraising+2025&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=HNWI+UHNWI+wealth+management&hl=en&gl=US&ceid=US:en",
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


# ─── DuckDuckGo Collector (GRATUIT — aucune clé API) ──────────────────────────

class DuckDuckGoCollector:
    """
    Recherche via DuckDuckGo News — entièrement gratuit, sans clé API.
    Utilise la librairie `duckduckgo-search`.
    """

    def search(self, query: str, max_results: int = 5) -> list[RawArticle]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("duckduckgo-search non installé. pip install duckduckgo-search")
            return []

        articles = []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=max_results))
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
        queries = queries or SEARCH_QUERIES
        all_articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = self.search(query, max_results=max_per_query)
            for article in results:
                if article.url and article.url not in seen_urls:
                    seen_urls.add(article.url)
                    all_articles.append(article)
            time.sleep(1.0)  # pause entre requêtes pour éviter le rate-limit DDG

        logger.info(f"DuckDuckGo collected {len(all_articles)} unique articles")
        return all_articles


# ─── Tavily Collector (optionnel — 1 000 req/mois gratuits) ──────────────────

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
            "search_depth": "basic",   # "basic" = moins de quota consommé
            "include_answer": False,
            "include_raw_content": False,
            "max_results": max_results,
            "topic": "news",
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
        # Limiter à 3 requêtes max par run pour rester dans le quota gratuit
        queries = (queries or SEARCH_QUERIES)[:3]
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


# ─── RSS Collector (GRATUIT — aucune limite) ──────────────────────────────────

class RSSCollector:
    WEALTH_KEYWORDS = [
        "ipo", "acquisition", "merger", "fundraising", "billion", "million",
        "unicorn", "series a", "series b", "series c", "founder", "exit",
        "private equity", "hedge fund", "wealth", "fortune", "ceo appoint",
        "ceo named", "president named", "chairman", "spac", "listing",
        "sold company", "stake", "buyout", "deal", "investment round",
    ]

    def __init__(self, feeds: list[str] | None = None):
        self.feeds = feeds or RSS_FEEDS

    def _is_relevant(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.WEALTH_KEYWORDS)

    def collect(self, max_per_feed: int = 10) -> list[RawArticle]:
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

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

                published = None
                if hasattr(entry, "published"):
                    published = entry.published

                articles.append(RawArticle(
                    title=title,
                    url=url,
                    content=summary,
                    source=feed.feed.get("title", feed_url),
                    published_at=published,
                ))
                seen_urls.add(url)
                count += 1

        logger.info(f"RSS collected {len(articles)} relevant articles")
        return articles


# ─── Unified Collector ────────────────────────────────────────────────────────

class NewsCollector:
    """
    Stratégie de collecte (par ordre de priorité coût) :
      1. RSS          — GRATUIT, illimité           (source primaire)
      2. DuckDuckGo   — GRATUIT, sans clé API       (source secondaire)
      3. Tavily       — optionnel, 1 000 req/mois   (si TAVILY_API_KEY fourni)
    """

    def __init__(
        self,
        tavily_api_key: str | None = None,
        rss_feeds: list[str] | None = None,
        use_duckduckgo: bool = True,
        use_rss: bool = True,
        use_tavily: bool = False,   # désactivé par défaut — activer si clé dispo
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
                logger.info("Tavily désactivé — aucune clé API trouvée")
                self.use_tavily = False

    def collect(
        self,
        max_ddg_per_query: int = 5,
        max_tavily_per_query: int = 3,
        max_rss_per_feed: int = 10,
    ) -> list[RawArticle]:
        articles: list[RawArticle] = []

        # 1. RSS (gratuit)
        if self.use_rss:
            articles.extend(self.rss.collect(max_per_feed=max_rss_per_feed))

        # 2. DuckDuckGo (gratuit)
        if self.use_duckduckgo:
            articles.extend(self.ddg.collect_all(max_per_query=max_ddg_per_query))

        # 3. Tavily (optionnel, quota limité)
        if self.use_tavily:
            articles.extend(self.tavily.collect_all(max_per_query=max_tavily_per_query))

        # Dédoublonnage par URL
        seen: set[str] = set()
        unique = []
        for a in articles:
            if a.url and a.url not in seen:
                seen.add(a.url)
                unique.append(a)

        logger.info(f"Total collecté : {len(unique)} articles uniques")
        return unique
