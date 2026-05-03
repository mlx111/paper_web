"""Source Boost configuration — prefix-match weights for search ranking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceBoostConfig:
    source_weights: dict[str, float] = field(default_factory=dict)
    hard_excludes: list[str] = field(default_factory=list)
    keyword_boosts: dict[str, float] = field(default_factory=dict)


DEFAULT_SOURCE_BOOSTS = SourceBoostConfig(
    source_weights={
        "papers/": 1.5,
        "papers/arxiv/": 1.4,
        "papers/semanticscholar/": 1.4,
        "research/": 1.3,
        "concepts/": 1.2,
        "authors/": 1.1,
        "institutions/": 1.1,
        "presentations/": 1.0,
        "notes/": 0.8,
        "chat/": 0.5,
    },
    hard_excludes=["tmp/", "debug/", "archive/", "test/"],
    keyword_boosts={
        "attention": 1.2,
        "transformer": 1.2,
        "RAG": 1.3,
    },
)


def compute_source_boost(
    slug: str, config: SourceBoostConfig | None = None
) -> float:
    """Longest-prefix-match against source weights. Returns 1.0 if no match."""
    if config is None:
        config = DEFAULT_SOURCE_BOOSTS
    best_boost = 1.0
    best_len = 0
    for prefix, boost in config.source_weights.items():
        if slug.startswith(prefix) and len(prefix) > best_len:
            best_boost = boost
            best_len = len(prefix)
    return best_boost


def compute_keyword_boost(
    query: str, config: SourceBoostConfig | None = None
) -> float:
    """Check if query contains any boosted keywords. Returns max applicable boost or 1.0."""
    if config is None:
        config = DEFAULT_SOURCE_BOOSTS
    best = 1.0
    for keyword, boost in config.keyword_boosts.items():
        if keyword.lower() in query.lower():
            best = max(best, boost)
    return best


def is_hard_excluded(
    slug: str, config: SourceBoostConfig | None = None
) -> bool:
    """Check whether slug matches any hard-exclude prefix pattern."""
    if config is None:
        config = DEFAULT_SOURCE_BOOSTS
    for pattern in config.hard_excludes:
        if slug.startswith(pattern):
            return True
    return False
