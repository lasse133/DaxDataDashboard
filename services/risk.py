"""Rule-based mapper: NLP analysis -> audit-relevant risk flags.

Rules use zero-shot topic scores, optional evidence keywords, and optional
sentiment gates. The configuration remains reviewable in isa315_map.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from services.nlp import Analysis


_RULES_PATH = Path(__file__).parent.parent / "domain" / "isa315_map.yaml"
DEFAULT_TOPIC_THRESHOLD = 0.55


@dataclass
class RiskFlag:
    """One rule firing on one headline."""

    rule_id: str
    category: str
    severity: str
    matched_topics: list[tuple[str, float]]
    sentiment_matched: bool
    description: str
    audit_ref: dict[str, Any]
    procedures: list[str]


@lru_cache(maxsize=1)
def load_rules() -> list[dict]:
    with _RULES_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def all_topic_labels() -> list[str]:
    """Ordered union of every configured audit-risk topic."""
    seen: dict[str, None] = {}
    for rule in load_rules():
        for topic in rule.get("triggers", {}).get("topics", []):
            seen.setdefault(topic, None)
    return list(seen)


DISPLAY_TOPIC_LABELS = [
    "stock price movement",
    "cloud growth",
    "software demand",
    "earnings outlook",
    "quarterly results",
    "analyst rating",
    "product strategy",
    "enterprise software",
    "market commentary",
]


def classification_topic_labels() -> list[str]:
    """Risk and neutral labels sent to the zero-shot classifier."""
    seen: dict[str, None] = {}
    for label in [*all_topic_labels(), *DISPLAY_TOPIC_LABELS]:
        seen.setdefault(label, None)
    return list(seen)


def _evaluate_rule(rule: dict, analysis: Analysis, topic_threshold: float) -> RiskFlag | None:
    triggers = rule.get("triggers", {})
    rule_topics: list[str] = triggers.get("topics", [])

    matched = [
        (topic, analysis.topics.scores.get(topic, 0.0))
        for topic in rule_topics
        if analysis.topics.scores.get(topic, 0.0) >= topic_threshold
    ]
    if not matched:
        return None

    sentiment_matched = True
    if "sentiment" in triggers:
        required = triggers["sentiment"].lower()
        threshold = float(triggers.get("sentiment_threshold", 0.5))
        if analysis.sentiment.label != required or analysis.sentiment.score < threshold:
            return None

    return RiskFlag(
        rule_id=rule["id"],
        category=rule["category"],
        severity=rule["severity"],
        matched_topics=matched,
        sentiment_matched=sentiment_matched,
        description=rule.get("description", "").strip(),
        audit_ref=rule.get("audit_ref", {}),
        procedures=list(rule.get("procedures", [])),
    )


def evaluate(analysis: Analysis, topic_threshold: float = DEFAULT_TOPIC_THRESHOLD) -> list[RiskFlag]:
    """Return every rule that fires on this headline."""
    flags = [
        flag
        for rule in load_rules()
        if (flag := _evaluate_rule(rule, analysis, topic_threshold)) is not None
    ]
    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda flag: order.get(flag.severity, 99))
    return flags
