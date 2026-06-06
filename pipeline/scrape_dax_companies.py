"""
Fetch the current DAX40 company list and save it as a CSV file.

This script is the first data-layer building block for the
DAX40 Risk Monitoring Dashboard. It updates a reusable company master file at:

    data/dax_companies.csv

The dashboard itself should read from that CSV instead of scraping live every
time it opens. That keeps the project reproducible and gives later scripts a
stable fallback if the online source is temporarily unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen

import pandas as pd

try:
    import requests
except ModuleNotFoundError:
    requests = None


# Keep project paths in one place so they are easy to change later.
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "dax_companies.csv"

# STOXX administers DAX and is therefore the preferred source for this project.
# The components page includes company names and a Supersector classification.
STOXX_DAX_COMPONENTS_URL = "https://stoxx.com/index/daxk/?components=true"

# Wikipedia remains a useful fallback because it is public and simple to parse
# with pandas. The dashboard will still use the saved CSV if both live sources
# fail, so demos and later scripts stay reproducible.
WIKIPEDIA_DAX_URL = "https://en.wikipedia.org/wiki/DAX"
STOXX_SOURCE_NAME = "STOXX DAX components page"
WIKIPEDIA_SOURCE_NAME = "Wikipedia DAX constituents table"

# Some websites block default Python user agents. A clear user agent makes the
# request more transparent and avoids the common "HTTP 403 Forbidden" issue.
REQUEST_HEADERS = {
    "User-Agent": (
        "DaxDataDashboard university project "
        "(https://github.com/lasse133/DaxDataDashboard)"
    )
}


def fetch_html(url: str) -> str:
    """
    Download a web page and return its HTML.

    The project requirements include requests, so that is the preferred path.
    The urllib fallback keeps the script runnable in minimal environments where
    pandas is installed but requests has not been installed yet.
    """
    if requests is not None:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        return response.text

    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def clean_column_name(column: object) -> str:
    """
    Convert a table column name into a simple string.

    pandas sometimes reads HTML table headers as tuples when a table has grouped
    headings. Flattening them here makes the later column matching simpler.
    """
    if isinstance(column, tuple):
        parts = [
            str(part).strip()
            for part in column
            if str(part).strip() and not str(part).startswith("Unnamed:")
        ]
        return " ".join(dict.fromkeys(parts))

    return str(column).strip()


def find_column(columns: Iterable[str], possible_names: Iterable[str]) -> str | None:
    """
    Find a column by checking several possible names.

    Web tables sometimes change column headings slightly. This helper keeps the
    scraping function readable and makes small source changes less painful.
    """
    normalized_columns = {str(column).strip().lower(): column for column in columns}

    for name in possible_names:
        match = normalized_columns.get(name.lower())
        if match is not None:
            return match

    return None


def clean_company_name(company_name: str) -> str:
    """
    Clean company names from web sources without changing their meaning.

    We keep the source spelling because title-casing would break names such as
    SAP, BASF, E.ON, and BMW.
    """
    return str(company_name).strip()


def build_output_frame(company_names: pd.Series, sectors: pd.Series | str, source: str) -> pd.DataFrame:
    """
    Build the final CSV shape used by the rest of the project.

    The company layer intentionally does not include Yahoo Finance symbols.
    Stock scripts can map companies to provider-specific tickers separately.
    """
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    companies = pd.DataFrame(
        {
            "company_name": company_names.astype(str).map(clean_company_name),
            "sector": (
                sectors.astype(str).str.strip()
                if isinstance(sectors, pd.Series)
                else sectors
            ),
            "source": source,
            "scraped_at": scraped_at,
        }
    )

    companies = companies[companies["company_name"].ne("")]
    return companies[["company_name", "sector", "source", "scraped_at"]].reset_index(drop=True)


def scrape_dax_companies_from_stoxx() -> pd.DataFrame:
    """
    Scrape the DAX components from STOXX.

    STOXX is preferred over Wikipedia because STOXX administers DAX and the
    public components page includes a Supersector field that we can use as the
    project's sector column.
    """
    tables = pd.read_html(StringIO(fetch_html(STOXX_DAX_COMPONENTS_URL)))

    for table in tables:
        table = table.copy()
        table.columns = [clean_column_name(column) for column in table.columns]

        company_column = find_column(table.columns, ["Company"])
        sector_column = find_column(table.columns, ["Supersector", "Sector", "Industry"])

        if company_column is not None and sector_column is not None:
            return build_output_frame(
                company_names=table[company_column],
                sectors=table[sector_column],
                source=STOXX_SOURCE_NAME,
            )

    raise ValueError("Could not find a STOXX DAX components table with Company and Supersector columns.")


def scrape_dax_companies_from_wikipedia() -> pd.DataFrame:
    """
    Scrape the current DAX constituents table from Wikipedia.

    Returns:
        A pandas DataFrame with exactly the columns used by the rest of the
        project:
        - company_name
        - sector
        - source
        - scraped_at
    """
    # pandas can parse HTML tables directly from text. StringIO avoids a pandas
    # deprecation warning about passing literal HTML strings.
    tables = pd.read_html(StringIO(fetch_html(WIKIPEDIA_DAX_URL)))

    dax_table = None
    company_column = None
    sector_column = None

    # Search through all tables on the page because table order can change.
    for table in tables:
        table = table.copy()
        table.columns = [clean_column_name(column) for column in table.columns]

        company_column = find_column(
            table.columns,
            ["Company", "Name", "Company name"],
        )
        sector_column = find_column(
            table.columns,
            ["Industry", "Sector", "Prime Standard industry group"],
        )

        if company_column is not None:
            dax_table = table
            break

    if dax_table is None or company_column is None:
        raise ValueError("Could not find a DAX constituents table with a company column.")

    return build_output_frame(
        company_names=dax_table[company_column],
        sectors=dax_table[sector_column] if sector_column is not None else "",
        source=WIKIPEDIA_SOURCE_NAME,
    )


def scrape_dax_companies() -> pd.DataFrame:
    """
    Try the best available live source first, then fall back to Wikipedia.

    Keeping this source-selection logic in one function means later scripts only
    need to call scrape_dax_companies(), even if we replace or improve sources.
    """
    try:
        print("Trying STOXX DAX components source...")
        return scrape_dax_companies_from_stoxx()
    except Exception as error:
        print(f"WARNING: STOXX scraping failed: {error}")
        print("Trying Wikipedia fallback source...")
        return scrape_dax_companies_from_wikipedia()


def validate_dax_companies(companies: pd.DataFrame) -> list[str]:
    """
    Run basic quality checks and return warning messages.

    These checks do not stop the script. They print warnings so a human can see
    possible data problems while still getting a CSV file for reproducibility.
    """
    warnings: list[str] = []

    if len(companies) != 40:
        warnings.append(f"Expected 40 DAX companies, but found {len(companies)}.")

    if companies["company_name"].isna().any() or companies["company_name"].eq("").any():
        warnings.append("At least one row has a missing company name.")

    duplicate_companies = companies.loc[
        companies["company_name"].duplicated(keep=False),
        "company_name",
    ].dropna()

    if not duplicate_companies.empty:
        duplicates = ", ".join(sorted(duplicate_companies.unique()))
        warnings.append(f"Duplicate company names found: {duplicates}.")

    if "sector" in companies.columns and (
        companies["sector"].isna().any() or companies["sector"].eq("").any()
    ):
        warnings.append("At least one row has a missing sector.")

    return warnings


def load_existing_csv() -> pd.DataFrame:
    """
    Load the previously saved CSV if live scraping fails.

    This fallback is important because later dashboard steps should still work
    during demos, reviews, or offline development.
    """
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"Live scraping failed and no fallback CSV exists at {OUTPUT_FILE}."
        )

    print(f"Loading fallback data from {OUTPUT_FILE}")
    return pd.read_csv(OUTPUT_FILE)


def save_companies(companies: pd.DataFrame) -> None:
    """Create the data folder if needed and save the company list as CSV."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    companies.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")


def main() -> None:
    """Run the scraper, validate the result, and save the CSV file."""
    try:
        print("Fetching current DAX company list...")
        companies = scrape_dax_companies()
        used_fallback = False
    except Exception as error:
        print(f"WARNING: Dynamic scraping failed: {error}")
        companies = load_existing_csv()
        used_fallback = True

    warnings = validate_dax_companies(companies)
    for warning in warnings:
        print(f"WARNING: {warning}")

    if not used_fallback:
        save_companies(companies)
        print(f"Saved {len(companies)} companies to {OUTPUT_FILE}")
    else:
        print(f"Using existing fallback CSV with {len(companies)} companies.")


if __name__ == "__main__":
    main()
