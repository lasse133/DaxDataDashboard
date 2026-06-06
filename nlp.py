"""
nlp.py
------
The "Process + Score" layer.

  - analyze_sentiment(text)  -> FinBERT financial sentiment (positive/negative/neutral + confidence)
  - extract_risk_drivers(text) -> ISA-315-style risk categories via the lexicon in config.py
  - score_headline(item)     -> combines both into one enriched record the UI can render

FinBERT (ProsusAI/finbert) is loaded once and cached. The first call downloads
the model (~400 MB) from Hugging Face; afterwards it runs locally.
"""

from __future__ import annotations
from functools import lru_cache

import config
from audit_references import map_audit_reference

POSITIVE_KEYWORDS = [
    "beat",
    "beats",
    "growth",
    "profit",
    "raises",
    "record",
    "strong",
    "upgrade",
]


@lru_cache(maxsize=1)
def _get_pipeline():
    """Load FinBERT once. Cached for the life of the process."""
    from transformers import pipeline
    return pipeline(
        task="text-classification",
        model="ProsusAI/finbert",
        top_k=None,          # return scores for all three classes
    )


def analyze_sentiment(text: str) -> dict:
    """
    Return {"label": "negative", "score": 0.91, "scores": {pos,neg,neu}}.
    `score` is the confidence of the winning label.
    """
    try:
        clf = _get_pipeline()
        raw = clf(text[:512])            # FinBERT max input length
        # `raw` is a list with one element (a list of {label, score} dicts)
        scores = {d["label"].lower(): float(d["score"]) for d in raw[0]}
    except Exception:
        scores = _fallback_sentiment_scores(text)

    label = max(scores, key=scores.get)
    return {"label": label, "score": scores[label], "scores": scores}


def _fallback_sentiment_scores(text: str) -> dict[str, float]:
    """Small backup classifier for demos when FinBERT cannot load."""
    lowered = text.lower()
    risk_keywords = {
        keyword
        for keywords in config.RISK_DRIVERS.values()
        for keyword in keywords
    }
    negative_hits = sum(1 for keyword in risk_keywords if keyword in lowered)
    positive_hits = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in lowered)

    if negative_hits > positive_hits:
        return {"negative": 0.72, "neutral": 0.20, "positive": 0.08}
    if positive_hits > negative_hits:
        return {"positive": 0.70, "neutral": 0.22, "negative": 0.08}
    return {"neutral": 0.62, "negative": 0.23, "positive": 0.15}


def extract_risk_drivers(text: str) -> list[str]:
    """Keyword-match the headline against the ISA-315 risk lexicon."""
    t = text.lower()
    hits = [cat for cat, kws in config.RISK_DRIVERS.items()
            if any(kw in t for kw in kws)]
    return hits or ["Uncategorised"]


def score_headline(item: dict) -> dict:
    """
    Enrich one raw headline dict (from data_sources.poll_news) with NLP output.
    Adds: sentiment label, confidence, risk drivers, and an is_warning flag.
    """
    sent = analyze_sentiment(item["headline"])
    drivers = extract_risk_drivers(item["headline"])
    audit_reference = map_audit_reference(item["headline"], drivers)
    is_warning = (
        sent["label"] == config.RISK_LABEL
        and sent["score"] >= config.WARNING_THRESHOLD
    )
    return {
        **item,
        "sentiment": sent["label"],
        "confidence": round(sent["score"], 3),
        "risk_score": round(sent["scores"].get("negative", 0.0), 3),
        "risk_drivers": drivers,
        "is_warning": is_warning,
        **audit_reference,
    }
