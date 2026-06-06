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
from pathlib import Path
from typing import Iterable

import config


PROJECT_ROOT = Path(__file__).resolve().parent
COMPANY_NEWS_FILE = PROJECT_ROOT / "data" / "company_news.csv"
STOCK_PRICES_FILE = PROJECT_ROOT / "data" / "stock_prices.csv"
NEWS_EXCLUDE_TERMS = [
    "betting",
    "bundesliga",
    "football",
    "leverkusen",
    "prediction",
    "soccer",
    " vs ",
]


# =============================================================================
# 1. STOCK PRICES  (live, no API key required)
# =============================================================================
def get_prices(tickers: Iterable[str], start_date=None):
    """
    Return a dict: ticker -> {"last": float, "pct_change": float, "history": DataFrame}
    Uses yfinance, which needs no API key. Wrapped in try/except so a network
    hiccup never crashes the dashboard.
    """
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
    return out or _get_cached_prices(tickers, start_date=price_start_date)


def _get_cached_prices(tickers: Iterable[str], start_date=None):
    """Fallback to the project CSV so demos still show 2026 prices offline."""
    if not STOCK_PRICES_FILE.exists():
        return {}

    import pandas as pd

    try:
        stock_prices = pd.read_csv(STOCK_PRICES_FILE)
    except Exception as e:  # noqa: BLE001
        print(f"[cached_prices] CSV read failed: {e}")
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


def _normalise_company_name(name: str) -> str:
    return " ".join(str(name).lower().replace("-", " ").split())


def _display_company_name(name: str) -> str:
    normalised = _normalise_company_name(name)
    for display_name in config.DAX40:
        if _normalise_company_name(display_name) == normalised:
            return display_name
    return str(name).title()


def _clean_headline(text: str) -> str:
    """Keep cached headlines compact and browser-display friendly."""
    return " ".join(str(text).split())


def _is_relevant_news_row(row) -> bool:
    title = _normalise_company_name(row.get("title", ""))
    company_first_word = _normalise_company_name(row.get("company_name", "")).split()[0]
    if company_first_word not in title:
        return False
    return not any(term in f" {title} " for term in NEWS_EXCLUDE_TERMS)


def _to_datetime(value):
    if value is None:
        return None
    try:
        return dt.datetime.combine(value, dt.time.min)
    except TypeError:
        pass
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    try:
        parsed = dt.datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def _filter_news_by_date(news, start_date=None, end_date=None):
    if "published_at" not in news.columns:
        return news

    import pandas as pd

    start = _to_datetime(start_date)
    end = _to_datetime(end_date)
    published = pd.to_datetime(news["published_at"], errors="coerce", utc=True)
    published = published.dt.tz_convert(None)

    if start is not None:
        news = news[published >= start]
        published = published[published >= start]
    if end is not None:
        end_exclusive = end + dt.timedelta(days=1)
        news = news[published < end_exclusive]
    return news


def _csv_mock_news(
    n: int = 2,
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
):
    """Use cached scraped news with real URLs when available."""
    if not COMPANY_NEWS_FILE.exists():
        return []

    import pandas as pd

    selected = {_normalise_company_name(company) for company in companies or []}
    try:
        news = pd.read_csv(COMPANY_NEWS_FILE)
    except Exception as e:  # noqa: BLE001
        print(f"[mock_news] cached CSV read failed: {e}")
        return []

    if selected:
        news = news[
            news["company_name"].apply(_normalise_company_name).isin(selected)
        ]
    news = _filter_news_by_date(news, start_date=start_date, end_date=end_date)
    if news.empty:
        return []

    relevant_news = news[
        news.apply(_is_relevant_news_row, axis=1)
    ]
    if not relevant_news.empty:
        news = relevant_news

    picks = news.sample(n=min(n, len(news))).to_dict("records")
    now = dt.datetime.now().isoformat(timespec="seconds")
    return [
        {
            "published": row.get("published_at") or now,
            "company": _display_company_name(row.get("company_name", "")),
            "headline": _clean_headline(row.get("title", "")),
            "source": row.get("source", "Cached news"),
            "source_url": row.get("url", ""),
        }
        for row in picks
        if row.get("title")
    ]


def _mock_news(
    n: int = 2,
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
):
    """Emit cached or fallback headlines with a fresh timestamp."""
    cached = _csv_mock_news(
        n=n,
        companies=companies,
        start_date=start_date,
        end_date=end_date,
    )
    if cached:
        return cached
    if start_date or end_date:
        return []

    now = dt.datetime.now()
    selected = set(companies or [])
    templates = [
        item for item in _MOCK_TEMPLATES
        if not selected or item[0] in selected
    ]
    picks = random.sample(templates, k=min(n, len(templates)))
    return [
        {"company": company, "headline": text, "published": now.isoformat(timespec="seconds"),
         "source": "Simulated mock headline", "source_url": ""}
        for company, text in picks
    ]


# ---- 2b. REAL stream (NewsAPI) ----------------------------------------------
def _newsapi_news(
    companies: Iterable[str] | None = None,
    page_size: int = 10,
    start_date=None,
    end_date=None,
):
    """Fetch live headlines from NewsAPI. Requires config.NEWSAPI_KEY."""
    import requests

    selected = list(companies or [])
    query = " OR ".join(selected) if selected else "DAX OR Siemens OR Volkswagen OR SAP"
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": config.NEWSAPI_KEY,
    }
    if start_date:
        params["from"] = str(start_date)
    if end_date:
        params["to"] = str(end_date)
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        articles = r.json().get("articles", [])
    except Exception as e:  # noqa: BLE001
        print(f"[newsapi] fetch failed, falling back to mock: {e}")
        return _mock_news(
            companies=companies,
            start_date=start_date,
            end_date=end_date,
        )

    results = []
    for a in articles:
        title = a.get("title") or ""
        # naive company tagging: match any DAX name appearing in the title
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
    """
    Single entry point for the UI. Returns a list of headline dicts.
    Automatically uses NewsAPI when a key is configured, else the mock stream.
    """
    if config.NEWSAPI_KEY:
        return _newsapi_news(
            companies=companies,
            page_size=n * 4,
            start_date=start_date,
            end_date=end_date,
        )
    return _mock_news(
        n,
        companies=companies,
        start_date=start_date,
        end_date=end_date,
    )
