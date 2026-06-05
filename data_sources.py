"""
data_sources.py
---------------
The "Ingest" layer of the pipeline.

Two responsibilities:
  1. get_prices()      -> live intraday stock data for DAX 40 names (yfinance, no key)
  2. poll_news()       -> a stream of fresh headlines (mock by default, NewsAPI if a key is set)

Both functions return plain Python data so the NLP and UI layers don't care
where the data came from.
"""

from __future__ import annotations

import random
import datetime as dt
from typing import Iterable

import config


# =============================================================================
# 1. STOCK PRICES  (live, no API key required)
# =============================================================================
def get_prices(tickers: Iterable[str]):
    """
    Return a dict: ticker -> {"last": float, "pct_change": float, "history": DataFrame}
    Uses yfinance, which needs no API key. Wrapped in try/except so a network
    hiccup never crashes the dashboard.
    """
    import yfinance as yf

    out = {}
    tickers = list(tickers)
    try:
        data = yf.download(
            tickers=tickers,
            period=config.PRICE_LOOKBACK,
            interval=config.PRICE_INTERVAL,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[get_prices] download failed: {e}")
        return out

    for t in tickers:
        try:
            # yfinance nests columns by ticker when downloading multiple symbols
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
    return out


# =============================================================================
# 2. NEWS STREAM
# =============================================================================
# ---- 2a. MOCK stream (default: runs with zero setup) ------------------------
_MOCK_TEMPLATES = [
    ("Siemens", "Siemens faces delays in major infrastructure project amid supply chain bottlenecks"),
    ("Bayer", "Bayer hit with new lawsuit over product liability, shares slide"),
    ("Volkswagen", "Volkswagen issues profit warning as demand in China weakens"),
    ("SAP", "SAP raises full-year guidance on strong cloud revenue growth"),
    ("Deutsche Bank", "Deutsche Bank under regulatory probe over compliance failures"),
    ("BASF", "BASF announces plant production halt due to rising energy costs"),
    ("Adidas", "Adidas reports record quarterly sales, beating expectations"),
    ("Infineon", "Infineon warns of chip shortage impacting automotive customers"),
    ("Mercedes-Benz", "Mercedes-Benz recalls vehicles over safety defect, faces fine"),
    ("Allianz", "Allianz posts solid profit, raises dividend for shareholders"),
    ("RWE", "RWE faces scrutiny over emissions targets and climate disclosures"),
    ("Continental", "Continental announces strike at German plant, output disrupted"),
]


def _mock_news(n: int = 2):
    """Emit `n` random headlines with a fresh timestamp, simulating a live feed."""
    now = dt.datetime.now()
    picks = random.sample(_MOCK_TEMPLATES, k=min(n, len(_MOCK_TEMPLATES)))
    return [
        {"company": company, "headline": text, "published": now.isoformat(timespec="seconds"),
         "source": "MockWire"}
        for company, text in picks
    ]


# ---- 2b. REAL stream (NewsAPI) ----------------------------------------------
def _newsapi_news(query: str = "DAX OR Siemens OR Volkswagen OR SAP", page_size: int = 10):
    """Fetch live headlines from NewsAPI. Requires config.NEWSAPI_KEY."""
    import requests

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": config.NEWSAPI_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        articles = r.json().get("articles", [])
    except Exception as e:  # noqa: BLE001
        print(f"[newsapi] fetch failed, falling back to mock: {e}")
        return _mock_news()

    results = []
    for a in articles:
        title = a.get("title") or ""
        # naive company tagging: match any DAX name appearing in the title
        company = next((name for name in config.DAX40 if name.split()[0].lower() in title.lower()), "DAX 40")
        results.append({
            "company": company,
            "headline": title,
            "published": a.get("publishedAt", ""),
            "source": (a.get("source") or {}).get("name", "NewsAPI"),
        })
    return results


def poll_news(n: int = 2):
    """
    Single entry point for the UI. Returns a list of headline dicts.
    Automatically uses NewsAPI when a key is configured, else the mock stream.
    """
    if config.NEWSAPI_KEY:
        return _newsapi_news(page_size=n * 4)  # fetch more; UI dedupes
    return _mock_news(n)
