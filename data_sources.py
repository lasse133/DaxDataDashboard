from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Iterable

import config

PROJECT_ROOT = Path(__file__).resolve().parent
STOCK_PRICES_FILE = PROJECT_ROOT / "data" / "stock_prices.csv"


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
# 2. NEWS STREAM (Strictly Live GDELT API Mode)
# =============================================================================

# Add Streamlit's data cache. It keeps the downloaded JSON in memory for 1 hour (3600 seconds)
# so you don't re-ping GDELT every time you click a button in the UI.
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_gdelt_fetch(query: str, start_str: str | None, end_str: str | None, page_size: int):
    """Internal cached helper to handle the HTTP requests and rate limiters."""
    import requests
    
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": page_size,
        "timespan": "1month"  # Default if no dates
    }

    if start_str:
        params["startdatetime"] = start_str
        if end_str:
            params["enddatetime"] = end_str
        params.pop("timespan", None)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # Exponential Backoff: Try 3 times, waiting longer each time if we hit a 429 Rate Limit
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            
            # If we get a 429 Too Many Requests, wait and retry. GDELT requires
            # AT LEAST 5 seconds between requests, so the first wait must clear
            # that floor (the old 3s wait was always re-throttled).
            if r.status_code == 429:
                wait_time = 6 + attempt * 3  # 6s, 9s, 12s
                time.sleep(wait_time)
                continue
                
            r.raise_for_status()

            # GDELT sometimes returns HTTP 200 with an EMPTY body or a plain-text
            # notice (e.g. rate-limit / "query too short") instead of JSON. Calling
            # .json() on that raises "Expecting value: line 1 column 1 (char 0)".
            text = r.text.strip()
            if not text or text[0] not in "[{":
                if attempt < 2:
                    time.sleep((attempt + 1) * 2)
                    continue
                st.info(
                    "GDELT returned no parseable results — it is often rate-limiting "
                    "or has no articles for this query/date window. Try again shortly."
                )
                return []

            return r.json().get("articles", [])

        except Exception as e:
            if attempt == 2:  # If we fail on the last attempt, report it
                st.error(f"GDELT API Fetch Failed after retries: {e}")
                return []
    return []


# Non-Latin scripts (CJK, Cyrillic, Hebrew, Arabic, Thai) used as a fallback
# English check when GDELT does not tag an article's language.
_NON_LATIN = re.compile(
    "[぀-ヿ㐀-鿿가-힯"   # Japanese kana, CJK, Hangul
    "Ѐ-ӿ֐-׿؀-ۿ"      # Cyrillic, Hebrew, Arabic
    "฀-๿]"                               # Thai
)


def _is_english_article(article: dict, title: str) -> bool:
    """English-only filter: trust GDELT's per-article language tag; if it is
    missing, fall back to checking the title for non-Latin script."""
    lang = (article.get("language") or "").strip().lower()
    if lang:
        return lang in ("english", "eng", "en")
    return bool(title) and not _NON_LATIN.search(title)


def _gdelt_news(
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
    page_size: int = 10,  # Lowered default slightly to be gentler on the API
):
    """Format inputs and parse results from the open-source GDELT v2 Doc API."""
    import config
    
    selected = list(companies) if companies else ["Siemens", "Volkswagen", "SAP"]
    query = " OR ".join([f'"{c}"' for c in selected])

    start_str = f"{start_date.strftime('%Y%m%d')}000000" if start_date else None
    end_str = f"{end_date.strftime('%Y%m%d')}235959" if end_date else None

    # Call the cached and rate-limit-protected helper function
    articles = _cached_gdelt_fetch(query, start_str, end_str, page_size)

    results = []
    for a in articles:
        title = a.get("title") or ""

        # English-only: drop articles GDELT tags as another language.
        if not _is_english_article(a, title):
            continue

        company = next((name for name in config.DAX40 if name.split()[0].lower() in title.lower()), "")
        
        if selected and company not in selected:
            company = selected[0] if len(selected) == 1 else "DAX 40"

        results.append({
            "company": company,
            "headline": title,
            "published": a.get("seendate", ""),
            "source": a.get("source", "GDELT"),
            "source_url": a.get("url", ""),
        })
    return results


def poll_news(
    n: int = 5,
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
):
    """Single entry point for the UI. Exclusively handles live GDELT API polling."""
    return _gdelt_news(
        companies=companies,
        start_date=start_date,
        end_date=end_date,
        page_size=n
    )