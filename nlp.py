"""
nlp.py
------
The "Process + Score" layer with universal namespace injection for Python 3.14.

  - analyze_sentiment(text)    -> FinBERT financial sentiment (positive/negative/neutral + confidence)
  - extract_risk_drivers(text) -> Advanced Zero-Shot Classification via BART model (no fallbacks)
  - score_headline(item)       -> combines both into one enriched record the UI can render
"""

from __future__ import annotations
import builtins
from functools import lru_cache
import os
import traceback
import torch
builtins.torch = torch  # Force inject torch into global builtins to resolve library NameErrors

import transformers
from transformers import pipeline

# Mute noisy Hugging Face internal deprecation warnings
transformers.logging.set_verbosity_error()

import config
from audit_references import map_audit_reference
from pathlib import Path

_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

HF_TOKEN = os.getenv("HF_TOKEN", None)
# =============================================================================
# 1. MODEL INITIALIZATION AND CACHING
# =============================================================================
@lru_cache(maxsize=1)
def _get_sentiment_model():
    """FinBERT for Positive/Negative Sentiment Analysis."""
    try:
        return pipeline(
            task="text-classification",
            model="ProsusAI/finbert",
            top_k=None,
            local_files_only=True
        )
    except Exception:
        return pipeline(
            task="text-classification",
            model="ProsusAI/finbert",
            api_key=HF_TOKEN,
            top_k=None
        )


@lru_cache(maxsize=1)
def _get_zeroshot_model():
    """BART Large MNLI model for Contextual Zero-Shot Risk Tagging."""
    try:
        return pipeline(
            task="zero-shot-classification",
            model="facebook/bart-large-mnli",
            api_key=HF_TOKEN,
            local_files_only=True
        )
    except Exception:
        return pipeline(
            task="zero-shot-classification",
            model="facebook/bart-large-mnli"
        )


# =============================================================================
# 2. SENTIMENT ENGINE
# =============================================================================
def analyze_sentiment(text: str) -> dict:
    """
    Return {"label": "negative", "score": 0.91, "scores": {pos,neg,neu}}.
    If the model fails, prints the exact error trace to the terminal window.
    """
    try:
        clf = _get_sentiment_model()
        raw = clf(text[:512])  # Enforcement of FinBERT token boundary sequence
        scores = {d["label"].lower(): float(d["score"]) for d in raw[0]}
        label = max(scores, key=scores.get)
        return {"label": label, "score": scores[label], "scores": scores}
    except Exception as e:
        print(f"\n--- [CRITICAL INFRASTRUCTURE ERROR: FinBERT SENTIMENT RUNTIME] ---")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")
        traceback.print_exc()
        print(f"-----------------------------------------------------------------\n")
        
        return {
            "label": "FinBERT Model Error",
            "score": 0.0,
            "scores": {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
        }


# =============================================================================
# 3. RISK CLASSIFICATION ENGINE
# =============================================================================
def extract_risk_drivers(text: str) -> list[str]:
    """
    Use a zero-shot model to classify text into structural ISA-315 risk buckets.
    If the model fails, prints the exact error trace to the terminal window.
    """
    try:
        classifier = _get_zeroshot_model()
        candidate_labels = list(config.RISK_DRIVERS.keys())

        result = classifier(text[:512], candidate_labels, multi_label=True)

        valid_risks = [
            label
            for label, score in zip(result["labels"], result["scores"])
            if score > 0.50
        ]
        return valid_risks if valid_risks else ["Uncategorised"]
    except Exception as e:
        print(f"\n--- [CRITICAL INFRASTRUCTURE ERROR: BART ZERO-SHOT RUNTIME] ---")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")
        traceback.print_exc()
        print(f"---------------------------------------------------------------\n")
        
        return ["BART Model Error"]


# =============================================================================
# 4. PIPELINE AGGREGATOR
# =============================================================================
def score_headline(item: dict) -> dict:
    """Enrich raw headline map structures with deep learning and compliance analytics."""
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