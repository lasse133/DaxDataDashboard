"""
Streamlit dashboard for the DAX 40 Audit Risk Radar.
"""

import datetime as dt
from collections import Counter
from email.utils import parsedate_to_datetime

import pandas as pd
import streamlit as st

import config
import data_sources
import nlp
import database

# Initialize the database and table schema on startup
database.init_db()

st.set_page_config(page_title="DAX40 Data Dashboard", layout="wide")

st.sidebar.title("Controls")
selected_company = st.sidebar.selectbox(
    "Company to watch",
    options=list(config.DAX40.keys()),
    index=list(config.DAX40.keys()).index("SAP"),
)
companies = [selected_company]
refresh = config.REFRESH_SECONDS

def _quarter_window(year: int, quarters: list[str]) -> tuple[dt.date, dt.date]:
    quarter_ranges = {
        "Q1": (dt.date(year, 1, 1), dt.date(year, 3, 31)),
        "Q2": (dt.date(year, 4, 1), dt.date(year, 6, 30)),
        "Q3": (dt.date(year, 7, 1), dt.date(year, 9, 30)),
        "Q4": (dt.date(year, 10, 1), dt.date(year, 12, 31)),
    }
    ranges = [quarter_ranges[q] for q in quarters]
    return min(r[0] for r in ranges), min(max(r[1] for r in ranges), dt.date.today())


available_years = list(range(2025, dt.date.today().year + 1))
period_year = st.sidebar.selectbox(
    "Reporting year",
    options=available_years,
    index=available_years.index(2025),
)
selected_quarters = st.sidebar.multiselect(
    "Reporting period",
    options=["Q1", "Q2", "Q3", "Q4"],
    default=["Q1", "Q2", "Q3", "Q4"],
    help="Select one or more quarters. Selecting Q1-Q4 gives the full year.",
)
if not selected_quarters:
    st.sidebar.warning("Select at least one quarter.")
    selected_quarters = ["Q1", "Q2", "Q3", "Q4"]

news_start_date, news_end_date = _quarter_window(period_year, selected_quarters)
stock_start_date = news_start_date

st.sidebar.caption("News source: NewsAPI recent + Google News RSS history")
st.sidebar.caption("Headlines are filtered to the selected company in English or German.")
st.sidebar.caption("News is fetched on demand — click 'Fetch latest news'.")
st.sidebar.caption(
    f"Selected period: {', '.join(selected_quarters)} {period_year} "
    f"({news_start_date} to {news_end_date})"
)
st.sidebar.caption("Prices: Direct Yahoo API (live)")

selected_tickers = [config.DAX40[c] for c in companies]

if st.sidebar.button(
    "🗑️ Clear cached news",
    help="Delete all stored headlines and the 1-hour API response cache, then reload.",
):
    deleted = database.clear_headlines()
    st.cache_data.clear()
    st.toast(f"Cleared {deleted} cached headline(s).")
    st.rerun()

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
    label = f"{index}. {item['company']} - {headline}"
    if item.get("is_warning"):
        # Make headlines that need investigation stand out in the implications list.
        return f":red[⚠️ {label}]"
    return label


def _highlight_investigation_rows(row):
    """Tint table rows that need investigation (implication == 'Investigate')
    with a warning colour: light-red fill, bold dark-red text."""
    if row.get("implication") == "Investigate":
        return ["background-color: #ffd5d5; color: #b00020; font-weight: 600"] * len(row)
    return [""] * len(row)


def _investigation_summary(item: dict) -> str:
    if item["is_warning"]:
        return item["suggested_audit_response"]
    return "No further investigation necessary based on this signal alone."


def _filter_feed_by_period(feed: list[dict]) -> list[dict]:
    """Keep cached headlines inside the selected reporting period."""
    start = pd.Timestamp(news_start_date).tz_localize(None)
    end = pd.Timestamp(news_end_date).tz_localize(None) + pd.Timedelta(days=1)
    filtered = []
    for item in feed:
        published = pd.to_datetime(item.get("published"), errors="coerce", utc=True)
        if pd.isna(published):
            filtered.append(item)
            continue
        published = published.tz_convert(None)
        if start <= published < end:
            filtered.append(item)
    return filtered


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


def _scoring_failed(scored: dict) -> bool:
    """True if the NLP models errored out, so we don't cache a broken record."""
    drivers = scored.get("risk_drivers") or []
    return (
        "BART Model Error" in drivers
        or "FinBERT Model Error" in str(scored.get("sentiment", ""))
    )


def _not_scored_language_record(item: dict) -> dict:
    return {
        **item,
        "sentiment": "not scored due to language",
        "confidence": 0.0,
        "risk_score": 0.0,
        "risk_drivers": ["Not scored due to language"],
        "is_warning": False,
        "audit_risk_category": "Not assigned",
        "financial_statement_level_risk": "Not assigned",
        "affected_accounts": "Not assigned",
        "affected_assertions": "Not assigned",
        "affected_departments": "Not assigned",
        "legal_reference": "",
        "audit_standard_reference": "",
        "legal_reference_explanation": "",
        "audit_standard_explanation": "",
        "reference_responsibility": "Engagement team",
        "suggested_audit_response": (
            "German-language headline retained for review, but not scored by the "
            "current English NLP models."
        ),
    }


def fetch_and_score_news():
    """Manual fetch: poll the news sources, score only new headlines, persist to
    SQLite. Triggered by the button (no automatic timer)."""
    if news_start_date > news_end_date:
        st.warning("Article start date must be before or equal to the end date.")
        return

    with st.spinner(f"Fetching and scoring news for {companies[0]}…"):
        incoming = data_sources.poll_news(
            n=24,
            companies=companies,
            start_date=news_start_date,
            end_date=news_end_date,
        )

        debug = data_sources.get_last_news_debug()

        new_count = 0
        for item in incoming:
            if database.headline_exists(item["company"], item["headline"]):
                debug["skipped_already_cached"] = debug.get("skipped_already_cached", 0) + 1
                continue
            try:
                if item.get("original_language") == "de":
                    scored = _not_scored_language_record(item)
                else:
                    scored = nlp.score_headline(item)
                if _scoring_failed(scored):
                    debug["nlp_model_error_skipped"] = debug.get("nlp_model_error_skipped", 0) + 1
                    st.warning(
                        "NLP model error while scoring a headline — skipped "
                        "(not cached). Check the terminal for the traceback."
                    )
                    continue
                database.save_headline(scored)
                new_count += 1
                debug["saved_to_sqlite"] = debug.get("saved_to_sqlite", 0) + 1
            except Exception as e:  # noqa: BLE001
                debug["nlp_exception_skipped"] = debug.get("nlp_exception_skipped", 0) + 1
                st.warning(f"NLP scoring failed: {e}")
                continue

        debug["sent_to_nlp_scoring"] = max(
            0,
            len(incoming) - debug.get("skipped_already_cached", 0),
        )
        debug["source_counts"] = dict(Counter(item.get("source", "Unknown") for item in incoming))
        st.session_state["news_debug"] = debug

    st.success(f"Fetched {len(incoming)} headline(s); {new_count} new and scored.")


def render_news_diagnostics():
    debug = st.session_state.get("news_debug")
    if not debug:
        return

    with st.expander("News ingestion diagnostics", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Company", debug.get("selected_company", ""))
        c2.metric("Ticker", debug.get("ticker", ""))
        c3.metric("Sector", debug.get("sector", ""))

        st.markdown("**Generated queries**")
        st.write(debug.get("generated_queries", []))
        st.markdown("**Normal history source**")
        st.write(debug.get("normal_history_source", "GDELT / NewsAPI"))
        if debug.get("gdelt_queries"):
            st.markdown("**GDELT history queries used**")
            st.write(debug.get("gdelt_queries", []))
        st.markdown("**Date windows used**")
        st.write(debug.get("date_windows", []))
        if debug.get("selected_period_windows"):
            st.markdown("**Full selected period windows**")
            st.write(debug.get("selected_period_windows", []))

        counts = {
            "raw articles fetched": debug.get("raw_articles_fetched", 0),
            "removed duplicates": debug.get("removed_as_duplicates", 0),
            "removed by language filter": debug.get("removed_by_language_filter", 0),
            "removed low-value/noise": debug.get("removed_low_value", 0),
            "deduped before limit": debug.get("deduped_before_limit", 0),
            "incoming from poll": debug.get("incoming_from_poll", 0),
            "sent to NLP / retained": debug.get("sent_to_nlp_scoring", 0),
            "saved to SQLite": debug.get("saved_to_sqlite", 0),
            "skipped cached": debug.get("skipped_already_cached", 0),
            "skipped NLP model error": debug.get("nlp_model_error_skipped", 0),
            "skipped NLP exception": debug.get("nlp_exception_skipped", 0),
        }
        st.table(pd.DataFrame(counts.items(), columns=["step", "count"]))
        if debug.get("source_counts"):
            st.markdown("**Retained headlines by source**")
            source_counts = pd.DataFrame(
                sorted(debug["source_counts"].items(), key=lambda item: item[1], reverse=True),
                columns=["source", "count"],
            )
            st.dataframe(source_counts, hide_index=True, width="stretch")
        if debug.get("incoming_headline_sample"):
            st.markdown("**Incoming headlines from normal fetch**")
            st.dataframe(
                pd.DataFrame(debug["incoming_headline_sample"]),
                width="stretch",
                hide_index=True,
            )


def render_gdelt_debugger():
    with st.expander("GDELT raw debugger", expanded=False):
        st.caption(
            "Runs a small raw source check before normal filtering and NLP scoring. "
            "Use this when a company shows zero final matches."
        )
        max_windows = st.number_input(
            "Monthly windows to test",
            min_value=1,
            max_value=12,
            value=2,
            step=1,
        )
        if st.button("Run raw GDELT debug", type="secondary"):
            with st.spinner("Checking raw GDELT results..."):
                result = data_sources.debug_gdelt_raw(
                    selected_company,
                    news_start_date,
                    news_end_date,
                    max_windows=int(max_windows),
                )
            st.session_state["gdelt_debug"] = result

        result = st.session_state.get("gdelt_debug")
        if not result:
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("Company", result.get("official_company", ""))
        c2.metric("Ticker", result.get("ticker", ""))
        c3.metric("Sector", result.get("sector", ""))
        st.markdown("**Queries tested**")
        st.write(result.get("queries_tested", []))
        st.markdown("**Windows tested**")
        st.write(result.get("windows_tested", []))
        st.markdown("**Totals**")
        st.table(pd.DataFrame(result.get("totals", {}).items(), columns=["metric", "count"]))

        for index, run in enumerate(result.get("runs", []), start=1):
            with st.expander(
                f"{index}. {run['window']} | raw={run['raw_articles']} | {run['query']}",
                expanded=False,
            ):
                st.write(
                    {
                        "language_kept_in_sample": run["language_kept_in_sample"],
                        "language_removed_in_sample": run["language_removed_in_sample"],
                    }
                )
                if run.get("sample"):
                    st.dataframe(
                        pd.DataFrame(run["sample"]),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "url": st.column_config.LinkColumn("url", display_text="open"),
                        },
                    )
                else:
                    st.info("No raw articles returned for this query/window.")


def live_feed():
    if not companies:
        st.info("Pick at least one company in the sidebar to stream audit news.")
        return

    # Read the scored history straight from SQLite (no fetching here).
    feed = _filter_feed_by_period(
        database.get_recent_headlines(companies=companies, limit=200)
    )[:50]

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
        df["implication"] = df.apply(
            lambda row: "Investigate" if row["is_warning"] else "No further investigation",
            axis=1,
        )
        df = df[
            [
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
            df.style.apply(_highlight_investigation_rows, axis=1),
            width="stretch",
            hide_index=True,
            column_config={
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
        st.info("No scored headlines yet. Click '🔄 Fetch latest news' to pull and score articles.")

    st.markdown('<a id="article-implications"></a>', unsafe_allow_html=True)
    st.subheader("Article Implications")
    if feed:
        for index, item in enumerate(feed, start=1):
            with st.expander(_article_label(item, index), expanded=False):
                _render_article_implication(item)
    else:
        st.info(
            "Article implications appear after matching headlines are scored."
        )


# --- manual news fetch control (no automatic timer) --------------------------
st.caption(
    "News is fetched on demand. Click the button to poll NewsAPI (last 30 days) plus "
    "GDELT (older dates) for the selected company and window; new headlines are scored and cached."
)
st.markdown(
    """
    <style>
    div.stButton > button {
        background-color: #e0e0e0;
        color: #333333;
        border: 1px solid #c4c4c4;
    }
    div.stButton > button:hover {
        background-color: #d5d5d5;
        color: #000000;
        border-color: #a8a8a8;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
if st.button(
    "🔄 Fetch latest news",
    type="secondary",
    help="Fetch live news (NewsAPI + GDELT) and score new headlines for the selected company.",
):
    fetch_and_score_news()

render_news_diagnostics()
render_gdelt_debugger()
live_feed()


st.subheader(f"Stock prices from {stock_start_date}")


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
