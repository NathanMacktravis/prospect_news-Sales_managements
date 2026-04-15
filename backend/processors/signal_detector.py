"""
Signal Detector — first-pass keyword filter to identify articles
that contain HNWI/UHNWI wealth signals before sending to the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.collectors.news_collector import RawArticle


# ─── Signal taxonomy ──────────────────────────────────────────────────────────

SIGNAL_CATEGORIES: dict[str, list[str]] = {
    "ipo": [
        r"\bipo\b", r"initial public offering", r"stock market listing",
        r"went public", r"market debut", r"nasdaq listing", r"nyse listing",
        r"spac merger", r"direct listing",
    ],
    "ma": [
        r"acquisition", r"merger", r"takeover", r"acquired by", r"bought out",
        r"deal worth", r"billion deal", r"strategic acquisition",
        r"m&a", r"private equity buyout",
    ],
    "fundraising": [
        r"raised \$", r"series [abcde]\b", r"funding round", r"venture capital",
        r"seed round", r"growth equity", r"unicorn", r"decacorn",
        r"valuation of \$", r"valued at \$",
    ],
    "exit": [
        r"sold (?:his|her|their) (?:company|stake|shares)",
        r"founder exit", r"cashed out", r"liquidity event",
        r"partial exit", r"secondary sale",
    ],
    "appointment": [
        r"named (?:ceo|cfo|coo|chairman|president|managing director)",
        r"appointed (?:ceo|cfo|coo|chairman|president)",
        r"new (?:ceo|cfo|chairman) of",
        r"steps down as ceo",
        r"board of directors",
    ],
    "wealth_signal": [
        r"\bbillionaire\b", r"\bmillionaire\b", r"net worth",
        r"family office", r"ultra-high.?net.?worth", r"hnwi", r"uhnwi",
        r"wealth manager", r"private banking",
        r"luxury (?:real estate|yacht|jet|property)",
        r"forbes (?:list|400|richest)",
    ],
    "financial_milestone": [
        r"\$\d+(?:\.\d+)?\s*(?:billion|million)\b",
        r"\d+(?:\.\d+)?\s*(?:billion|million) (?:dollars|euros|pounds)",
        r"hedge fund", r"asset management", r"private equity",
    ],
}

# ─── Result model ─────────────────────────────────────────────────────────────

@dataclass
class SignalMatch:
    category: str
    pattern: str
    snippet: str  # 100-char context around the match


@dataclass
class SignaledArticle:
    article: RawArticle
    signals: list[SignalMatch] = field(default_factory=list)
    signal_categories: set[str] = field(default_factory=set)
    signal_score: float = 0.0  # 0.0–1.0 preliminary score

    @property
    def is_relevant(self) -> bool:
        return len(self.signals) > 0


# ─── Detector ─────────────────────────────────────────────────────────────────

# Category weights for preliminary scoring
CATEGORY_WEIGHTS = {
    "ipo": 1.0,
    "ma": 0.9,
    "fundraising": 0.8,
    "exit": 0.9,
    "appointment": 0.5,
    "wealth_signal": 0.7,
    "financial_milestone": 0.6,
}

def detect_signals(article: RawArticle) -> SignaledArticle:
    """Run keyword detection on a single article."""
    text = f"{article.title} {article.content}".lower()
    result = SignaledArticle(article=article)

    for category, patterns in SIGNAL_CATEGORIES.items():
        for raw_pattern in patterns:
            regex = re.compile(raw_pattern, re.IGNORECASE)
            for match in regex.finditer(text):
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                snippet = text[start:end].replace("\n", " ").strip()
                result.signals.append(SignalMatch(
                    category=category,
                    pattern=raw_pattern,
                    snippet=snippet,
                ))
                result.signal_categories.add(category)

    # Preliminary score: sum of unique category weights, capped at 1.0
    total_weight = sum(
        CATEGORY_WEIGHTS.get(cat, 0.5)
        for cat in result.signal_categories
    )
    result.signal_score = min(total_weight / 3.0, 1.0)  # normalize: 3 cats = full score

    return result


def filter_articles(
    articles: list[RawArticle],
    min_signal_score: float = 0.2,
) -> list[SignaledArticle]:
    """Filter a batch of raw articles, returning only those with wealth signals."""
    signaled = [detect_signals(a) for a in articles]
    relevant = [s for s in signaled if s.is_relevant and s.signal_score >= min_signal_score]

    # Sort by preliminary score descending
    relevant.sort(key=lambda s: s.signal_score, reverse=True)
    return relevant
