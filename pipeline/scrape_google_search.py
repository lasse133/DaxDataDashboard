"""
Fetch Google Custom Search results for DAX40 companies.

Input file:
    data/dax_companies.csv

Output file:
    data/google_search_results.csv

This script uses Google's official Custom Search JSON API. It requires two
environment variables:

    GOOGLE_API_KEY
    GOOGLE_CSE_ID

The API is optional for the project because it needs credentials. If the
variables are missing, the script prints a clear message and exits without
breaking the rest of the CSV pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

try:
    import requests
except ModuleNotFoundError:
    requests = None


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
COMPANIES_FILE = DATA_DIR / "dax_companies.csv"
OUTPUT_FILE = DATA_DIR / "google_search_results.csv"

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
REQUEST_HEADERS = {
    "User-Agent": (
        "DaxDataDashboard university project "
        "(https://github.com/lasse133/DaxDataDashboard)"
    )
}


def get_google_credentials() -> tuple[str, str]:
    """
    Read Google API credentials from environment variables.

    Credentials should not be committed to GitHub. Environment variables keep
    secrets out of the repository while still letting every teammate run the
    script with their own API key.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    search_engine_id = os.getenv("GOOGLE_CSE_ID", "").strip()

    if not api_key or not search_engine_id:
        raise RuntimeError(
            "Missing Google credentials. Set GOOGLE_API_KEY and GOOGLE_CSE_ID "
            "before running this script."
        )

    return api_key, search_engine_id


def fetch_json(url: str, params: dict[str, str]) -> dict:
    """Download JSON from an API endpoint."""
    if requests is not None:
        response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        return response.json()

    query = "&".join(f"{quote(str(key))}={quote(str(value))}" for key, value in params.items())
    request = Request(f"{url}?{query}", headers=REQUEST_HEADERS)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def build_search_query(company_name: str) -> str:
    """
    Build a risk-monitoring search query for one company.

    The terms are intentionally simple and auditable. Later, this can become a
    configurable keyword list or be replaced by a more advanced risk taxonomy.
    """
    risk_terms = [
        "risk",
        "fraud",
        "lawsuit",
        "investigation",
        "cyberattack",
        "profit warning",
    ]
    return f'"{company_name}" Germany ({" OR ".join(risk_terms)})'


def fetch_google_results_for_company(
    company_name: str,
    api_key: str,
    search_engine_id: str,
    max_results: int = 5,
) -> pd.DataFrame:
    """
    Fetch Google Custom Search results for one company.

    Google returns many fields. The project keeps a small dashboard-ready subset
    that is similar to the news CSV shape.
    """
    payload = fetch_json(
        GOOGLE_SEARCH_URL,
        params={
            "key": api_key,
            "cx": search_engine_id,
            "q": build_search_query(company_name),
            "num": str(max_results),
            "safe": "active",
        },
    )

    rows = []
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for rank, item in enumerate(payload.get("items", []), start=1):
        rows.append(
            {
                "company_name": company_name,
                "rank": rank,
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "display_link": item.get("displayLink", ""),
                "snippet": item.get("snippet", ""),
                "query": build_search_query(company_name),
                "source": "Google Custom Search JSON API",
                "scraped_at": scraped_at,
            }
        )

    return pd.DataFrame(rows)


def scrape_google_search_results() -> pd.DataFrame:
    """Fetch Google search results for all DAX companies."""
    api_key, search_engine_id = get_google_credentials()
    companies = pd.read_csv(COMPANIES_FILE)
    all_results: list[pd.DataFrame] = []

    for company_name in companies["company_name"]:
        print(f"Fetching Google search results for {company_name}...")
        company_results = fetch_google_results_for_company(
            company_name=company_name,
            api_key=api_key,
            search_engine_id=search_engine_id,
        )

        if not company_results.empty:
            all_results.append(company_results)

        # The free tier is limited, so keep this gentle.
        time.sleep(0.2)

    columns = [
        "company_name",
        "rank",
        "title",
        "url",
        "display_link",
        "snippet",
        "query",
        "source",
        "scraped_at",
    ]

    if not all_results:
        return pd.DataFrame(columns=columns)

    results = pd.concat(all_results, ignore_index=True)[columns]
    return results.drop_duplicates(subset=["url"]).reset_index(drop=True)


def save_google_search_results(results: pd.DataFrame) -> None:
    """Create the data folder if needed and save Google search results."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")


def main() -> None:
    """Run Google search scraping if credentials are available."""
    try:
        results = scrape_google_search_results()
    except RuntimeError as error:
        print(f"WARNING: {error}")
        print("Google search scraping was skipped.")
        return

    save_google_search_results(results)
    print(f"Saved {len(results)} Google search rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
