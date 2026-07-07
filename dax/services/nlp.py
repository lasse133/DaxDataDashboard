"""Pretrained deep-learning NLP for the DAX 40 Audit Risk Radar.

Three transformer models, inference only:

    * Translation (DE -> EN):  Helsinki-NLP/opus-mt-de-en   (MarianMT, ~74M params)
    * Sentiment (EN):          ProsusAI/finbert             (BERT-base, ~110M)
    * Zero-shot topics (EN):   facebook/bart-large-mnli     (BART-large, ~406M)

Design notes
------------
* Models are loaded lazily via `get_pipeline(...)` and cached across calls.
  Streamlit callers should wrap that in `@st.cache_resource` (see app.py).
* Every function is a pure input -> output transformer. No global state
  beyond the model cache.
* `analyze(...)` is the single-headline pipeline the app calls in parallel
  via `concurrent.futures`. It returns a dict with all intermediate
  outputs so the UI can show WHY a headline was flagged, not just the label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from langdetect import DetectorFactory, LangDetectException, detect
from transformers import pipeline

# langdetect is nondeterministic by default — seed it so the same headline
# always yields the same language, which matters for audit reproducibility.
DetectorFactory.seed = 0


# ---------------------------------------------------------------------------
# Model registry — surfaced in the UI so auditors can see the exact stack.
# ---------------------------------------------------------------------------

MODELS = {
    "translate": {
        "task": "translation",
        "id": "Helsinki-NLP/opus-mt-de-en",
        "architecture": "MarianMT (Transformer seq2seq)",
        "params": "~74M",
        "purpose": "German -> English translation before downstream analysis",
    },
    "sentiment": {
        "task": "sentiment-analysis",
        "id": "ProsusAI/finbert",
        "architecture": "BERT-base",
        "params": "~110M",
        "purpose": "Finance-tuned sentiment (positive / negative / neutral)",
    },
    "topics": {
        "task": "zero-shot-classification",
        "id": "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
        "architecture": "DeBERTa-v3-base",
        "params": "~184M",
        "purpose": "Zero-shot classification against the ISA 315 topic catalog",
    },
}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def get_pipeline(kind: str):
    """Return a lazily-loaded HuggingFace pipeline. Cached for the process."""
    spec = MODELS[kind]
    return pipeline(task=spec["task"], model=spec["id"])


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str, hint: str = "") -> str:
    """Return 'en' or 'de'. Uses the provider hint when trustworthy, falls back
    to langdetect. Anything not confidently DE is treated as EN — the downstream
    models are English, so EN is the safe default.
    """
    hint = (hint or "").lower()[:2]
    if hint in {"en", "de"}:
        return hint
    if not text.strip():
        return "en"
    try:
        code = detect(text)
    except LangDetectException:
        return "en"
    return "de" if code == "de" else "en"


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def translate_de_to_en(text: str) -> str:
    if not text.strip():
        return text
    result = get_pipeline("translate")(text, max_length=256)
    # transformers returns [{'translation_text': '...'}]
    return result[0]["translation_text"]


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

@dataclass
class Sentiment:
    label: str    # 'positive' | 'negative' | 'neutral'
    score: float  # 0..1


def analyze_sentiment(text_en: str) -> Sentiment:
    result = get_pipeline("sentiment")(text_en, truncation=True)[0]
    return Sentiment(label=result["label"].lower(), score=float(result["score"]))


# ---------------------------------------------------------------------------
# Zero-shot topics
# ---------------------------------------------------------------------------

@dataclass
class TopicScores:
    """All labels the classifier saw, with their scores (sum ≈ 1 with
    multi_label=False; independent 0..1 with multi_label=True).

    `top` is a small (label, score) list for the UI.
    """
    scores: dict[str, float] = field(default_factory=dict)

    def top(self, k: int = 3) -> list[tuple[str, float]]:
        return sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)[:k]


def classify_topics(text_en: str, labels: list[str]) -> TopicScores:
    if not text_en.strip() or not labels:
        return TopicScores()
    # multi_label=True: each topic scored independently. Financial news often
    # spans multiple risk categories at once (e.g. "CFO resigns amid fraud
    # probe" = governance + fraud), so single-label softmax would be wrong.
    result = get_pipeline("topics")(text_en, candidate_labels=labels, multi_label=True)
    return TopicScores(scores=dict(zip(result["labels"], (float(s) for s in result["scores"]))))


# ---------------------------------------------------------------------------
# Full single-headline pipeline
# ---------------------------------------------------------------------------

@dataclass
class Analysis:
    """Everything the risk mapper and UI need for one headline."""
    language: str
    original: str
    english: str           # == original when language == 'en'
    sentiment: Sentiment
    topics: TopicScores

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "original": self.original,
            "english": self.english,
            "sentiment": {"label": self.sentiment.label, "score": self.sentiment.score},
            "topics": self.topics.scores,
        }


def analyze(text: str, topic_labels: list[str], language_hint: str = "") -> Analysis:
    """Run the full deep-learning pipeline on one headline title.

    This is what the app calls concurrently via ThreadPoolExecutor. The
    ordering (translate -> sentiment + topics) matters: FinBERT and BART-MNLI
    were trained on English.
    """
    lang = detect_language(text, hint=language_hint)
    english = translate_de_to_en(text) if lang == "de" else text
    return Analysis(
        language=lang,
        original=text,
        english=english,
        sentiment=analyze_sentiment(english),
        topics=classify_topics(english, topic_labels),
    )
