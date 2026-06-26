from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Iterable

import config

PROJECT_ROOT = Path(__file__).resolve().parent
# NOTE: This app is fully streaming — every value is fetched live from an API at
# request time. No scraped CSV in data/ is read at runtime (the data/ folder only
# holds the SQLite cache of already-scored headlines, audit_radar.db).


# =============================================================================
# 1. STOCK PRICES  (live, no API key required, NO fallback to CSV)
# =============================================================================

def get_prices(tickers: Iterable[str], start_date=None):
    """Fetch live stock prices directly from Yahoo's hidden JSON API."""
    import requests
    import pandas as pd
    from urllib.parse import quote

    out = {}
    tickers = list(tickers)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    price_start_date = start_date or config.PRICE_START_DATE

    # 1. Dynamically calculate the date range
    if price_start_date:
        # Convert the Streamlit calendar date into a Unix timestamp (period1)
        p1 = int(pd.to_datetime(price_start_date).timestamp())
        # Set the end date to right now (period2)
        p2 = int(pd.Timestamp.now().timestamp())
        
        api_params = {
            "period1": p1,
            "period2": p2,
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }
    else:
        # Fallback if no date is selected
        api_params = {
            "range": "1y",
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }

    for ticker in tickers:
        try:
            # 2. Hit the Yahoo Chart API
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}"
            
            res = requests.get(url, params=api_params, headers=headers, timeout=5)
            res.raise_for_status()
            data = res.json()

            # 3. Parse the JSON payload
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue

            timestamps = result[0].get("timestamp", [])
            quote_data = result[0].get("indicators", {}).get("quote", [{}])[0]
            closes = quote_data.get("close", [])

            if not timestamps or not closes:
                continue

            # 4. Convert to a Pandas DataFrame
            history_df = pd.DataFrame({
                "date": pd.to_datetime(timestamps, unit="s", utc=True),
                "close": closes
            }).dropna()

            if history_df.empty:
                continue

            # 5. Format the output for the Streamlit UI
            history_series = history_df.set_index("date")["close"]
            
            last = float(history_series.iloc[-1])
            first = float(history_series.iloc[0])
            pct = (last - first) / first * 100 if first else 0.0

            out[ticker] = {
                "last": last,
                "pct_change": pct,
                "history": history_series
            }

        except Exception as e:
            print(f"[get_prices] Direct API fetch failed for {ticker}: {e}")
            continue
            
    return out

import time
import streamlit as st

# =============================================================================
# 2. NEWS STREAM (Live NewsAPI Mode)
# =============================================================================

# Non-Latin scripts (CJK, Cyrillic, Hebrew, Arabic, Thai) — an English backstop
# on top of NewsAPI's language=en filter.
_NON_LATIN = re.compile(
    "[぀-ヿ㐀-鿿가-힯"   # Japanese kana, CJK, Hangul
    "Ѐ-ӿ֐-׿؀-ۿ"      # Cyrillic, Hebrew, Arabic
    "฀-๿]"                               # Thai
)


def _is_probably_english(text: str) -> bool:
    """English backstop: reject titles containing non-Latin-script characters."""
    return bool(text) and not _NON_LATIN.search(text)


# Cache results for 1 hour so repeated clicks for the same query don't burn the
# NewsAPI free-tier daily quota.
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_newsapi_fetch(query: str, from_str: str | None, to_str: str | None, page_size: int):
    """Call NewsAPI /everything and return the raw article list (cached)."""
    import requests

    params = {
        "q": query,
        # Match the company in the HEADLINE only. NewsAPI's default full-text
        # search floods results with articles that merely mention the word in
        # the body, which the company tag below would then discard.
        "searchIn": "title",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": config.NEWSAPI_KEY,
    }
    if from_str:
        params["from"] = from_str
    if to_str:
        params["to"] = to_str

    r = None
    try:
        r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("articles", [])
    except requests.exceptions.HTTPError:
        # NewsAPI returns a JSON error body (quota exceeded, invalid key, etc.).
        try:
            msg = r.json().get("message", r.text)
        except Exception:  # noqa: BLE001
            msg = r.text if r is not None else "unknown error"
        st.error(f"NewsAPI error: {msg}")
        return []
    except Exception as e:  # noqa: BLE001
        st.error(f"NewsAPI request failed: {e}")
        return []


def _newsapi_news(
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
    page_size: int = 10,
):
    """Fetch and normalise NewsAPI headlines for the selected company."""
    if not config.NEWSAPI_KEY:
        st.error("NEWSAPI_KEY is not set — add it to your .env file to fetch news.")
        return []

    selected = list(companies) if companies else ["Siemens", "Volkswagen", "SAP"]
    query = " OR ".join(f'"{c}"' for c in selected)

    # NewsAPI's free tier only serves the last 30 days. Clamp the start date and
    # tell the user instead of silently returning nothing.
    today = dt.date.today()
    earliest = today - dt.timedelta(days=30)
    from_str = to_str = None
    if start_date:
        if start_date < earliest:
            st.info(
                f"NewsAPI free tier only covers the last 30 days — showing news "
                f"from {earliest} instead of {start_date}."
            )
        from_str = max(start_date, earliest).isoformat()
    if end_date:
        to_str = end_date.isoformat()

    # Fetch a few extra so the English/company filters still leave a useful list.
    articles = _cached_newsapi_fetch(query, from_str, to_str, max(page_size, 12))

    results = []
    for a in articles:
        title = a.get("title") or ""
        if not _is_probably_english(title):
            continue

        company = next(
            (name for name in config.DAX40 if name.split()[0].lower() in title.lower()),
            "",
        )
        if selected and company not in selected:
            company = selected[0] if len(selected) == 1 else "DAX 40"

        results.append({
            "company": company,
            "headline": title,
            "published": a.get("publishedAt", ""),
            "source": (a.get("source") or {}).get("name", "NewsAPI"),
            "source_url": a.get("url", ""),
        })
    return results


# =============================================================================
# 2b. DEEP-HISTORY FALLBACK (GDELT — covers dates older than NewsAPI's 30 days)
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_gdelt_fetch(query: str, start_str: str | None, end_str: str | None, page_size: int):
    """Call GDELT DOC 2.0 ArtList. GDELT throttles to 1 request / 5 seconds, so
    we back off (>=6s) on HTTP 429 and tolerate its non-JSON error bodies."""
    import requests

    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords": page_size}
    if start_str:
        params["startdatetime"] = start_str
        if end_str:
            params["enddatetime"] = end_str
    else:
        params["timespan"] = "1month"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            if r.status_code == 429:  # GDELT requires >=5s spacing
                time.sleep(6 + attempt * 3)
                continue
            r.raise_for_status()
            text = r.text.strip()
            if not text or text[0] not in "[{":  # empty / plain-text notice, not JSON
                if attempt < 2:
                    time.sleep(6)
                    continue
                return []
            return r.json().get("articles", [])
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                st.warning(f"GDELT history fetch failed: {e}")
                return []
    return []


def _gdelt_news(companies=None, start_date=None, end_date=None, page_size: int = 10):
    """Normalise GDELT results into the same dict shape as NewsAPI (English only)."""
    selected = list(companies) if companies else ["Siemens", "Volkswagen", "SAP"]
    query = " OR ".join(f'"{c}"' for c in selected)
    start_str = f"{start_date.strftime('%Y%m%d')}000000" if start_date else None
    end_str = f"{end_date.strftime('%Y%m%d')}235959" if end_date else None

    articles = _cached_gdelt_fetch(query, start_str, end_str, max(page_size, 12))

    results = []
    for a in articles:
        title = a.get("title") or ""
        lang = (a.get("language") or "").strip().lower()
        if lang and lang not in ("english", "eng", "en"):
            continue
        if not _is_probably_english(title):
            continue
        company = next(
            (name for name in config.DAX40 if name.split()[0].lower() in title.lower()), "",
        )
        if selected and company not in selected:
            company = selected[0] if len(selected) == 1 else "DAX 40"
        results.append({
            "company": company,
            "headline": title,
            "published": a.get("seendate", ""),
            "source": a.get("domain", "GDELT"),
            "source_url": a.get("url", ""),
        })
    return results


# =============================================================================
# 2c. ENTRY POINT — hybrid NewsAPI (recent) + GDELT (history)
# =============================================================================
def poll_news(
    n: int = 5,
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
):
    """Single entry point for the UI.

    NewsAPI serves the last 30 days (clean, reliable); GDELT covers anything
    older (NewsAPI's free tier can't reach it). The two are merged and
    de-duplicated so the requested window is fully covered.
    """
    today = dt.date.today()
    earliest_newsapi = today - dt.timedelta(days=30)

    combined = []

    # 1) Recent window (overlaps the last 30 days) -> NewsAPI.
    if end_date is None or end_date >= earliest_newsapi:
        recent_start = max(start_date, earliest_newsapi) if start_date else None
        combined += _newsapi_news(companies, recent_start, end_date, page_size=n)

    # 2) Older window (before the last 30 days) -> GDELT deep history.
    if start_date and start_date < earliest_newsapi:
        history_end = min(end_date or today, earliest_newsapi)
        combined += _gdelt_news(companies, start_date, history_end, page_size=n)

    # De-duplicate by (company, headline).
    seen, deduped = set(), []
    for item in combined:
        key = (item["company"], item["headline"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped