"""DAX40 Dashboard - Streamlit UI.

Presentation layer only. All I/O, deep learning, and rule evaluation live
under `services/`.

Streaming model
---------------
Streamlit is request/response, so we deliver "stream processing" as an
event-at-a-time pipeline. Rather than a ThreadPoolExecutor blocking the
script (which would ignore Pause clicks until it finishes), we process
ONE headline per script run and `st.rerun()` to loop:

    each rerun:
      if not paused and not done:
          process next queued headline (deep-learning pipeline)
          append result to session_state.results
          st.rerun()
      render current results table + risk chart

This gives us a genuinely pausable / resumable stream: the Pause button
is honored between iterations because the script yields between rows.

Deep learning
-------------
Three pretrained transformers (MarianMT translation, FinBERT sentiment,
DeBERTa-v3-MNLI zero-shot topics) - see `services/nlp.py::MODELS`.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from io import BytesIO
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services import news, nlp, prices, risk


# ---------------------------------------------------------------------------
# Page config + constants
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DAX40 Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
)

SEVERITY_COLORS = {"high": "#c0392b", "medium": "#e67e22", "low": "#f1c40f"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
NEGATIVE_ROW_BG = "background-color: #fdecea"  # light red for negative-sentiment rows
STOPWORDS = {
    "about", "after", "all", "also", "am", "amid", "an", "and", "are", "as",
    "auf", "aus", "bei", "bis", "but", "by", "das", "dem", "den", "der",
    "des", "die", "ein", "eine", "einer", "for", "from", "fur", "fuer",
    "has", "have", "im", "in", "into", "is", "ist", "it", "mit", "not",
    "of", "on", "or", "over", "sich", "sind", "that", "the", "this", "to",
    "und", "von", "war", "was", "were", "werden", "with", "zu", "zur",
    "aktie", "aktien", "analyst", "analysts", "boerse", "boerse", "buy",
    "chase", "finanzen", "google", "hold", "kurs", "kursziel", "market",
    "marketbeat", "morningstar", "news", "neutral", "price", "rating",
    "reuters", "sell", "share", "shares", "stock", "stocks", "target",
    "trading", "yahoo",
    "ag", "corp", "company", "group", "inc", "konzern", "plc", "se",
    "softwarekonzern",
}
RISK_DRIVER_TERMS = {
    "cybersecurity": [
        "cyber attack", "cybersecurity", "data breach", "ransomware",
        "security incident", "cloud outage", "it outage",
    ],
    "legal regulatory": [
        "lawsuit", "litigation", "regulatory investigation", "fine",
        "sanctions", "compliance issue", "antitrust", "tax investigation",
    ],
    "financial performance": [
        "profit warning", "guidance cut", "revenue decline", "margin pressure",
        "impairment", "loss", "liquidity", "covenant breach",
    ],
    "business model": [
        "restructuring", "acquisition", "merger", "divestment", "divestiture",
        "spin off", "job cuts", "cost cutting",
    ],
    "operations": [
        "supply chain", "production delay", "shortage", "disruption",
        "dependency", "plant closure",
    ],
}

st.markdown(
    """
    <style>
    .stApp {
        background: #f3f6f9;
        color: #14283d;
    }
    .stMainBlockContainer {
        padding-top: 1.4rem;
        padding-bottom: 3rem;
    }
    [data-testid="stSidebar"] {
        background: #0b2945;
        border-right: 3px solid #2a78ad;
        box-shadow: 8px 0 24px rgba(11, 41, 69, 0.10);
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
        color: #f8fafc;
    }
    [data-testid="stSidebar"] h1 {
        font-size: 1.45rem;
        line-height: 1.2;
        margin-bottom: 0.2rem;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        color: #b8cee0;
    }
    [data-testid="stSidebar"] hr {
        border-color: rgba(255, 255, 255, 0.12);
        margin: 1.25rem 0;
    }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-baseweb="input"] > div {
        background: #ffffff !important;
        border-color: transparent !important;
        border-radius: 6px;
    }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"],
    [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] *,
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"],
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"] *,
    [data-testid="stSidebar"] [data-baseweb="input"],
    [data-testid="stSidebar"] [data-baseweb="input"] * {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        caret-color: #000000 !important;
        text-shadow: none !important;
        opacity: 1 !important;
    }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] svg,
    [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] svg path,
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"] svg,
    [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"] svg path {
        color: #000000 !important;
        fill: #000000 !important;
    }
    [data-testid="stSidebar"] input::placeholder {
        color: #4b5563 !important;
        -webkit-text-fill-color: #4b5563 !important;
        opacity: 1 !important;
    }
    h2, h3 {
        color: #153b5c;
        letter-spacing: 0;
    }
    h2 {
        margin-top: 1.6rem;
        padding-bottom: 0.35rem;
        border-bottom: 1px solid #d7e1e9;
    }
    [data-testid="stButton"] > button {
        border-radius: 6px;
        border: 1px solid #1d6697;
        font-weight: 700;
        min-height: 2.65rem;
        transition: background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
    }
    [data-testid="stButton"] > button[kind="primary"] {
        background: #e94f55;
        border-color: #e94f55;
        color: #ffffff;
        box-shadow: 0 6px 16px rgba(197, 48, 56, 0.20);
    }
    [data-testid="stButton"] > button[kind="primary"]:hover {
        background: #cf3e45;
        border-color: #cf3e45;
    }
    [data-testid="stTextInput"] input,
    [data-testid="stDateInput"] input {
        border-radius: 6px;
    }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #d7e1e9;
        border-top: 3px solid #2a78ad;
        border-radius: 6px;
        padding: 13px 15px;
        box-shadow: 0 5px 14px rgba(15, 39, 66, 0.06);
    }
    [data-testid="stMetricLabel"] {
        color: #587086;
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        color: #112f4a;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid #cfdbe5;
        border-radius: 6px;
        overflow: hidden;
        box-shadow: 0 6px 18px rgba(15, 39, 66, 0.06);
    }
    [data-testid="stExpander"] {
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid #d7e1e9;
        border-radius: 6px;
    }
    .finance-hero {
        background: #103a5d;
        border-left: 5px solid #42a8b5;
        border-radius: 6px;
        padding: 22px 26px;
        color: #ffffff;
        margin: 0.25rem 0 1.25rem 0;
        box-shadow: 0 10px 28px rgba(15, 39, 66, 0.16);
    }
    .finance-hero h1 {
        color: #ffffff;
        font-size: 2rem;
        line-height: 1.12;
        margin: 0 0 0.35rem 0;
        letter-spacing: 0;
    }
    .finance-hero p {
        color: #dcecff;
        margin: 0;
        font-size: 0.98rem;
    }
    .hero-kicker {
        color: #8ed8df;
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.4rem;
    }
    .section-label {
        color: #0f2742;
        font-weight: 700;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        font-size: 0.78rem;
    }
    [data-testid="stProgress"] > div > div {
        background-color: #2a78ad;
    }
    [data-testid="stAlert"] {
        border-radius: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Loading deep-learning models (first run only)...")
def load_models() -> dict[str, Any]:
    return {
        "translate": nlp.get_pipeline("translate"),
        "sentiment": nlp.get_pipeline("sentiment"),
        "topics": nlp.get_pipeline("topics"),
    }


@st.cache_data(show_spinner="Fetching news from GDELT + Google (rate-limited)...")
def cached_headlines(
    ticker: str, year: int, quarters: tuple[int, ...], nonce: int
) -> tuple[list[dict], list[dict]]:
    """Fetch headlines across one or more quarters within a single year.

    `quarters` is a sorted tuple so the cache key is stable regardless of
    the multiselect widget's return order.
    """
    diagnostics: list[news.FetchReport] = []
    hls = news.fetch_headlines_multi(
        ticker, year, quarters, diagnostics=diagnostics
    )

    def _quarter_of(ts_iso: str) -> str:
        """Bucket a headline's timestamp into one of the selected quarters."""
        ts = datetime.fromisoformat(ts_iso)
        q = (ts.month - 1) // 3 + 1
        return f"Q{q} {ts.year}"

    all_headlines = [
        {
            "title": h.title,
            "url": h.url,
            "source": h.source,
            "provider": h.provider,
            "published_at": h.published_at.isoformat(),
            "language_hint": h.language_hint,
            "quarter": _quarter_of(h.published_at.isoformat()),
        }
        for h in hls
    ]
    diag_dicts = [
        {
            "provider": d.provider,
            "ok": d.ok,
            "n_raw": d.n_raw,
            "n_after_filter": d.n_after_filter,
            "error": d.error,
            "http_status": d.http_status,
        }
        for d in diagnostics
    ]
    return all_headlines, diag_dicts


@st.cache_data(show_spinner="Fetching current Google News headlines...")
def cached_current_headlines(
    ticker: str, days: int, nonce: int
) -> tuple[list[dict], list[dict]]:
    diagnostics: list[news.FetchReport] = []
    hls = news.fetch_current_headlines(
        ticker,
        days=days,
        include_company_channels=False,
        diagnostics=diagnostics,
    )
    headlines = [
        {
            "title": h.title,
            "url": h.url,
            "source": h.source,
            "provider": h.provider,
            "published_at": h.published_at.isoformat(),
            "language_hint": h.language_hint,
        }
        for h in hls
    ]
    diag_dicts = [
        {
            "provider": d.provider,
            "ok": d.ok,
            "n_raw": d.n_raw,
            "n_after_filter": d.n_after_filter,
            "error": d.error,
            "http_status": d.http_status,
        }
        for d in diagnostics
    ]
    return headlines, diag_dicts


@st.cache_data(show_spinner="Fetching company channel headlines...")
def cached_company_channel_headlines(
    ticker: str, days: int, nonce: int
) -> tuple[list[dict], list[dict]]:
    diagnostics: list[news.FetchReport] = []
    hls = news.fetch_company_channel_headlines(
        ticker,
        days=days,
        diagnostics=diagnostics,
    )
    headlines = [
        {
            "title": h.title,
            "url": h.url,
            "source": h.source,
            "provider": h.provider,
            "published_at": h.published_at.isoformat(),
            "language_hint": h.language_hint,
        }
        for h in hls
    ]
    diag_dicts = [
        {
            "provider": d.provider,
            "ok": d.ok,
            "n_raw": d.n_raw,
            "n_after_filter": d.n_after_filter,
            "error": d.error,
            "http_status": d.http_status,
        }
        for d in diagnostics
    ]
    return headlines, diag_dicts


@st.cache_data(show_spinner=False)
def cached_prices(
    ticker: str, year: int, quarters: tuple[int, ...], nonce: int
) -> pd.DataFrame:
    """Concatenate daily OHLC across the selected quarters within one year."""
    frames = []
    for q in quarters:
        df = prices.fetch_prices(ticker, news.Quarter(year=year, q=q))
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()


@st.cache_data(show_spinner=False)
def cached_prices_range(
    ticker: str, start: date, end: date, nonce: int
) -> pd.DataFrame:
    return prices.fetch_prices_range(ticker, start, end)


@st.cache_data(show_spinner=False)
def cached_analyze(title: str, language_hint: str, topics_key: str) -> dict:
    """Per-headline NLP cache."""
    
    # --- Data Cleaning Step ---
    # Strip the publisher name from the end of the Google News headline
    if " - " in title:
        clean_title = title.rsplit(" - ", 1)[0].strip()
    else:
        clean_title = title
    # --------------------------

    labels = risk.classification_topic_labels()
    
    # Pass the clean_title to the AI models instead of the raw title
    analysis = nlp.analyze(clean_title, topic_labels=labels, language_hint=language_hint)
    
    return analysis.as_dict()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_year_and_quarter() -> tuple[int, int]:
    today = datetime.now(timezone.utc)
    return today.year, (today.month - 1) // 3 + 1


def _rebuild_analysis(d: dict) -> nlp.Analysis:
    return nlp.Analysis(
        language=d["language"],
        original=d["original"],
        english=d["english"],
        sentiment=nlp.Sentiment(label=d["sentiment"]["label"], score=d["sentiment"]["score"]),
        topics=nlp.TopicScores(scores=d["topics"]),
    )


def _reset_pipeline(headline_dicts: list[dict]) -> None:
    """Prime the streaming state for a fresh pipeline run."""
    st.session_state.queue = list(headline_dicts)
    st.session_state.results = []
    st.session_state.paused = False
    st.session_state.pipeline_signature = _signature(headline_dicts)


def _signature(headlines: list[dict]) -> str:
    """A stable fingerprint of the queue used to detect input changes."""
    headline_signature = "|".join(h["url"] or h["title"] for h in headlines)
    rule_version = getattr(risk, "RISK_RULE_VERSION", "original-v2")
    return f"{rule_version}|{headline_signature}"


def _results_dataframe(results: list[dict]) -> pd.DataFrame:
    """Build a display dataframe from processed results."""
    rows = []
    for r in results:
        h, a, flags = r["headline"], r["analysis"], r["flags"]
        top_topic, top_score = ("No strong match", 0.0)
        if a["topics"]:
            top_topic, top_score = max(a["topics"].items(), key=lambda kv: kv[1])
        rows.append(
            {
                "Date": h["published_at"][:10],
                "Quarter": h.get("quarter", ""),
                "Sentiment": f"{a['sentiment']['label']} ({a['sentiment']['score']:.2f})",
                "_sentiment_label": a["sentiment"]["label"],
                "Highest topic signal": f"{top_topic} ({top_score:.2f})",
                "Triggered rules": ", ".join(flag.rule_id for flag in flags) or "No rule triggered",
                "Headline": h["title"],
                "Source": h.get("source") or h["provider"],
                "URL": h["url"],
            }
        )
    return pd.DataFrame(rows)


def _style_results(df: pd.DataFrame):
    """Highlight rows with negative sentiment in light red."""
    sentiment_by_index = df["_sentiment_label"].to_dict()
    display_df = df.drop(columns=["_sentiment_label"])

    def _highlight(row: pd.Series) -> list[str]:
        if sentiment_by_index.get(row.name) == "negative":
            return [NEGATIVE_ROW_BG] * len(row)
        return [""] * len(row)

    return display_df.style.apply(_highlight, axis=1)


def _headline_dataframe(headlines: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": h["published_at"][:10],
                "Source": h.get("source") or h.get("provider", ""),
                "Headline": h["title"],
                "URL": h["url"],
            }
            for h in headlines
        ]
    )


def _filter_headlines(headlines: list[dict], query: str) -> list[dict]:
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return headlines
    return [
        h for h in headlines
        if all(term in h["title"].lower() for term in terms)
    ]


def _clean_term_text(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r"http\S+|www\S+", " ", text)
    text = re.sub(r"[^a-zA-ZA-Za-z\- ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _company_stopwords(company: dict, ticker: str) -> set[str]:
    words: set[str] = set()
    words.update(_clean_term_text(company.get("name", "")).split())
    for alias in company.get("aliases", []):
        words.update(_clean_term_text(alias).split())
        words.add(_clean_term_text(alias).replace(" ", "-"))
    ticker_clean = ticker.lower().replace(".de", "").replace(".", "")
    words.update({ticker.lower(), ticker_clean})
    return {w for w in words if w}


def _risk_lexicon_terms() -> set[str]:
    terms: set[str] = set()
    for rule in risk.load_rules():
        triggers = rule.get("triggers", {})
        terms.update(str(t).lower() for t in triggers.get("topics", []))
        terms.update(str(k).lower() for k in triggers.get("keywords", []))
    for phrases in RISK_DRIVER_TERMS.values():
        terms.update(phrase.lower() for phrase in phrases)
    return terms


def _ngrams(tokens: list[str], max_n: int = 3) -> set[str]:
    grams: set[str] = set()
    for n in range(1, max_n + 1):
        for i in range(0, len(tokens) - n + 1):
            grams.add(" ".join(tokens[i:i + n]))
    return grams


def _top_terms(
    headlines: list[dict],
    company: dict,
    ticker: str,
    limit: int = 15,
) -> pd.DataFrame:
    """Return TF-IDF weighted, audit-risk-focused headline terms.

    This intentionally does not count raw source names or stock-market
    boilerplate. It extracts 1-3 word phrases from headline/snippet text,
    removes company/ticker noise, and boosts terms from the ISA-style risk
    lexicon.
    """
    company_noise = _company_stopwords(company, ticker)
    stopwords = STOPWORDS | company_noise
    docs: list[list[str]] = []
    seen_texts: set[str] = set()

    for h in headlines:
        text = _clean_term_text(f"{h.get('title', '')} {h.get('snippet', '')}")
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        tokens = [
            token
            for token in text.split()
            if len(token) > 2 and token not in stopwords and not token.isnumeric()
        ]
        if tokens:
            docs.append(tokens)

    if not docs:
        return pd.DataFrame(columns=["Term", "Score"])

    doc_terms = [_ngrams(tokens) for tokens in docs]
    document_frequency = Counter(term for terms in doc_terms for term in terms)
    risk_terms = _risk_lexicon_terms()
    total_docs = len(doc_terms)
    scores: Counter[str] = Counter()

    for terms in doc_terms:
        term_frequency = Counter(terms)
        for term, tf in term_frequency.items():
            if any(part in stopwords for part in term.split()):
                continue
            idf = math.log((1 + total_docs) / (1 + document_frequency[term])) + 1
            weight = tf * idf
            if term in risk_terms:
                weight *= 3.0
            elif any(risk_term in term or term in risk_term for risk_term in risk_terms):
                weight *= 1.8
            scores[term] += weight

    full_text = " ".join(" ".join(tokens) for tokens in docs)
    for phrase in risk_terms:
        if " " in phrase and phrase in full_text:
            scores[phrase] += full_text.count(phrase) * 3.0

    cleaned_scores = {
        term: score
        for term, score in scores.items()
        if len(term) > 3
        and not term.isnumeric()
        and not any(part in stopwords for part in term.split())
    }
    top = sorted(cleaned_scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    return pd.DataFrame(top, columns=["Term", "Score"])


def _report_pdf_bytes(
    company: dict,
    period_label: str,
    summary: dict,
    results: list[dict],
) -> bytes:
    """Create a headline-level PDF workpaper from processed reporting results."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleNavy",
        parent=styles["Title"],
        textColor=colors.HexColor("#0f2742"),
        spaceAfter=12,
    )
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=10)
    story = [
        Paragraph("DAX40 Dashboard", title_style),
        Paragraph(f"{company['name']} ({company['ticker']}) - {period_label}", body),
        Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", body),
        Spacer(1, 0.35 * cm),
        Paragraph(
            "This export is based on fetched headlines and model/rule outputs. "
            "It does not summarize full article bodies and does not perform an ISA 315 risk assessment.",
            body,
        ),
        Spacer(1, 0.35 * cm),
    ]

    if summary:
        story.extend(
            [
                Paragraph("Price Summary", styles["Heading2"]),
                Paragraph(
                    f"Last close EUR {summary['last_close']:.2f}; period return "
                    f"{summary['period_return_pct']:+.2f}%; high {summary['period_high']:.2f}; "
                    f"low {summary['period_low']:.2f}; trading days {summary['trading_days']}.",
                    body,
                ),
                Spacer(1, 0.3 * cm),
            ]
        )

    rows = [["Date", "Sentiment", "Highest topic signal", "Triggered rules", "Headline"]]
    for r in results:
        h = r["headline"]
        a = r["analysis"]
        flags = ", ".join(flag.rule_id for flag in r["flags"]) or "No rule triggered"
        top_topic, top_score = ("No strong match", 0.0)
        if a["topics"]:
            top_topic, top_score = max(a["topics"].items(), key=lambda item: item[1])
        rows.append(
            [
                h["published_at"][:10],
                f"{a['sentiment']['label']} ({a['sentiment']['score']:.2f})",
                f"{top_topic} ({top_score:.2f})",
                flags,
                Paragraph(h["title"], small),
            ]
        )

    table = Table(rows, repeatRows=1, colWidths=[1.7 * cm, 2.3 * cm, 3.2 * cm, 2.8 * cm, 7.2 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f2742")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e2ec")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faff")]),
            ]
        )
    )
    story.extend([Paragraph("Processed Headlines", styles["Heading2"]), table])
    doc.build(story)
    return buffer.getvalue()


def _rules_dataframe() -> pd.DataFrame:
    """Flatten the ISA 315 rule catalog (isa315_map.yaml) for display."""
    rows = []
    for rule in risk.load_rules():
        triggers = rule.get("triggers", {})
        gate = "-"
        if "sentiment" in triggers:
            threshold = float(triggers.get("sentiment_threshold", 0.5))
            gate = f"{triggers['sentiment']} >= {threshold:.2f}"
        audit_ref = rule.get("audit_ref", {})
        rows.append(
            {
                "Rule": rule["id"],
                "Category": rule["category"],
                "Severity": rule["severity"],
                "Trigger topics (any one suffices)": ", ".join(triggers.get("topics", [])),
                "Sentiment gate": gate,
                "ISA": ", ".join(audit_ref.get("isa", [])),
                "IDW": ", ".join(audit_ref.get("idw", [])),
            }
        )
    return pd.DataFrame(rows)


def _render_how_it_works() -> None:
    """Collapsible primer: pipeline explanation + the live rule catalog."""
    with st.expander("How this report works | ISA 315 rule catalog", expanded=False):
        st.markdown(
            f"""
**From headline to risk flag, in four steps:**

1. **Fetch** - headlines mentioning the company are pulled from GDELT and
   Google News RSS for the selected period, deduplicated, and filtered to
   titles that actually name the company.
2. **Deep learning** - each headline is language-detected (German is
   translated to English), scored for financial sentiment by FinBERT, and
   scored against every configured topic by a zero-shot classifier.
3. **Rule evaluation** - a rule fires when a configured topic scores >=
   **{risk.DEFAULT_TOPIC_THRESHOLD:.2f}** and any configured sentiment gate also
   matches. One headline can fire several rules.
4. **Report** - flags are aggregated by category and severity into the risk
   radar, and every flagged headline links back to the ISA / IDW references
   and suggested procedures of the rule that fired.

The catalog below is read live from `domain/isa315_map.yaml` - rules are data,
not code, so they can be reviewed and edited without touching the app.
Severity is fixed per rule: **high** = red, **medium** = orange, **low** = yellow.
"""
        )

        st.dataframe(
            _rules_dataframe().style.map(
                lambda s: f"background-color: {SEVERITY_COLORS.get(s, '#999')}; color: white",
                subset=["Severity"],
            ),
            width="stretch",
            hide_index=True,
        )

        rules = risk.load_rules()
        selected_id = st.selectbox(
            "Inspect a rule",
            options=[r["id"] for r in rules],
            format_func=lambda rid: next(
                f"{r['id']} | {r['category']}" for r in rules if r["id"] == rid
            ),
        )
        rule = next(r for r in rules if r["id"] == selected_id)
        st.markdown(f"> {rule.get('description', '').strip()}")
        st.markdown("**Suggested procedures**")
        for p in rule.get("procedures", []):
            st.write(f"| {p}")

        st.caption(
            "The flags support the auditor's professional judgment - they do not "
            "perform the ISA 315 risk assessment. Every flag requires human review."
        )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.session_state.setdefault("refresh_nonce", 0)
st.session_state.setdefault("current_news_nonce", 0)
st.session_state.setdefault("company_news_nonce", 0)
st.session_state.setdefault("queue", [])
st.session_state.setdefault("results", [])
st.session_state.setdefault("paused", False)
st.session_state.setdefault("pipeline_signature", "")

with st.sidebar:
    st.title("DAX40 Dashboard")
    st.caption("DAX 40 | ISA 315 support tool")

    companies = news.load_companies()
    ticker_options = [c["ticker"] for c in companies]
    default_ticker_idx = ticker_options.index("SAP.DE") if "SAP.DE" in ticker_options else 0
    ticker = st.selectbox(
        "Company",
        options=ticker_options,
        format_func=lambda t: f"{next(c['name'] for c in companies if c['ticker'] == t)} ({t})",
        index=default_ticker_idx,
    )

    workspace = "Reporting period"

    # --- Workspace-specific controls ---------------------------------------
    cur_year, cur_q = _current_year_and_quarter()
    if workspace == "Reporting period":
        year_options = list(range(cur_year, cur_year - 5, -1))  # last 5 years, newest first
        year = st.selectbox("Year", options=year_options, index=0)

        quarter_choice = st.multiselect(
            "Reporting period (one or more quarters)",
            options=["Q1", "Q2", "Q3", "Q4"],
            default=[f"Q{cur_q}"] if year == cur_year else ["Q1", "Q2", "Q3", "Q4"],
            help="Select the quarters within the chosen year to investigate.",
        )
        quarters: tuple[int, ...] = tuple(sorted(int(q[1:]) for q in quarter_choice))
        period_label = f"{', '.join(quarter_choice) or '-'} {year}"

        st.markdown("**Stock price window**")
        price_window_mode = st.radio(
            "Price range",
            options=["Year to date", "Custom"],
            horizontal=True,
            label_visibility="collapsed",
        )
        today = datetime.now(timezone.utc).date()
        ytd_start = date(today.year, 1, 1)
        if price_window_mode == "Year to date":
            price_start = ytd_start
            price_end = today
            st.caption(f"YTD: {price_start.isoformat()} to {price_end.isoformat()}")
        else:
            selected_range = st.date_input(
                "Custom stock price range",
                value=(ytd_start, today),
                min_value=date(today.year - 10, 1, 1),
                max_value=today,
            )
            if isinstance(selected_range, tuple) and len(selected_range) == 2:
                price_start, price_end = selected_range
            else:
                price_start, price_end = ytd_start, today

        st.divider()
        refresh_clicked = st.button(
            "Fetch latest data", type="primary", width="stretch",
            disabled=not quarters,
        )
        if refresh_clicked:
            st.session_state.refresh_nonce += 1
            cached_analyze.clear()
            cached_headlines.clear()
            cached_prices.clear()
            # Force pipeline to rebuild on next run.
            st.session_state.pipeline_signature = ""
    st.divider()
    with st.expander("Deep-learning stack", expanded=False):
        for _kind, spec in nlp.MODELS.items():
            st.markdown(
                f"**{spec['task']}**  \n"
                f"`{spec['id']}`  \n"
                f"{spec['architecture']} | {spec['params']}  \n"
                f"_{spec['purpose']}_"
            )

    st.caption(
        "This tool **supports** the auditor's professional judgment. "
        "It does not perform ISA 315 risk assessment."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

company = news.get_company(ticker)

def _render_lightweight_news_workspace(
    *,
    title: str,
    kicker: str,
    caption: str,
    headlines: list[dict],
    diagnostics: list[dict],
    search_placeholder: str,
    metric_label: str,
) -> None:
    st.markdown(
        f"""
        <div class="finance-hero">
            <div class="hero-kicker">{kicker}</div>
            <h1>{company['name']}</h1>
            <p>{caption}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(f"{title} diagnostics", expanded=not headlines):
        for d in diagnostics:
            status = "OK" if d["ok"] else "ERROR"
            st.write(
                f"{status} **{d['provider']}** | "
                f"raw={d['n_raw']} | after filter={d['n_after_filter']}"
            )
            if d["error"]:
                st.code(d["error"], language="text")

    if not headlines:
        st.warning(f"No {title.lower()} headlines found for this company and window.")
        st.stop()

    search_query = st.text_input(
        "Search within fetched headlines",
        placeholder=search_placeholder,
    )
    filtered_headlines = _filter_headlines(headlines, search_query)

    metric_cols = st.columns(3)
    metric_cols[0].metric(metric_label, len(headlines))
    metric_cols[1].metric("Visible after search", len(filtered_headlines))
    metric_cols[2].metric("Sources", len({h.get("source") or h.get("provider", "") for h in headlines}))

    st.subheader("News | Deep-learning risk pipeline")
    if not filtered_headlines:
        st.info("No fetched headlines match the current search.")
        st.stop()

    processed_results = []
    with st.spinner("Analyzing filtered headlines..."):
        for headline in filtered_headlines:
            analysis_dict = cached_analyze(
                title=headline["title"],
                language_hint=headline.get("language_hint", ""),
                topics_key="v4",
            )
            analysis = _rebuild_analysis(analysis_dict)
            processed_results.append(
                {
                    "headline": headline,
                    "analysis": analysis_dict,
                    "flags": risk.evaluate(analysis),
                }
            )

    current_df = _results_dataframe(processed_results)
    st.dataframe(
        _style_results(current_df),
        width="stretch",
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("Link", width="small"),
            "Headline": st.column_config.TextColumn("Headline", width="large"),
            "Highest topic signal": st.column_config.TextColumn(
                "Highest topic signal",
                help="The zero-shot classifier's highest-scoring configured topic; this is a model signal, not a confirmed classification.",
            ),
            "Triggered rules": st.column_config.TextColumn(
                "Triggered rules",
                help="Rule IDs whose topic threshold and optional sentiment requirements were met.",
            ),
        },
    )
    st.caption(
        "This screen is for fast monitoring. The reporting-period workspace is "
        "the audit workpaper view with model scoring and risk flags."
    )
    st.stop()


if not quarters:
    st.warning("Select at least one quarter in the sidebar.")
    st.stop()

st.markdown(
    f"""
    <div class="finance-hero">
        <div class="hero-kicker">Reporting period risk workpaper</div>
        <h1>{company['name']}</h1>
        <p>Sector: {company['sector']} | Ticker: {ticker} | Audit window: {period_label}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

_render_how_it_works()

load_models()

# --- Price panel ------------------------------------------------------------

price_df = cached_prices_range(
    ticker,
    price_start,
    price_end,
    st.session_state.refresh_nonce,
)
summary = prices.summarize(price_df)

kpi_cols = st.columns(4)
if summary:
    kpi_cols[0].metric(
        "Last close (EUR)", f"{summary['last_close']:.2f}",
        delta=f"{summary['period_return_pct']:+.2f}% ({price_start:%d.%m.%Y} - {price_end:%d.%m.%Y})",
    )
    kpi_cols[1].metric("Period high", f"{summary['period_high']:.2f}")
    kpi_cols[2].metric("Period low", f"{summary['period_low']:.2f}")
    kpi_cols[3].metric("Trading days", summary["trading_days"])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=price_df.index,
            y=price_df["Close"],
            mode="lines",
            name="Close",
            line=dict(color="#1f5f99", width=3),
            fill="tozeroy",
            fillcolor="rgba(31, 95, 153, 0.10)",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=32, b=0),
        height=310,
        title=f"Share price context | {price_start:%d %b %Y} to {price_end:%d %b %Y}",
        showlegend=False,
        xaxis_title=None,
        yaxis_title="EUR",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")
else:
    st.info("No price data returned for this ticker / period.")

st.divider()

# --- News pipeline ----------------------------------------------------------

st.subheader("News | Deep-learning risk pipeline")

headline_dicts, fetch_diagnostics = cached_headlines(
    ticker, year, quarters, st.session_state.refresh_nonce
)

with st.expander("News fetch diagnostics", expanded=not headline_dicts):
    if not fetch_diagnostics:
        st.write("No diagnostics recorded.")
    else:
        for d in fetch_diagnostics:
            status = "OK" if d["ok"] else "ERROR"
            http = f" (HTTP {d['http_status']})" if d["http_status"] else ""
            st.write(
                f"{status} **{d['provider']}**{http} | "
                f"raw={d['n_raw']} | after filter={d['n_after_filter']}"
            )
            if d["error"]:
                st.code(d["error"], language="text")

if not headline_dicts:
    temporary_outage = any(
        d.get("http_status") in {429, 503}
        or "rate-limit" in d.get("error", "").lower()
        or "temporarily" in d.get("error", "").lower()
        for d in fetch_diagnostics
    )
    if temporary_outage:
        st.warning(
            "The free news sources are temporarily throttling requests for this "
            "company change. Wait about one minute, then click **Fetch latest data** "
            "again. The price panel still works independently."
        )
    else:
        st.warning(
            "No headlines found. Common causes: (1) free sources returned nothing for "
            "the date range, (2) none of the returned articles mentioned the company "
            "by name, (3) network / rate-limit failure - see diagnostics above."
        )
    st.stop()

st.caption(f"Fetched **{len(headline_dicts)}** unique headline(s) mentioning **{company['name']}**.")

reporting_search_query = st.text_input(
    "Search within fetched headlines",
    placeholder="e.g. cloud, lawsuit, guidance, acquisition",
)
headline_dicts = _filter_headlines(headline_dicts, reporting_search_query)
if not headline_dicts:
    st.info("No fetched headlines match the current search.")
    st.stop()

# --- Pipeline state initialization -----------------------------------------
# If the fetched headline set changed (new refresh, new ticker/period), reset
# the streaming queue. Otherwise keep the running state so pause survives reruns.
current_signature = _signature(headline_dicts)
if st.session_state.pipeline_signature != current_signature:
    _reset_pipeline(headline_dicts)

# --- Pause / Resume controls -----------------------------------------------
total = len(headline_dicts)
done = len(st.session_state.results)
remaining = len(st.session_state.queue)
is_paused = st.session_state.paused
is_finished = remaining == 0

ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 3])
if is_finished:
    ctrl1.button("Pause", disabled=True, width="stretch")
    ctrl2.button("Resume", disabled=True, width="stretch")
elif is_paused:
    ctrl1.button("Pause", disabled=True, width="stretch")
    if ctrl2.button("Resume", type="primary", width="stretch"):
        st.session_state.paused = False
        st.rerun()
else:
    if ctrl1.button("Pause", width="stretch"):
        st.session_state.paused = True
        st.rerun()
    ctrl2.button("Resume", disabled=True, width="stretch")

if ctrl3.button("Reset", width="stretch", disabled=not (done or is_paused)):
    _reset_pipeline(headline_dicts)
    st.rerun()

status_text = (
    f"**{done}/{total}** processed"
    + (" | **paused**" if is_paused and not is_finished else "")
    + (" | OK complete" if is_finished else "")
)
ctrl4.markdown(status_text)

progress_val = done / total if total else 1.0
st.progress(progress_val)

# --- Table (real dataframe, styled) ----------------------------------------
table_placeholder = st.empty()
if st.session_state.results:
    df = _results_dataframe(st.session_state.results)
    table_placeholder.dataframe(
        _style_results(df),
        width="stretch",
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("Link", width="small"),
            "Headline": st.column_config.TextColumn("Headline", width="large"),
            "Highest topic signal": st.column_config.TextColumn(
                "Highest topic signal",
                help="The zero-shot classifier's highest-scoring configured topic; this is a model signal, not a confirmed classification.",
            ),
            "Triggered rules": st.column_config.TextColumn(
                "Triggered rules",
                help="Rule IDs whose topic threshold and optional sentiment requirements were met.",
            ),
        },
    )
else:
    table_placeholder.info("No headlines processed yet. Click **Resume** or wait for the pipeline to start.")

# --- Step ONE headline per rerun, then loop --------------------------------
if not is_finished and not is_paused:
    next_h = st.session_state.queue.pop(0)
    analysis_dict = cached_analyze(
        title=next_h["title"],
        language_hint=next_h.get("language_hint", ""),
        topics_key="v4",
    )
    analysis = _rebuild_analysis(analysis_dict)
    flags = risk.evaluate(analysis)
    st.session_state.results.append(
        {"headline": next_h, "analysis": analysis_dict, "flags": flags}
    )
    # Tiny sleep so a pause click at just the wrong instant has a chance
    # to register - costs almost nothing on total wall-clock time.
    time.sleep(0.05)
    st.rerun()

# ---------------------------------------------------------------------------
# Post-pipeline sections (only when we have results to show)
# ---------------------------------------------------------------------------

results = st.session_state.results
if not results:
    st.stop()

# ---- Risk radar chart ------------------------------------------------------

st.divider()
st.subheader("Risk radar | aggregated flags")

flag_rows: list[dict] = []
for r in results:
    for f in r["flags"]:
        flag_rows.append({
            "rule_id": f.rule_id,
            "category": f.category,
            "severity": f.severity,
            "headline": r["headline"]["title"],
            "url": r["headline"]["url"],
            "published_at": r["headline"]["published_at"],
            "quarter": r["headline"].get("quarter", ""),
        })

if not flag_rows:
    st.info("No rules fired for this period. Nothing warrants investigation from these headlines.")
else:
    flags_df = pd.DataFrame(flag_rows)
    agg = (
        flags_df.groupby(["category", "severity"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    fig_bar = px.bar(
        agg,
        x="count", y="category", color="severity", orientation="h",
        color_discrete_map=SEVERITY_COLORS,
        category_orders={"severity": ["high", "medium", "low"]},
        title="Flags by ISA 315 category",
    )
    fig_bar.update_layout(height=350, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig_bar, width="stretch")

    # ---- Drill-down per flag -----------------------------------------------
    st.markdown("### Flagged headlines | audit references and procedures")
    ordered = sorted(
        [(r, f) for r in results for f in r["flags"]],
        key=lambda pair: SEVERITY_ORDER.get(pair[1].severity, 99),
    )
    for r, f in ordered:
        h = r["headline"]
        a = r["analysis"]
        color = SEVERITY_COLORS[f.severity]
        with st.expander(
            f"[{f.severity.upper()}] {f.rule_id} | {f.category}  -  {h['title'][:100]}",
            expanded=False,
        ):
            st.markdown(
                f"<span style='background:{color};color:white;padding:2px 8px;"
                f"border-radius:6px'>{f.severity.upper()}</span>  "
                f"**{f.rule_id} - {f.category}**",
                unsafe_allow_html=True,
            )
            st.markdown(f"> {f.description}")

            cols = st.columns(2)
            with cols[0]:
                st.markdown("**Deep-learning signals**")
                st.write(f"Language detected: `{a['language']}`")
                if a["language"] == "de":
                    st.caption(f"Translated: {a['english']}")
                st.write(f"Sentiment: **{a['sentiment']['label']}** ({a['sentiment']['score']:.3f})")
                st.write("Matched topics (score >= threshold):")
                for topic, score in f.matched_topics:
                    st.write(f"  | {topic} - {score:.3f}")
            with cols[1]:
                st.markdown("**Audit references**")
                for std in f.audit_ref.get("isa", []):
                    st.write(f"| ISA: {std}")
                for std in f.audit_ref.get("idw", []):
                    st.write(f"| IDW: {std}")
                st.markdown("**Suggested procedures**")
                for p in f.procedures:
                    st.write(f"| {p}")
            st.markdown(f"[Open source article]({h['url']})")

# ---- Snapshot export -------------------------------------------------------

st.divider()
st.subheader("Workpaper snapshot")

snapshot = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "company": company,
    "year": year,
    "quarters": list(quarters),
    "period_label": period_label,
    "price_summary": summary,
    "models": nlp.MODELS,
    "headlines": [
        {
            **r["headline"],
            "analysis": r["analysis"],
            "flags": [
                {
                    "rule_id": f.rule_id,
                    "category": f.category,
                    "severity": f.severity,
                    "matched_topics": [
                        {"topic": topic, "score": score}
                        for topic, score in f.matched_topics
                    ],
                    "audit_ref": f.audit_ref,
                }
                for f in r["flags"]
            ],
        }
        for r in results
    ],
}
st.download_button(
    "Download JSON snapshot",
    data=json.dumps(snapshot, indent=2, default=str),
    file_name=f"{ticker}_{year}_{'-'.join(f'Q{q}' for q in quarters)}_snapshot.json",
    mime="application/json",
    width="stretch",
)

pdf_bytes = _report_pdf_bytes(company, period_label, summary, results)
st.download_button(
    "Download PDF workpaper",
    data=pdf_bytes,
    file_name=f"{ticker}_{year}_{'-'.join(f'Q{q}' for q in quarters)}_workpaper.pdf",
    mime="application/pdf",
    width="stretch",
)

