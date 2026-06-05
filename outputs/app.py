"""
app.py
------
The "Visualize" layer: the Streamlit dashboard auditors actually open.

Run it with:   streamlit run app.py

Streaming model
---------------
Streamlit reruns the whole script on every interaction. To get a *live* feed
without freezing the page, the news section is wrapped in an
`@st.fragment(run_every=...)` block, which re-executes ON ITS OWN on a timer and
updates only that part of the page. New headlines are pushed into
`st.session_state.feed` (a rolling buffer) so history persists across reruns.
"""

import datetime as dt

import pandas as pd
import streamlit as st

import config
import data_sources
import nlp

st.set_page_config(page_title="DAX 40 Audit Risk Radar", page_icon="📊", layout="wide")

# --- session state: the rolling event log ------------------------------------
if "feed" not in st.session_state:
    st.session_state.feed = []          # list of scored headline dicts
if "seen" not in st.session_state:
    st.session_state.seen = set()       # de-dupe by (company, headline)

# --- sidebar controls ---------------------------------------------------------
st.sidebar.title("⚙️ Controls")
companies = st.sidebar.multiselect(
    "Companies to watch",
    options=list(config.DAX40.keys()),
    default=["Siemens", "Volkswagen", "SAP", "Deutsche Bank", "Bayer"],
)
refresh = st.sidebar.slider("Refresh interval (sec)", 5, 60, config.REFRESH_SECONDS, 5)
mode = "🟢 LIVE NewsAPI" if config.NEWSAPI_KEY else "🟡 Mock stream (no key set)"
st.sidebar.caption(f"News source: {mode}")
st.sidebar.caption("Prices: yfinance (live)")

selected_tickers = [config.DAX40[c] for c in companies]

# --- header -------------------------------------------------------------------
st.title("📊 DAX 40 Audit Risk Radar")
st.caption(
    "Real-time screening of market + news data to surface ISA-315 risk signals. "
    "FinBERT scores financial sentiment; the lexicon tags the risk category."
)

# =============================================================================
# LIVE NEWS + RISK FEED  (auto-refreshing fragment = the "stream")
# =============================================================================
@st.fragment(run_every=refresh)
def live_feed():
    # 1. INGEST: poll for new headlines
    incoming = data_sources.poll_news(n=2)

    # 2. PROCESS + SCORE: run each NEW headline through FinBERT
    for item in incoming:
        key = (item["company"], item["headline"])
        if key in st.session_state.seen:
            continue
        st.session_state.seen.add(key)
        try:
            scored = nlp.score_headline(item)
        except Exception as e:  # noqa: BLE001 -- model load / inference guard
            st.warning(f"NLP scoring failed: {e}")
            continue
        st.session_state.feed.insert(0, scored)      # newest first

    feed = st.session_state.feed[:50]                # cap memory

    # 3a. VISUALIZE: flash warnings for fresh negative signals
    warnings = [f for f in feed[:6] if f["is_warning"]]
    if warnings:
        for w in warnings:
            st.error(
                f"⚠️ **{w['company']}** — {w['headline']}  \n"
                f"Risk score **{w['risk_score']}** · drivers: "
                f"{', '.join(w['risk_drivers'])}"
            )

    # 3b. top metrics
    c1, c2, c3, c4 = st.columns(4)
    total = len(feed)
    neg = sum(1 for f in feed if f["sentiment"] == "negative")
    flags = sum(1 for f in feed if f["is_warning"])
    c1.metric("Headlines processed", total)
    c2.metric("Negative signals", neg)
    c3.metric("Active warnings", flags)
    c4.metric("Last update", dt.datetime.now().strftime("%H:%M:%S"))

    # 3c. the event table
    if feed:
        df = pd.DataFrame(feed)
        df = df[["published", "company", "headline", "sentiment",
                 "confidence", "risk_drivers", "source"]]
        df["risk_drivers"] = df["risk_drivers"].apply(", ".join)

        def _row_style(row):
            color = {"negative": "#5a1f1f", "positive": "#1f4020"}.get(row["sentiment"], "")
            return [f"background-color: {color}" if color else "" for _ in row]

        st.dataframe(
            df.style.apply(_row_style, axis=1),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Waiting for the first headlines to stream in…")


live_feed()

# =============================================================================
# LIVE PRICES  (also inside an auto-refreshing fragment)
# =============================================================================
st.subheader("📈 Intraday prices")


@st.fragment(run_every=refresh)
def price_panel():
    if not selected_tickers:
        st.info("Pick at least one company in the sidebar.")
        return
    prices = data_sources.get_prices(selected_tickers)
    if not prices:
        st.warning("Could not fetch prices right now (market closed or network).")
        return

    cols = st.columns(min(len(prices), 5))
    for i, (ticker, p) in enumerate(prices.items()):
        with cols[i % len(cols)]:
            st.metric(
                config.TICKER_TO_NAME.get(ticker, ticker),
                f"€{p['last']:.2f}",
                f"{p['pct_change']:+.2f}%",
            )

    # combined intraday chart
    chart_df = pd.DataFrame({
        config.TICKER_TO_NAME.get(t, t): p["history"]
        for t, p in prices.items()
    })
    st.line_chart(chart_df, use_container_width=True)


price_panel()

st.caption(
    "Disclaimer: decision-support tool for audit planning (ISA 315). "
    "Sentiment is model-generated and must be reviewed by the engagement team."
)
