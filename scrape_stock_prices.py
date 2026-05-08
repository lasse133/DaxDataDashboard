"""
Fetch recent stock market data for DAX40 companies from Yahoo Finance.

Input files:
    data/dax_companies.csv
    data/yahoo_ticker_mapping.csv

Output file:
    data/stock_prices.csv

This script intentionally keeps Yahoo tickers outside dax_companies.csv. The
company list is an index-membership layer; the ticker mapping belongs to the
stock-data layer and can be replaced if another data provider is used later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import json
import time

import pandas as pd

try:
    import requests
except ModuleNotFoundError:
    requests = None


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
COMPANIES_FILE = DATA_DIR / "dax_companies.csv"
TICKER_MAPPING_FILE = DATA_DIR / "yahoo_ticker_mapping.csv"
OUTPUT_FILE = DATA_DIR / "stock_prices.csv"

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
REQUEST_HEADERS = {
    "User-Agent": (
        "DaxDataDashboard university project "
        "(https://github.com/lasse133/DaxDataDashboard)"
    )
}


def fetch_json(url: str, params: dict[str, str] | None = None) -> dict:
    """
    Download JSON from an API endpoint.

    requests is easier to read, but urllib keeps the script usable in minimal
    Python environments before all requirements are installed.
    """
    if requests is not None:
        response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        return response.json()

    if params:
        query = "&".join(f"{quote(str(key))}={quote(str(value))}" for key, value in params.items())
        url = f"{url}?{query}"

    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_company_tickers() -> pd.DataFrame:
    """
    Combine the DAX company list with the Yahoo ticker mapping.

    Keeping this merge explicit makes missing ticker mappings easy to detect.
    """
    companies = pd.read_csv(COMPANIES_FILE)
    ticker_mapping = pd.read_csv(TICKER_MAPPING_FILE)

    merged = companies.merge(ticker_mapping, on="company_name", how="left")
    missing = merged[merged["yahoo_ticker"].isna()]

    if not missing.empty:
        missing_names = ", ".join(missing["company_name"].astype(str))
        raise ValueError(f"Missing Yahoo ticker mapping for: {missing_names}")

    return merged


def fetch_yahoo_price_history(yahoo_ticker: str, range_value: str = "3mo") -> pd.DataFrame:
    """
    Fetch daily OHLCV prices for one Yahoo Finance ticker.

    OHLCV means open, high, low, close, and volume. These fields are enough for
    simple volatility, price-drop, and volume-spike risk signals.
    """
    url = YAHOO_CHART_URL.format(symbol=quote(yahoo_ticker))
    payload = fetch_json(
        url,
        params={
            "range": range_value,
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        },
    )

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(chart["error"])

    result = chart.get("result", [])
    if not result:
        raise ValueError(f"No chart data returned for {yahoo_ticker}")

    timestamps = result[0].get("timestamp", [])
    quote_data = result[0].get("indicators", {}).get("quote", [{}])[0]

    rows = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, unit="s", utc=True).date,
            "open": quote_data.get("open", []),
            "high": quote_data.get("high", []),
            "low": quote_data.get("low", []),
            "close": quote_data.get("close", []),
            "volume": quote_data.get("volume", []),
        }
    )

    return rows.dropna(subset=["close"]).reset_index(drop=True)


def scrape_stock_prices() -> pd.DataFrame:
    """Fetch recent stock prices for all mapped DAX companies."""
    companies = load_company_tickers()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_prices: list[pd.DataFrame] = []

    for _, company in companies.iterrows():
        company_name = company["company_name"]
        yahoo_ticker = company["yahoo_ticker"]
        print(f"Fetching stock prices for {company_name} ({yahoo_ticker})...")

        prices = fetch_yahoo_price_history(yahoo_ticker)
        prices.insert(0, "company_name", company_name)
        prices.insert(1, "yahoo_ticker", yahoo_ticker)
        prices["source"] = "Yahoo Finance chart API"
        prices["scraped_at"] = scraped_at
        all_prices.append(prices)

        # A tiny pause is polite and helps avoid rate-limit surprises.
        time.sleep(0.2)

    return pd.concat(all_prices, ignore_index=True)


def load_existing_csv() -> pd.DataFrame:
    """Use the last saved stock CSV if live fetching fails."""
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"Stock scraping failed and no fallback CSV exists at {OUTPUT_FILE}."
        )

    print(f"Loading fallback data from {OUTPUT_FILE}")
    return pd.read_csv(OUTPUT_FILE)


def validate_stock_prices(stock_prices: pd.DataFrame) -> list[str]:
    """Return simple data-quality warnings for the stock-price CSV."""
    warnings: list[str] = []

    if stock_prices.empty:
        warnings.append("No stock price rows were collected.")

    missing_close = stock_prices["close"].isna().sum()
    if missing_close:
        warnings.append(f"{missing_close} rows have missing close prices.")

    missing_volume = stock_prices["volume"].isna().sum()
    if missing_volume:
        warnings.append(f"{missing_volume} rows have missing volume values.")

    company_count = stock_prices["company_name"].nunique()
    if company_count != 40:
        warnings.append(f"Expected stock data for 40 companies, but found {company_count}.")

    return warnings


def save_stock_prices(stock_prices: pd.DataFrame) -> None:
    """Create the data folder if needed and save stock prices."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stock_prices.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")


def main() -> None:
    """Run the stock scraper and save its output."""
    try:
        stock_prices = scrape_stock_prices()
        used_fallback = False
    except Exception as error:
        print(f"WARNING: Stock scraping failed: {error}")
        stock_prices = load_existing_csv()
        used_fallback = True

    for warning in validate_stock_prices(stock_prices):
        print(f"WARNING: {warning}")

    if not used_fallback:
        save_stock_prices(stock_prices)
        print(f"Saved {len(stock_prices)} stock price rows to {OUTPUT_FILE}")
    else:
        print(f"Using existing fallback CSV with {len(stock_prices)} stock price rows.")


if __name__ == "__main__":
    main()
