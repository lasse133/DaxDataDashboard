"""DAX 40 Audit Risk Radar — Streamlit UI.

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
DeBERTa-v3-MNLI zero-shot topics) — see `services/nlp.py::MODELS`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services import news, nlp, prices, risk


# ---------------------------------------------------------------------------
# Page config + constants
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DAX 40 Audit Risk Radar",
    page_icon="📊",
    layout="wide",
)

SEVERITY_COLORS = {"high": "#c0392b", "medium": "#e67e22", "low": "#f1c40f"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
NEGATIVE_ROW_BG = "background-color: #fdecea"  # light red for negative-sentiment rows


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
def cached_analyze(title: str, language_hint: str, topics_key: str) -> dict:
    """Per-headline NLP cache."""
    labels = risk.all_topic_labels()
    analysis = nlp.analyze(title, topic_labels=labels, language_hint=language_hint)
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
    return "|".join(h["url"] or h["title"] for h in headlines)


def _results_dataframe(results: list[dict]) -> pd.DataFrame:
    """Build a display dataframe from processed results."""
    rows = []
    for r in results:
        h, a, flags = r["headline"], r["analysis"], r["flags"]
        top_topic, top_score = ("—", 0.0)
        if a["topics"]:
            top_topic, top_score = max(a["topics"].items(), key=lambda kv: kv[1])
        rows.append(
            {
                "Date": h["published_at"][:10],
                "Quarter": h.get("quarter", ""),
                "Sentiment": f"{a['sentiment']['label']} ({a['sentiment']['score']:.2f})",
                "_sentiment_label": a["sentiment"]["label"],
                "Top topic": f"{top_topic} ({top_score:.2f})",
                "Risk flags": ", ".join(f.rule_id for f in flags) or "—",
                "Headline": h["title"],
                "Source": h["provider"],
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


def _rules_dataframe() -> pd.DataFrame:
    """Flatten the ISA 315 rule catalog (isa315_map.yaml) for display."""
    rows = []
    for rule in risk.load_rules():
        triggers = rule.get("triggers", {})
        gate = "—"
        if "sentiment" in triggers:
            thresh = float(triggers.get("sentiment_threshold", 0.5))
            gate = f"{triggers['sentiment']} ≥ {thresh:.2f}"
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
    with st.expander("ℹ️ How this report works · ISA 315 rule catalog", expanded=False):
        st.markdown(
            f"""
**From headline to risk flag, in four steps:**

1. **Fetch** — headlines mentioning the company are pulled from GDELT and
   Google News RSS for the selected period, deduplicated, and filtered to
   titles that actually name the company.
2. **Deep learning** — each headline is language-detected (German is
   translated to English), scored for financial sentiment by FinBERT, and
   scored against every trigger topic below by a zero-shot classifier.
   Each topic gets an independent 0–1 score.
3. **Rule evaluation** — a rule fires when at least one of its trigger topics
   scores ≥ **{risk.DEFAULT_TOPIC_THRESHOLD:.2f}** and, where the rule has a
   sentiment gate, the sentiment label and score also match. One headline can
   fire several rules; each firing becomes one **risk flag**.
4. **Report** — flags are aggregated by category and severity into the risk
   radar, and every flagged headline links back to the ISA / IDW references
   and suggested procedures of the rule that fired.

The catalog below is read live from `domain/isa315_map.yaml` — rules are data,
not code, so they can be reviewed and edited without touching the app.
Severity is fixed per rule: **high** = red, **medium** = orange, **low** = yellow.
"""
        )

        st.dataframe(
            _rules_dataframe().style.map(
                lambda s: f"background-color: {SEVERITY_COLORS.get(s, '#999')}; color: white",
                subset=["Severity"],
            ),
            use_container_width=True,
            hide_index=True,
        )

        rules = risk.load_rules()
        selected_id = st.selectbox(
            "Inspect a rule",
            options=[r["id"] for r in rules],
            format_func=lambda rid: next(
                f"{r['id']} · {r['category']}" for r in rules if r["id"] == rid
            ),
        )
        rule = next(r for r in rules if r["id"] == selected_id)
        st.markdown(f"> {rule.get('description', '').strip()}")
        st.markdown("**Suggested procedures**")
        for p in rule.get("procedures", []):
            st.write(f"· {p}")

        st.caption(
            "The flags support the auditor's professional judgment — they do not "
            "perform the ISA 315 risk assessment. Every flag requires human review."
        )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.session_state.setdefault("refresh_nonce", 0)
st.session_state.setdefault("queue", [])
st.session_state.setdefault("results", [])
st.session_state.setdefault("paused", False)
st.session_state.setdefault("pipeline_signature", "")

with st.sidebar:
    st.title("Audit Risk Radar")
    st.caption("DAX 40 · ISA 315 support tool")

    companies = news.load_companies()
    ticker_options = [c["ticker"] for c in companies]
    default_ticker_idx = ticker_options.index("SAP.DE") if "SAP.DE" in ticker_options else 0
    ticker = st.selectbox(
        "Company",
        options=ticker_options,
        format_func=lambda t: f"{next(c['name'] for c in companies if c['ticker'] == t)} ({t})",
        index=default_ticker_idx,
    )

    # --- Year + Quarters ---------------------------------------------------
    cur_year, cur_q = _current_year_and_quarter()
    year_options = list(range(cur_year, cur_year - 5, -1))  # last 5 years, newest first
    year = st.selectbox("Year", options=year_options, index=0)

    quarter_choice = st.multiselect(
        "Reporting period (one or more quarters)",
        options=["Q1", "Q2", "Q3", "Q4"],
        default=[f"Q{cur_q}"] if year == cur_year else ["Q1", "Q2", "Q3", "Q4"],
        help="Select the quarters within the chosen year to investigate.",
    )
    quarters: tuple[int, ...] = tuple(sorted(int(q[1:]) for q in quarter_choice))
    period_label = f"{', '.join(quarter_choice) or '—'} {year}"

    st.divider()
    refresh_clicked = st.button(
        "🔄 Fetch latest data", type="primary", use_container_width=True,
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
                f"{spec['architecture']} · {spec['params']}  \n"
                f"_{spec['purpose']}_"
            )

    st.caption(
        "This tool **supports** the auditor's professional judgment. "
        "It does not perform ISA 315 risk assessment."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if not quarters:
    st.warning("Select at least one quarter in the sidebar.")
    st.stop()

company = news.get_company(ticker)
st.title(f"{company['name']}  ·  {period_label}")
st.caption(f"Sector: {company['sector']}  ·  Ticker: `{ticker}`")

_render_how_it_works()

load_models()

# --- Price panel ------------------------------------------------------------

price_df = cached_prices(ticker, year, quarters, st.session_state.refresh_nonce)
summary = prices.summarize(price_df)

kpi_cols = st.columns(4)
if summary:
    kpi_cols[0].metric(
        "Last close (EUR)", f"{summary['last_close']:.2f}",
        delta=f"{summary['period_return_pct']:+.2f}% (period)",
    )
    kpi_cols[1].metric("Period high", f"{summary['period_high']:.2f}")
    kpi_cols[2].metric("Period low", f"{summary['period_low']:.2f}")
    kpi_cols[3].metric("Trading days", summary["trading_days"])

    fig = go.Figure(go.Scatter(x=price_df.index, y=price_df["Close"], mode="lines", name="Close"))
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=250,
                      showlegend=False, xaxis_title=None, yaxis_title="EUR")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No price data returned for this ticker / period.")

st.divider()

# --- News pipeline ----------------------------------------------------------

st.subheader("News · Deep-learning risk pipeline")

headline_dicts, fetch_diagnostics = cached_headlines(
    ticker, year, quarters, st.session_state.refresh_nonce
)

with st.expander("News fetch diagnostics", expanded=not headline_dicts):
    if not fetch_diagnostics:
        st.write("No diagnostics recorded.")
    else:
        for d in fetch_diagnostics:
            status = "✅" if d["ok"] else "❌"
            http = f" (HTTP {d['http_status']})" if d["http_status"] else ""
            st.write(
                f"{status} **{d['provider']}**{http} · "
                f"raw={d['n_raw']} · after filter={d['n_after_filter']}"
            )
            if d["error"]:
                st.code(d["error"], language="text")

if not headline_dicts:
    st.warning(
        "No headlines found. Common causes: (1) free sources returned nothing for "
        "the date range, (2) none of the returned articles mentioned the company "
        "by name, (3) network / rate-limit failure — see diagnostics above."
    )
    st.stop()

st.caption(f"Fetched **{len(headline_dicts)}** unique headline(s) mentioning **{company['name']}**.")

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
    ctrl1.button("⏸ Pause", disabled=True, use_container_width=True)
    ctrl2.button("▶ Resume", disabled=True, use_container_width=True)
elif is_paused:
    ctrl1.button("⏸ Pause", disabled=True, use_container_width=True)
    if ctrl2.button("▶ Resume", type="primary", use_container_width=True):
        st.session_state.paused = False
        st.rerun()
else:
    if ctrl1.button("⏸ Pause", use_container_width=True):
        st.session_state.paused = True
        st.rerun()
    ctrl2.button("▶ Resume", disabled=True, use_container_width=True)

if ctrl3.button("↺ Reset", use_container_width=True, disabled=not (done or is_paused)):
    _reset_pipeline(headline_dicts)
    st.rerun()

status_text = (
    f"**{done}/{total}** processed"
    + (" · ⏸ **paused**" if is_paused and not is_finished else "")
    + (" · ✅ complete" if is_finished else "")
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
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("Link", width="small"),
            "Headline": st.column_config.TextColumn("Headline", width="large"),
        },
    )
else:
    table_placeholder.info("No headlines processed yet. Click **▶ Resume** or wait for the pipeline to start.")

# --- Step ONE headline per rerun, then loop --------------------------------
if not is_finished and not is_paused:
    next_h = st.session_state.queue.pop(0)
    analysis_dict = cached_analyze(
        title=next_h["title"],
        language_hint=next_h.get("language_hint", ""),
        topics_key="v1",
    )
    analysis = _rebuild_analysis(analysis_dict)
    flags = risk.evaluate(analysis)
    st.session_state.results.append(
        {"headline": next_h, "analysis": analysis_dict, "flags": flags}
    )
    # Tiny sleep so a pause click at just the wrong instant has a chance
    # to register — costs almost nothing on total wall-clock time.
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
st.subheader("Risk radar · aggregated flags")

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
    st.plotly_chart(fig_bar, use_container_width=True)

    # ---- Drill-down per flag -----------------------------------------------
    st.markdown("### Flagged headlines · audit references and procedures")
    ordered = sorted(
        [(r, f) for r in results for f in r["flags"]],
        key=lambda pair: SEVERITY_ORDER.get(pair[1].severity, 99),
    )
    for r, f in ordered:
        h = r["headline"]
        a = r["analysis"]
        color = SEVERITY_COLORS[f.severity]
        with st.expander(
            f"[{f.severity.upper()}] {f.rule_id} · {f.category}  —  {h['title'][:100]}",
            expanded=False,
        ):
            st.markdown(
                f"<span style='background:{color};color:white;padding:2px 8px;"
                f"border-radius:6px'>{f.severity.upper()}</span>  "
                f"**{f.rule_id} — {f.category}**",
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
                st.write("Matched topics (score ≥ threshold):")
                for topic, score in f.matched_topics:
                    st.write(f"  · {topic} — {score:.3f}")
            with cols[1]:
                st.markdown("**Audit references**")
                for std in f.audit_ref.get("isa", []):
                    st.write(f"· ISA: {std}")
                for std in f.audit_ref.get("idw", []):
                    st.write(f"· IDW: {std}")
                st.markdown("**Suggested procedures**")
                for p in f.procedures:
                    st.write(f"· {p}")
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
                    "matched_topics": [{"topic": t, "score": s} for t, s in f.matched_topics],
                    "audit_ref": f.audit_ref,
                }
                for f in r["flags"]
            ],
        }
        for r in results
    ],
}
st.download_button(
    "⬇️  Download JSON snapshot",
    data=json.dumps(snapshot, indent=2, default=str),
    file_name=f"{ticker}_{year}_{'-'.join(f'Q{q}' for q in quarters)}_snapshot.json",
    mime="application/json",
    use_container_width=True,
)
