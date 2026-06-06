from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable

import config

PROJECT_ROOT = Path(__file__).resolve().parent
STOCK_PRICES_FILE = PROJECT_ROOT / "data" / "stock_prices.csv"


# =============================================================================
# 1. STOCK PRICES  (live, no API key required, fallback to CSV if offline)
# =============================================================================
def get_prices(tickers: Iterable[str], start_date=None):
    import yfinance as yf

    out = {}
    tickers = list(tickers)
    price_start_date = start_date or config.PRICE_START_DATE
    try:
        data = yf.download(
            tickers=tickers,
            start=price_start_date,
            period=None if price_start_date else config.PRICE_LOOKBACK,
            interval=config.PRICE_INTERVAL,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[get_prices] download failed: {e}")
        return _get_cached_prices(tickers, start_date=price_start_date)

    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            closes = df["Close"].dropna()
            if closes.empty:
                continue
            last = float(closes.iloc[-1])
            first = float(closes.iloc[0])
            pct = (last - first) / first * 100 if first else 0.0
            out[t] = {"last": last, "pct_change": pct, "history": closes}
        except Exception:  # noqa: BLE001
            continue
    return out or _get_cached_prices(tickers, start_date=price_start_date)


def _get_cached_prices(tickers: Iterable[str], start_date=None):
    if not STOCK_PRICES_FILE.exists():
        return {}

    import pandas as pd

    try:
        stock_prices = pd.read_csv(STOCK_PRICES_FILE)
    except Exception:
        return {}

    stock_prices["date"] = pd.to_datetime(stock_prices["date"])
    if start_date:
        stock_prices = stock_prices[
            stock_prices["date"] >= pd.to_datetime(start_date)
        ]

    out = {}
    for ticker in tickers:
        company_prices = stock_prices[
            stock_prices["yahoo_ticker"].eq(ticker)
        ].sort_values("date")
        if company_prices.empty:
            continue
        closes = company_prices.set_index("date")["close"].dropna()
        if closes.empty:
            continue
        last = float(closes.iloc[-1])
        first = float(closes.iloc[0])
        pct = (last - first) / first * 100 if first else 0.0
        out[ticker] = {"last": last, "pct_change": pct, "history": closes}
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
            # Fixed: Changed to a local st.warning to stay inside fragment scope safely
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