"""
Streamlit dashboard for the DAX 40 Audit Risk Radar.
"""

import datetime as dt

import pandas as pd
import streamlit as st

import config
import data_sources
import nlp


st.set_page_config(page_title="DAX40 Data Dashboard", layout="wide")

if "feed" not in st.session_state:
    st.session_state.feed = []
if "seen" not in st.session_state:
    st.session_state.seen = set()


st.sidebar.title("Controls")
selected_company = st.sidebar.selectbox(
    "Company to watch",
    options=list(config.DAX40.keys()),
    index=list(config.DAX40.keys()).index("SAP"),
)
companies = [selected_company]
refresh = config.REFRESH_SECONDS
news_start_date = st.sidebar.date_input(
    "Articles from",
    value=dt.date(2026, 5, 1),
)
news_end_date = st.sidebar.date_input(
    "Articles until",
    value=dt.date(2026, 6, 6),
)
stock_start_date = st.sidebar.date_input(
    "Stock prices from",
    value=dt.date(2026, 1, 1),
)

mode = "LIVE NewsAPI" if config.NEWSAPI_KEY else "Cached news/mock mode"
st.sidebar.caption(f"News source: {mode}")
st.sidebar.caption("Headlines are filtered to the selected company.")
st.sidebar.caption("Dashboard refreshes once per hour.")
st.sidebar.caption(f"Article window: {news_start_date} to {news_end_date}")
st.sidebar.caption("Prices: Direct Yahoo API (live)")

selected_tickers = [config.DAX40[c] for c in companies]
current_filter = (tuple(companies), news_start_date.isoformat(), news_end_date.isoformat())
if st.session_state.get("feed_filter") != current_filter:
    st.session_state.feed = []
    st.session_state.seen = set()
    st.session_state.feed_filter = current_filter


st.title("DAX40 Data Dashboard")
st.caption(
    "Real-time screening of market and news data to surface ISA 315 risk signals. "
    "FinBERT scores financial sentiment; a Zero-Shot classification model assigns audit categories, "
    "affected accounts, and legal/audit references for warning signals."
)


def _article_label(item: dict, index: int) -> str:
    headline = item["headline"]
    if len(headline) > 90:
        headline = f"{headline[:87]}..."
    return f"{index}. {item['company']} - {headline}"


def _investigation_summary(item: dict) -> str:
    if item["is_warning"]:
        return item["suggested_audit_response"]
    return "No further investigation necessary based on this signal alone."


def _render_article_implication(item: dict) -> None:
    if item.get("source_url"):
        st.markdown(f"[Open source article]({item['source_url']})")
    st.markdown(f"**External signal:** {item['headline']}")
    st.markdown(
        f"**Sentiment:** {item['sentiment']} | "
        f"**Confidence:** {item['confidence']} | "
        f"**Risk score:** {item['risk_score']}"
    )
    st.caption(
        "Sentiment is assigned by FinBERT, a financial-language model. "
        "Confidence is the model probability for the chosen sentiment label. "
        "Risk score is the model probability for the negative class; for example, "
        "0.012 means the headline is only 1.2% likely to be negative according "
        "to the model."
    )
    st.markdown(f"**Risk drivers:** {', '.join(item['risk_drivers'])}")
    st.caption(
        "Risk drivers are assigned contextually using a facebook/bart-large-mnli Zero-Shot Transformer "
        "model to evaluate semantic linguistic definitions rather than relying on exact keyword lookups."
    )
    st.markdown(f"**Audit risk category:** {item['audit_risk_category']}")
    st.markdown(
        f"**Financial statement level risk:** "
        f"{item['financial_statement_level_risk']}"
    )
    st.markdown(f"**Affected accounts:** {item['affected_accounts']}")
    st.markdown(f"**Affected assertions:** {item['affected_assertions']}")
    st.markdown(f"**Affected departments:** {item['affected_departments']}")

    if item.get("legal_reference") or item.get("audit_standard_reference"):
        st.markdown(f"**Legal reference:** {item['legal_reference'] or 'Not assigned'}")
        st.markdown(
            f"**Audit standard reference:** "
            f"{item['audit_standard_reference'] or 'Not assigned'}"
        )
        st.caption(item["legal_reference_explanation"])
        st.caption(item["audit_standard_explanation"])
        st.markdown(f"**Responsibility area:** {item['reference_responsibility']}")
    else:
        st.markdown("**Legal / audit reference:** Not assigned for this article.")

    st.markdown(f"**Implication:** {_investigation_summary(item)}")


@st.fragment(run_every=refresh)
def live_feed():
    if not companies:
        st.info("Pick at least one company in the sidebar to stream audit news.")
        return
    if news_start_date > news_end_date:
        st.warning("Article start date must be before or equal to the end date.")
        return

    st.caption(
        "News selection: the app polls cached scraped news or NewsAPI for the "
        "companies and article date range selected in the sidebar, then deduplicates "
        "by company and headline."
    )

    incoming = data_sources.poll_news(
        n=3,
        companies=companies,
        start_date=news_start_date,
        end_date=news_end_date,
    )

    for item in incoming:
        key = (item["company"], item["headline"])
        if key in st.session_state.seen:
            continue
        st.session_state.seen.add(key)
        try:
            scored = nlp.score_headline(item)
        except Exception as e:  # noqa: BLE001
            st.warning(f"NLP scoring failed: {e}")
            continue
        st.session_state.feed.insert(0, scored)

    feed = [
        item for item in st.session_state.feed
        if item["company"] in companies
    ][:50]

    warnings = [item for item in feed[:8] if item["is_warning"]]
    if warnings:
        for warning in warnings:
            source_link = warning.get("source_url")
            source_text = f"  \n[Open source article]({source_link})" if source_link else ""
            st.error(
                f"**{warning['company']}** - {warning['headline']}  \n"
                f"Risk score **{warning['risk_score']}** | drivers: "
                f"{', '.join(warning['risk_drivers'])}"
                f"{source_text}"
            )

    c1, c2, c3, c4 = st.columns(4)
    total = len(feed)
    neg = sum(1 for item in feed if item["sentiment"] == "negative")
    flags = sum(1 for item in feed if item["is_warning"])
    c1.metric("Headlines processed", total)
    c2.metric("Negative signals", neg)
    c3.metric("Active warnings", flags)
    c4.metric("Last update", dt.datetime.now().strftime("%H:%M:%S"))

    if feed:
        df = pd.DataFrame(feed)
        df["risk_drivers"] = df["risk_drivers"].apply(", ".join)
        df["details"] = "#article-implications"
        df["implication"] = df.apply(
            lambda row: "Investigate" if row["is_warning"] else "No further investigation",
            axis=1,
        )
        df = df[
            [
                "details",
                "company",
                "headline",
                "sentiment",
                "confidence",
                "risk_score",
                "risk_drivers",
                "implication",
                "source_url",
            ]
        ]
        df = df.rename(
            columns={
                "confidence": "confidence*",
                "risk_score": "risk_score*",
                "risk_drivers": "risk_drivers*",
            }
        )
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "details": st.column_config.LinkColumn(
                    "details",
                    display_text="view",
                    width="small",
                ),
                "company": st.column_config.TextColumn("company", width="small"),
                "headline": st.column_config.TextColumn("headline", width="large"),
                "sentiment": st.column_config.TextColumn("sentiment", width="small"),
                "confidence*": st.column_config.NumberColumn(
                    "confidence*",
                    width="small",
                    format="%.3f",
                ),
                "risk_score*": st.column_config.NumberColumn(
                    "risk_score*",
                    width="small",
                    format="%.3f",
                ),
                "risk_drivers*": st.column_config.TextColumn("risk_drivers*", width="medium"),
                "implication": st.column_config.TextColumn("implication", width="medium"),
                "source_url": st.column_config.LinkColumn(
                    "source link",
                    display_text="open",
                    width="small",
                )
            },
        )
        st.caption(
            "* confidence = FinBERT certainty for the displayed sentiment label. "
            "risk_score = FinBERT negative-class probability, so values closer to "
            "1.000 indicate stronger negative-risk wording. risk_drivers = contextual "
            "ISA-315-style categories evaluated by the Zero-Shot model."
        )
    else:
        st.info("Waiting for matching headlines to stream in...")

    st.markdown('<a id="article-implications"></a>', unsafe_allow_html=True)
    st.subheader("Article Implications")
    if feed:
        for index, item in enumerate(feed, start=1):
            with st.expander(_article_label(item, index), expanded=index == 1):
                _render_article_implication(item)
    else:
        st.info(
            "Article implications appear after matching headlines are scored."
        )


live_feed()


st.subheader(f"Stock prices from {stock_start_date}")


@st.fragment(run_every=refresh)
def price_panel():
    if not selected_tickers:
        st.info("Pick at least one company in the sidebar.")
        return

    prices = data_sources.get_prices(selected_tickers, start_date=stock_start_date)
    if not prices:
        st.warning("Could not fetch prices right now. The market may be closed or the network may be unavailable.")
        return

    cols = st.columns(min(len(prices), 5))
    for i, (ticker, price) in enumerate(prices.items()):
        with cols[i % len(cols)]:
            st.metric(
                config.TICKER_TO_NAME.get(ticker, ticker),
                f"EUR {price['last']:.2f}",
                f"{price['pct_change']:+.2f}%",
            )

    chart_df = pd.DataFrame({
        config.TICKER_TO_NAME.get(ticker, ticker): price["history"]
        for ticker, price in prices.items()
    })
    st.line_chart(chart_df, width="stretch")


price_panel()

st.caption(
    "Disclaimer: decision-support tool for audit planning (ISA 315). "
    "Sentiment is model-generated and must be reviewed by the engagement team."
)