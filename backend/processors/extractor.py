"""
Prospect Extractor — uses Claude API (claude-haiku-4-5) with prompt caching
to extract structured HNWI/UHNWI prospect data from wealth-signaled articles.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from backend.processors.signal_detector import SignaledArticle

logger = logging.getLogger(__name__)

# ─── Output schema ────────────────────────────────────────────────────────────

class ProspectData(BaseModel):
    name: str = Field(description="Full name of the individual (or 'Unknown')")
    title: str = Field(description="Current title/role, e.g. 'Founder & CEO'")
    company: str = Field(description="Company name")
    sector: str = Field(description="Industry sector, e.g. 'Technology', 'Finance'")
    event_type: str = Field(
        description="Type of wealth event: IPO | M&A | Fundraising | Exit | Appointment | Other"
    )
    event_summary: str = Field(
        description="1–2 sentence factual description of the wealth event"
    )
    estimated_amount_usd: Optional[float] = Field(
        None, description="Estimated wealth/deal amount in USD (null if unknown)"
    )
    amount_label: str = Field(
        description="Human-readable amount, e.g. '$1.2B', '$450M', 'Undisclosed'"
    )
    location: str = Field(
        description="Country or city, e.g. 'France', 'San Francisco, USA'"
    )
    source_url: str = Field(description="Original article URL")
    published_at: Optional[str] = Field(
        None, description="Article publication date (ISO 8601 or null)"
    )
    sales_pitch: str = Field(
        description=(
            "2–3 sentence sales-ready talking point for a private banker. "
            "Focus on the liquidity event, timing, and how a wealth manager could add value."
        )
    )
    urgency_score: int = Field(
        ge=0, le=10,
        description="Urgency to contact this prospect (0=low, 10=critical). "
                    "Higher if event is recent or time-sensitive."
    )
    confidence_score: int = Field(
        ge=0, le=100,
        description="Confidence that this person is a real HNWI/UHNWI prospect (0–100)."
    )
    extracted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── System prompt (stable — will be cached) ─────────────────────────────────

SYSTEM_PROMPT = """You are an expert analyst at a leading private bank, specialized in identifying
High-Net-Worth Individual (HNWI) and Ultra-High-Net-Worth Individual (UHNWI) prospects from
financial news.

Your role is to extract structured prospect intelligence from news articles and produce
'Sales-Ready' insights for private bankers.

EXTRACTION RULES:
1. Focus exclusively on INDIVIDUALS (founders, executives, investors) — not institutions.
2. Extract the MOST PROMINENT individual if multiple are mentioned.
3. Wealth thresholds: HNWI = $1M+ net worth | UHNWI = $30M+ net worth.
4. For event amounts: IPO/M&A/fundraising amounts count as wealth proxy.
5. If the individual's name is unclear, use "Unknown (see article)".
6. Sales pitch must be ACTIONABLE for a private banker — mention timing, liquidity, and
   potential banking needs (wealth structuring, investment, succession planning).
7. Urgency: 8-10 = event happened within 7 days; 5-7 = within 30 days; 0-4 = older.
8. Confidence: 90-100 = named individual with explicit financial event;
   70-89 = likely HNWI based on role/context; below 70 = speculative.

RESPONSE FORMAT: Respond ONLY with a valid JSON object matching the required schema.
Do not include explanations, markdown code blocks, or any text outside the JSON."""


# ─── Extractor ────────────────────────────────────────────────────────────────

class ProspectExtractor:
    def __init__(self, api_key: str | None = None):
        self.client = anthropic.Anthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY")
        )
        self.model = "claude-haiku-4-5"

    def _build_user_message(self, article: SignaledArticle) -> str:
        signals_summary = ", ".join(sorted(article.signal_categories))
        return f"""ARTICLE TO ANALYZE:

Title: {article.article.title}
URL: {article.article.url}
Source: {article.article.source}
Published: {article.article.published_at or 'Unknown'}

Content:
{article.article.content[:3000]}

Detected wealth signals: [{signals_summary}]
Preliminary signal score: {article.signal_score:.2f}

Extract the prospect data and return a JSON object."""

    def extract(self, article: SignaledArticle) -> ProspectData | None:
        """Extract prospect data from a single article using Claude with prompt caching."""
        try:
            # System prompt uses cache_control — it's large and stable across all calls
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},  # cache the stable system prompt
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": self._build_user_message(article),
                    }
                ],
            )

            raw_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            ).strip()

            # Strip markdown code blocks if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            data = json.loads(raw_text)
            data["source_url"] = article.article.url
            data["published_at"] = article.article.published_at

            prospect = ProspectData(**data)

            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            cache_created = getattr(response.usage, "cache_creation_input_tokens", 0)
            logger.debug(
                f"Extracted '{prospect.name}' | cache_read={cache_read} "
                f"cache_write={cache_created} | confidence={prospect.confidence_score}"
            )

            return prospect

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for article '{article.article.title}': {e}")
            return None
        except Exception as e:
            logger.warning(f"Extraction failed for '{article.article.title}': {e}")
            return None

    def extract_batch(
        self,
        articles: list[SignaledArticle],
        min_confidence: int = 60,
    ) -> list[ProspectData]:
        """Extract prospects from a batch of signaled articles."""
        prospects: list[ProspectData] = []

        for i, article in enumerate(articles):
            logger.info(
                f"Extracting [{i+1}/{len(articles)}]: {article.article.title[:60]}..."
            )
            prospect = self.extract(article)
            if prospect and prospect.confidence_score >= min_confidence:
                prospects.append(prospect)

        logger.info(f"Extracted {len(prospects)} qualified prospects from {len(articles)} articles")
        return prospects
