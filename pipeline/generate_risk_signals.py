"""
Generate simple audit-planning risk signals from stock and news data.

Input files:
    data/dax_companies.csv
    data/stock_prices.csv
    data/company_news.csv

Output file:
    data/risk_signals.csv

The rules here are intentionally simple and explainable. That is useful for a
university project and for auditors, because each signal can be traced back to
the exact data point that caused it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
COMPANIES_FILE = DATA_DIR / "dax_companies.csv"
STOCK_PRICES_FILE = DATA_DIR / "stock_prices.csv"
COMPANY_NEWS_FILE = DATA_DIR / "company_news.csv"
GOOGLE_SEARCH_FILE = DATA_DIR / "google_search_results.csv"
OUTPUT_FILE = DATA_DIR / "risk_signals.csv"

NEGATIVE_KEYWORDS = [
    "bankruptcy",
    "bribery",
    "corruption",
    "cyberattack",
    "downgrade",
    "fraud",
    "investigation",
    "lawsuit",
    "layoffs",
    "loss",
    "probe",
    "profit warning",
    "recall",
    "scandal",
    "sanction",
    "short seller",
    "warning",
]


def add_signal(
    signals: list[dict],
    company_name: str,
    risk_type: str,
    risk_score: int,
    signal_text: str,
    evidence: str,
) -> None:
    """Append one risk signal in the shared output format."""
    signals.append(
        {
            "company_name": company_name,
            "risk_type": risk_type,
            "risk_score": risk_score,
            "signal_text": signal_text,
            "evidence": evidence,
            "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )


def generate_stock_signals(stock_prices: pd.DataFrame) -> list[dict]:
    """
    Create risk signals from price and volume movements.

    Current thresholds:
    - daily close-to-close price drop of 5% or more
    - latest volume at least twice the company's average daily volume
    """
    signals: list[dict] = []

    stock_prices = stock_prices.copy()
    stock_prices["date"] = pd.to_datetime(stock_prices["date"])
    stock_prices = stock_prices.sort_values(["company_name", "date"])

    for company_name, company_prices in stock_prices.groupby("company_name"):
        company_prices = company_prices.copy()
        company_prices["daily_return"] = company_prices["close"].pct_change()

        large_drops = company_prices[company_prices["daily_return"] <= -0.05]
        for _, row in large_drops.iterrows():
            percent_drop = row["daily_return"] * 100
            add_signal(
                signals,
                company_name=company_name,
                risk_type="stock_price_drop",
                risk_score=80,
                signal_text=f"Daily closing price dropped by {percent_drop:.1f}%.",
                evidence=f"Date: {row['date'].date()}, close: {row['close']:.2f}",
            )

        average_volume = company_prices["volume"].mean()
        latest_row = company_prices.iloc[-1]

        if average_volume and latest_row["volume"] >= average_volume * 2:
            volume_ratio = latest_row["volume"] / average_volume
            add_signal(
                signals,
                company_name=company_name,
                risk_type="volume_spike",
                risk_score=65,
                signal_text=f"Latest trading volume is {volume_ratio:.1f}x the recent average.",
                evidence=f"Date: {latest_row['date'].date()}, volume: {latest_row['volume']:.0f}",
            )

    return signals


def generate_news_signals(company_news: pd.DataFrame) -> list[dict]:
    """Create risk signals from negative keywords in recent news results."""
    signals: list[dict] = []

    for _, row in company_news.iterrows():
        title = str(row.get("title", ""))
        snippet = str(row.get("snippet", ""))
        searchable_text = f"{title} {snippet}".lower()

        matched_keywords = [
            keyword for keyword in NEGATIVE_KEYWORDS if keyword in searchable_text
        ]

        if matched_keywords:
            score = min(90, 50 + len(matched_keywords) * 10)
            add_signal(
                signals,
                company_name=row["company_name"],
                risk_type="negative_news_keyword",
                risk_score=score,
                signal_text=f"News result matched risk keyword(s): {', '.join(matched_keywords)}.",
                evidence=f"{title} | {row.get('url', '')}",
            )

    return signals


def generate_google_search_signals(search_results: pd.DataFrame) -> list[dict]:
    """Create risk signals from negative keywords in Google search results."""
    signals: list[dict] = []

    for _, row in search_results.iterrows():
        title = str(row.get("title", ""))
        snippet = str(row.get("snippet", ""))
        searchable_text = f"{title} {snippet}".lower()

        matched_keywords = [
            keyword for keyword in NEGATIVE_KEYWORDS if keyword in searchable_text
        ]

        if matched_keywords:
            score = min(85, 45 + len(matched_keywords) * 10)
            add_signal(
                signals,
                company_name=row["company_name"],
                risk_type="google_search_keyword",
                risk_score=score,
                signal_text=f"Google search result matched risk keyword(s): {', '.join(matched_keywords)}.",
                evidence=f"{title} | {row.get('url', '')}",
            )

    return signals


def generate_risk_signals() -> pd.DataFrame:
    """Combine stock and news rules into one risk-signal table."""
    companies = pd.read_csv(COMPANIES_FILE)
    signals: list[dict] = []

    if STOCK_PRICES_FILE.exists():
        stock_prices = pd.read_csv(STOCK_PRICES_FILE)
        signals.extend(generate_stock_signals(stock_prices))
    else:
        print(f"WARNING: Missing stock file: {STOCK_PRICES_FILE}")

    if COMPANY_NEWS_FILE.exists():
        company_news = pd.read_csv(COMPANY_NEWS_FILE)
        signals.extend(generate_news_signals(company_news))
    else:
        print(f"WARNING: Missing news file: {COMPANY_NEWS_FILE}")

    if GOOGLE_SEARCH_FILE.exists():
        google_search_results = pd.read_csv(GOOGLE_SEARCH_FILE)
        signals.extend(generate_google_search_signals(google_search_results))
    else:
        print(f"WARNING: Missing Google search file: {GOOGLE_SEARCH_FILE}")

    risk_signals = pd.DataFrame(
        signals,
        columns=[
            "company_name",
            "risk_type",
            "risk_score",
            "signal_text",
            "evidence",
            "detected_at",
        ],
    )

    # Include sector information for dashboard filtering.
    if not risk_signals.empty:
        risk_signals = risk_signals.merge(
            companies[["company_name", "sector"]],
            on="company_name",
            how="left",
        )
        risk_signals = risk_signals[
            [
                "company_name",
                "sector",
                "risk_type",
                "risk_score",
                "signal_text",
                "evidence",
                "detected_at",
            ]
        ]

    return risk_signals


def save_risk_signals(risk_signals: pd.DataFrame) -> None:
    """Create the data folder if needed and save risk signals."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    risk_signals.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")


def main() -> None:
    """Run risk-signal generation and save its output."""
    risk_signals = generate_risk_signals()
    save_risk_signals(risk_signals)
    print(f"Saved {len(risk_signals)} risk signals to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
