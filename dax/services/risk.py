"""Rule-based mapper: NLP analysis -> audit-relevant risk flags.

Reads `domain/isa315_map.yaml` and evaluates every rule against a single
headline's `Analysis`. A rule fires when:

  * at least one of its `triggers.topics` has a zero-shot score >=
    `topic_threshold` (default 0.55), AND
  * if the rule specifies a sentiment gate, the FinBERT label matches
    AND the score >= `sentiment_threshold`.

This is deliberately transparent: an auditor should be able to read this
file and predict what will fire on any given headline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from services.nlp import Analysis


_RULES_PATH = Path(__file__).parent.parent / "domain" / "isa315_map.yaml"

# Zero-shot scores below this are treated as "the model did not really say that".
# Tuned empirically for facebook/bart-large-mnli against financial headlines.
DEFAULT_TOPIC_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class RiskFlag:
    """One rule firing on one headline."""
    rule_id: str
    category: str
    severity: str          # "low" | "medium" | "high"
    matched_topics: list[tuple[str, float]]  # (topic, score) that crossed threshold
    sentiment_matched: bool                  # True iff rule had a sentiment gate and it matched
    description: str
    audit_ref: dict[str, Any]
    procedures: list[str]


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_rules() -> list[dict]:
    with _RULES_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or []


def all_topic_labels() -> list[str]:
    """Union of every `triggers.topics` value across all rules.

    This is the label set we feed to the zero-shot classifier. Kept as an
    ordered de-dup so runs are reproducible.
    """
    seen: dict[str, None] = {}
    for rule in load_rules():
        for topic in rule.get("triggers", {}).get("topics", []):
            seen.setdefault(topic, None)
    return list(seen.keys())


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

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

    # Optional sentiment gate.
    sentiment_matched = True
    if "sentiment" in triggers:
        required = triggers["sentiment"].lower()
        thresh = float(triggers.get("sentiment_threshold", 0.5))
        got = analysis.sentiment
        if got.label != required or got.score < thresh:
            return None
        sentiment_matched = True

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
    """Return every rule that fires on this headline (may be empty)."""
    flags = [
        flag
        for rule in load_rules()
        if (flag := _evaluate_rule(rule, analysis, topic_threshold)) is not None
    ]
    # Order by severity so the UI can render worst-first without re-sorting.
    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: order.get(f.severity, 99))
    return flags
