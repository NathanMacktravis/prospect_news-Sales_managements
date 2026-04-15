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

SYSTEM_PROMPT = """You are an expert analyst at a leading private bank identifying HNWI/UHNWI prospects from financial news.

RULES:
1. Focus on INDIVIDUALS (founders, executives, investors) — not institutions.
2. Extract the MOST PROMINENT individual if multiple are mentioned.
3. If the individual's name is unclear, use "Unknown".
4. Sales pitch must mention timing, liquidity, and banking needs.
5. Urgency: 8-10 = within 7 days; 5-7 = within 30 days; 0-4 = older.
6. Confidence: 90-100 = named person + explicit financial event; 70-89 = likely HNWI; below 70 = speculative.

YOU MUST return ONLY a raw JSON object. No markdown, no code block, no explanation.
Use EXACTLY these field names (copy them exactly as written below):

{
  "name": "Full name or Unknown",
  "title": "Job title e.g. Founder & CEO",
  "company": "Company name",
  "sector": "Industry sector e.g. Technology",
  "event_type": "IPO or M&A or Fundraising or Exit or Appointment or Other",
  "event_summary": "1-2 sentences describing the wealth event",
  "estimated_amount_usd": 1000000000,
  "amount_label": "$1B or Undisclosed",
  "location": "Country or City, Country",
  "sales_pitch": "2-3 sentence actionable pitch for a private banker",
  "urgency_score": 7,
  "confidence_score": 85
}

CRITICAL: Use ONLY these exact key names. Do NOT use prospect_name, prospect_title, or any other variation."""


# ─── Aliases : noms alternatifs que Haiku peut produire ──────────────────────
# Clé canonique → liste des variantes acceptées
_FIELD_ALIASES: dict[str, list[str]] = {
    "name":                 ["prospect_name", "individual_name", "person_name", "full_name"],
    "title":                ["prospect_title", "job_title", "role", "position"],
    "company":              ["company_name", "firm", "organization", "organisation"],
    "sector":               ["industry", "industry_sector", "business_sector"],
    "event_type":           ["wealth_event_type", "event", "type"],
    "event_summary":        ["summary", "description", "event_description", "wealth_event"],
    "estimated_amount_usd": ["amount_usd", "deal_amount", "amount", "value_usd"],
    "amount_label":         ["amount_display", "deal_size", "wealth_amount", "value"],
    "location":             ["country", "city", "geography", "region"],
    "sales_pitch":          ["pitch", "banker_pitch", "sales_note", "recommendation"],
    "urgency_score":        ["urgency", "contact_urgency"],
    "confidence_score":     ["confidence", "hnwi_confidence", "prospect_confidence"],
}

# Valeurs par défaut pour les champs obligatoires si vraiment absents
_FIELD_DEFAULTS: dict[str, object] = {
    "name":            "Unknown",
    "title":           "N/A",
    "company":         "N/A",
    "sector":          "Finance",
    "event_type":      "Other",
    "event_summary":   "Wealth event detected — see source article.",
    "amount_label":    "Undisclosed",
    "location":        "Unknown",
    "sales_pitch":     "Recent wealth event detected. Contact for wealth management services.",
    "urgency_score":   5,
    "confidence_score": 60,
}


def _normalize_json(raw: dict, article_url: str, article_date: str | None) -> dict:
    """
    Normalise le JSON brut retourné par Haiku avant validation Pydantic :
      1. Désimbrique un wrapper top-level ("prospect", "data", "result"…)
      2. Remplace les noms de champs alternatifs par les noms canoniques
      3. Applique les valeurs par défaut sur les champs manquants
      4. Corrige les types évidents (None → str, float castable)
    """
    # 1. Désimbrication : {"prospect": {...}} ou {"data": {...}}
    if len(raw) == 1:
        only_key = next(iter(raw))
        if isinstance(raw[only_key], dict):
            raw = raw[only_key]

    # 2. Remplacer les alias par les noms canoniques
    normalized: dict = {}
    for canonical, aliases in _FIELD_ALIASES.items():
        # Chercher le champ canonique d'abord, puis les alias
        for key in [canonical] + aliases:
            if key in raw:
                normalized[canonical] = raw[key]
                break

    # Copier les champs restants qui ne sont pas des alias connus
    all_alias_keys = {alias for aliases in _FIELD_ALIASES.values() for alias in aliases}
    for k, v in raw.items():
        if k not in _FIELD_ALIASES and k not in all_alias_keys:
            normalized[k] = v

    # 3. Appliquer les valeurs par défaut pour les champs manquants
    for field, default in _FIELD_DEFAULTS.items():
        if field not in normalized or normalized[field] is None:
            normalized[field] = default

    # 4. Corrections de type
    # sales_pitch doit être une str (jamais None)
    if not isinstance(normalized.get("sales_pitch"), str):
        normalized["sales_pitch"] = _FIELD_DEFAULTS["sales_pitch"]

    # scores doivent être des entiers
    for score_field in ("urgency_score", "confidence_score"):
        try:
            normalized[score_field] = int(normalized[score_field])
        except (TypeError, ValueError):
            normalized[score_field] = _FIELD_DEFAULTS[score_field]

    # estimated_amount_usd peut être None ou un nombre
    amt = normalized.get("estimated_amount_usd")
    if amt is not None:
        try:
            normalized["estimated_amount_usd"] = float(amt)
        except (TypeError, ValueError):
            normalized["estimated_amount_usd"] = None

    # 5. Injecter les métadonnées de l'article (toujours override)
    normalized["source_url"] = article_url
    normalized["published_at"] = article_date

    return normalized


# ─── Extractor ────────────────────────────────────────────────────────────────

class ProspectExtractor:
    def __init__(self, api_key: str | None = None):
        self.client = anthropic.Anthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY")
        )
        self.model = "claude-haiku-4-5"

    def _build_user_message(self, article: SignaledArticle) -> str:
        signals_summary = ", ".join(sorted(article.signal_categories))
        return f"""ARTICLE:
Title: {article.article.title}
Source: {article.article.source}
Published: {article.article.published_at or 'Unknown'}
Signals: [{signals_summary}]

Content:
{article.article.content[:2000]}

Return ONLY a raw JSON object with these exact keys: name, title, company, sector, event_type, event_summary, estimated_amount_usd, amount_label, location, sales_pitch, urgency_score, confidence_score"""

    def extract(self, article: SignaledArticle) -> ProspectData | None:
        """Extract prospect data from a single article using Claude with prompt caching."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
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

            # Nettoyer les blocs markdown si présents (```json ... ```)
            if "```" in raw_text:
                parts = raw_text.split("```")
                # Prendre le premier bloc entre backticks
                for part in parts[1::2]:
                    cleaned = part.lstrip("json").strip()
                    if cleaned.startswith("{"):
                        raw_text = cleaned
                        break

            # Extraire le premier objet JSON si du texte parasite précède
            brace_start = raw_text.find("{")
            brace_end = raw_text.rfind("}")
            if brace_start != -1 and brace_end != -1:
                raw_text = raw_text[brace_start:brace_end + 1]

            raw_data = json.loads(raw_text)

            # Normaliser avant validation Pydantic
            data = _normalize_json(
                raw_data,
                article_url=article.article.url,
                article_date=article.article.published_at,
            )

            prospect = ProspectData(**data)

            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            logger.debug(
                f"Extracted '{prospect.name}' | cache_hit={cache_read > 0} "
                f"| confidence={prospect.confidence_score}"
            )

            return prospect

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for '{article.article.title[:50]}': {e}")
            return None
        except Exception as e:
            logger.warning(f"Extraction failed for '{article.article.title[:50]}': {e}")
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
