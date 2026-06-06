from __future__ import annotations

import datetime as dt
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

# =============================================================================
# 2. NEWS STREAM (Strictly Live API Mode - No Mock Fallbacks)
# =============================================================================
def _newsapi_news(
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
    page_size: int = 20,
):
    """Fetch live headlines from NewsAPI. No static or mock fallbacks."""
    import requests
    import datetime as dt
    import streamlit as st

    # 1. Map selected companies into an API search query
    selected = list(companies) if companies else ["Siemens", "Volkswagen", "SAP"]
    query = " OR ".join(selected)

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": config.NEWSAPI_KEY,
    }

    # 2. NewsAPI Free Tier Enforcement
    today = dt.date.today()
    thirty_days_ago = today - dt.timedelta(days=30)

    if start_date:
        if start_date < thirty_days_ago:
            # Safely clamp the date inside the fragment
            st.warning(f"⚠️ NewsAPI free tier limited to past 30 days. Clamped query to {thirty_days_ago}")
            safe_start = thirty_days_ago
        else:
            safe_start = start_date
        params["from"] = safe_start.isoformat()
    
    if end_date:
        params["to"] = end_date.isoformat()

    # 3. Direct Request
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        articles = r.json().get("articles", [])
    except requests.exceptions.HTTPError as http_err:
        st.error(f"❌ NewsAPI HTTP Error: {http_err} - {r.text}")
        return []
    except Exception as e:
        st.error(f"❌ Network connection to NewsAPI failed: {e}")
        return []

    results = []
    for a in articles:
        title = a.get("title") or ""
        
        # Match company name appearing in the title to filter results
        company = next((name for name in config.DAX40 if name.split()[0].lower() in title.lower()), "")
        
        if selected and company not in selected:
            continue
            
        results.append({
            "company": company or "DAX 40",
            "headline": title,
            "published": a.get("publishedAt", ""),
            "source": (a.get("source") or {}).get("name", "NewsAPI"),
            "source_url": a.get("url", ""),
        })
    return results


def poll_news(
    n: int = 2,
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
):
    """Single entry point for the UI. Exclusively handles live API polling."""
    import streamlit as st

    if not config.NEWSAPI_KEY:
        st.error("❌ Critical Configuration Error: NEWSAPI_KEY is missing from your .env file.")
        return []
        
    return _newsapi_news(
        companies=companies,
        start_date=start_date,
        end_date=end_date,
        page_size=n
    )