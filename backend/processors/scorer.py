"""
Prospect Scorer — computes a composite wealth potential score (0–100)
by combining LLM confidence, signal richness, event type weight, and urgency.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.processors.extractor import ProspectData


# ─── Scoring weights ──────────────────────────────────────────────────────────

EVENT_TYPE_WEIGHTS = {
    "IPO": 1.0,
    "Exit": 0.95,
    "M&A": 0.9,
    "Fundraising": 0.75,
    "Appointment": 0.5,
    "Other": 0.4,
}

# Multipliers based on estimated deal amount
AMOUNT_MULTIPLIERS = [
    (10_000_000_000, 1.0),   # $10B+  → max
    (1_000_000_000, 0.9),    # $1B+
    (500_000_000, 0.8),      # $500M+
    (100_000_000, 0.7),      # $100M+
    (50_000_000, 0.6),       # $50M+
    (10_000_000, 0.5),       # $10M+
    (1_000_000, 0.4),        # $1M+
    (0, 0.3),                # unknown/small
]


def _amount_multiplier(amount_usd: float | None) -> float:
    if not amount_usd:
        return 0.3
    for threshold, mult in AMOUNT_MULTIPLIERS:
        if amount_usd >= threshold:
            return mult
    return 0.3


@dataclass
class ScoredProspect:
    data: ProspectData
    potential_score: int       # 0–100 overall wealth potential
    urgency_score: int         # 0–10 from LLM, re-exposed here for convenience
    composite_rank: float      # used for sorting; higher = better

    @property
    def name(self) -> str:
        return self.data.name

    @property
    def company(self) -> str:
        return self.data.company

    @property
    def event_type(self) -> str:
        return self.data.event_type

    @property
    def amount_label(self) -> str:
        return self.data.amount_label

    @property
    def sales_pitch(self) -> str:
        return self.data.sales_pitch

    @property
    def source_url(self) -> str:
        return self.data.source_url


def score_prospect(prospect: ProspectData) -> ScoredProspect:
    """Compute composite score for a single prospect."""

    # 1. LLM confidence (0–100 → 0.0–1.0)
    confidence_component = prospect.confidence_score / 100.0

    # 2. Event type weight (0.0–1.0)
    event_weight = EVENT_TYPE_WEIGHTS.get(prospect.event_type, 0.4)

    # 3. Amount multiplier (0.0–1.0)
    amount_mult = _amount_multiplier(prospect.estimated_amount_usd)

    # 4. Urgency contribution (0–10 → 0.0–1.0)
    urgency_component = prospect.urgency_score / 10.0

    # Weighted formula:
    # 40% confidence · 30% event weight · 20% amount · 10% urgency
    raw_score = (
        0.40 * confidence_component
        + 0.30 * event_weight
        + 0.20 * amount_mult
        + 0.10 * urgency_component
    )

    potential_score = round(raw_score * 100)
    potential_score = max(0, min(100, potential_score))

    # Composite rank for sorting: weight urgency more for same potential score
    composite_rank = raw_score + (urgency_component * 0.05)

    return ScoredProspect(
        data=prospect,
        potential_score=potential_score,
        urgency_score=prospect.urgency_score,
        composite_rank=composite_rank,
    )


def rank_prospects(
    prospects: list[ProspectData],
    top_n: int = 5,
    min_score: int = 40,
) -> list[ScoredProspect]:
    """Score, filter, and rank a list of prospects. Returns the top N."""
    scored = [score_prospect(p) for p in prospects]
    filtered = [s for s in scored if s.potential_score >= min_score]
    filtered.sort(key=lambda s: s.composite_rank, reverse=True)

    # Deduplicate by name (keep highest-scored)
    seen_names: set[str] = set()
    unique: list[ScoredProspect] = []
    for s in filtered:
        key = s.name.lower().strip()
        if key not in seen_names or key == "unknown":
            seen_names.add(key)
            unique.append(s)

    return unique[:top_n]
