"""
Fetch recent news/search results for DAX40 companies with the GDELT API.

Input file:
    data/dax_companies.csv

Output file:
    data/company_news.csv

Google News RSS is useful for an MVP because it is public, searchable, and does
not need an API key. A paid news API can replace this script later while keeping
the same CSV output shape for the dashboard and risk-signal layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import html
import json
import re
import time

import pandas as pd

try:
    import requests
except ModuleNotFoundError:
    requests = None


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
COMPANIES_FILE = DATA_DIR / "dax_companies.csv"
OUTPUT_FILE = DATA_DIR / "company_news.csv"

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
REQUEST_HEADERS = {
    "User-Agent": (
        "DaxDataDashboard university project "
        "(https://github.com/lasse133/DaxDataDashboard)"
    )
}


def clean_text(value: str) -> str:
    """Convert small HTML snippets from RSS feeds into readable plain text."""
    without_tags = re.sub(r"<[^>]+>", " ", str(value))
    return " ".join(html.unescape(without_tags).split())


def fetch_json(url: str, params: dict[str, str], retries: int = 0) -> dict:
    """Download JSON from an API endpoint."""
    for attempt in range(retries + 1):
        try:
            if requests is not None:
                response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=30)
                response.raise_for_status()
                return response.json()

            query = "&".join(f"{quote(str(key))}={quote(str(value))}" for key, value in params.items())
            request = Request(f"{url}?{query}", headers=REQUEST_HEADERS)
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code != 429 or attempt == retries:
                raise

            wait_seconds = 5 * (attempt + 1)
            print(f"WARNING: GDELT rate limit hit. Waiting {wait_seconds} seconds...")
            time.sleep(wait_seconds)

    return {}


def fetch_text(url: str, params: dict[str, str]) -> str:
    """Download plain text from an API or RSS endpoint."""
    if requests is not None:
        response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=10)
        response.raise_for_status()
        return response.text

    query = "&".join(f"{quote(str(key))}={quote(str(value))}" for key, value in params.items())
    request = Request(f"{url}?{query}", headers=REQUEST_HEADERS)
    with urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def build_company_query(company_name: str) -> str:
    """
    Build a focused GDELT query for one company.

    Quoting the company name reduces unrelated search results. Adding Germany
    makes the query more relevant for DAX monitoring.
    """
    return f'"{company_name}" Germany'


def fetch_news_for_company_from_gdelt(company_name: str, max_records: int = 3) -> pd.DataFrame:
    """
    Fetch recent news articles for one company.

    GDELT returns many fields. The project only needs a stable, dashboard-ready
    subset: title, URL, source, publication date, language, and snippet.
    """
    payload = fetch_json(
        GDELT_DOC_API_URL,
        params={
            "query": build_company_query(company_name),
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(max_records),
            "sort": "datedesc",
        },
    )

    articles = payload.get("articles", [])
    rows = []

    for article in articles:
        rows.append(
            {
                "company_name": company_name,
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "news_source": article.get("sourceCommonName", ""),
                "published_at": article.get("seendate", ""),
                "language": article.get("language", ""),
                "snippet": article.get("snippet", ""),
                "source": "GDELT Doc API",
                "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    return pd.DataFrame(rows)


def fetch_news_for_company_from_google_rss(company_name: str, max_records: int = 3) -> pd.DataFrame:
    """
    Fetch recent news results from Google News RSS.

    This is a fallback for development environments where GDELT is rate-limited.
    It is still a public search/news result source, not a paid news database.
    """
    rss_text = fetch_text(
        GOOGLE_NEWS_RSS_URL,
        params={
            "q": build_company_query(company_name),
            "hl": "en",
            "gl": "DE",
            "ceid": "DE:en",
        },
    )

    root = ET.fromstring(rss_text)
    rows = []

    for item in root.findall("./channel/item")[:max_records]:
        source = item.find("source")
        rows.append(
            {
                "company_name": company_name,
                "title": clean_text(item.findtext("title", default="")),
                "url": item.findtext("link", default=""),
                "news_source": clean_text(source.text if source is not None else ""),
                "published_at": item.findtext("pubDate", default=""),
                "language": "en",
                "snippet": clean_text(item.findtext("description", default="")),
                "source": "Google News RSS",
                "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    return pd.DataFrame(rows)


def fetch_news_for_company(company_name: str) -> pd.DataFrame:
    """
    Fetch recent news for one company.

    Google News RSS is the default because it is fast enough for the full DAX40
    list in a classroom/project environment. The GDELT helper above is kept so
    the source can be switched later without changing the CSV shape.
    """
    return fetch_news_for_company_from_google_rss(company_name)


def scrape_company_news() -> pd.DataFrame:
    """Fetch recent news for all DAX companies."""
    companies = pd.read_csv(COMPANIES_FILE)
    all_news: list[pd.DataFrame] = []

    for company_name in companies["company_name"]:
        print(f"Fetching news for {company_name}...")
        try:
            company_news = fetch_news_for_company(company_name)
        except Exception as error:
            print(f"WARNING: Could not fetch news for {company_name}: {error}")
            company_news = pd.DataFrame()

        if not company_news.empty:
            all_news.append(company_news)

        # Keep requests gentle because this loops over 40 companies.
        time.sleep(0.2)

    columns = [
        "company_name",
        "title",
        "url",
        "news_source",
        "published_at",
        "language",
        "snippet",
        "source",
        "scraped_at",
    ]

    if not all_news:
        return pd.DataFrame(columns=columns)

    news = pd.concat(all_news, ignore_index=True)[columns]
    return news.drop_duplicates(subset=["url"]).reset_index(drop=True)


def load_existing_csv() -> pd.DataFrame:
    """Use the last saved news CSV if live fetching fails."""
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"News scraping failed and no fallback CSV exists at {OUTPUT_FILE}."
        )

    print(f"Loading fallback data from {OUTPUT_FILE}")
    return pd.read_csv(OUTPUT_FILE)


def validate_company_news(news: pd.DataFrame) -> list[str]:
    """Return simple data-quality warnings for the news CSV."""
    warnings: list[str] = []

    if news.empty:
        warnings.append("No news rows were collected.")

    if not news.empty and news["url"].duplicated().any():
        warnings.append("Duplicate news URLs were found.")

    company_count = news["company_name"].nunique() if not news.empty else 0
    if company_count < 40:
        warnings.append(f"Found news for {company_count} of 40 companies.")

    return warnings


def save_company_news(news: pd.DataFrame) -> None:
    """Create the data folder if needed and save company news."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    news.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")


def main() -> None:
    """Run the news scraper and save its output."""
    try:
        news = scrape_company_news()
        used_fallback = False
    except Exception as error:
        print(f"WARNING: News scraping failed: {error}")
        news = load_existing_csv()
        used_fallback = True

    for warning in validate_company_news(news):
        print(f"WARNING: {warning}")

    if not used_fallback:
        save_company_news(news)
        print(f"Saved {len(news)} news rows to {OUTPUT_FILE}")
    else:
        print(f"Using existing fallback CSV with {len(news)} news rows.")


if __name__ == "__main__":
    main()
