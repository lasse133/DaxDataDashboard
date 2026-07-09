"""Diagnostic script for the news pipeline.

Run this from the project root:

    python debug_news.py SAP.DE

It walks the news fetch step by step and prints what each stage returns,
so we can see WHICH stage drops the headlines instead of guessing.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

# Ensure imports work when run from project root.
sys.path.insert(0, ".")

from services import news


def current_quarter() -> news.Quarter:
    now = datetime.now(timezone.utc)
    return news.Quarter(year=now.year, q=(now.month - 1) // 3 + 1)


def previous_quarter(q: news.Quarter) -> news.Quarter:
    if q.q == 1:
        return news.Quarter(year=q.year - 1, q=4)
    return news.Quarter(year=q.year, q=q.q - 1)


def main(ticker: str) -> None:
    print(f"\n=== Diagnostic: {ticker} ===\n")

    try:
        company = news.get_company(ticker)
    except KeyError as e:
        print(f"[FAIL] Unknown ticker: {e}")
        return
    print(f"Company : {company['name']}")
    print(f"Aliases : {company['aliases']}\n")

    # Try current quarter AND previous quarter (the current one may be days old).
    for label, quarter in [
        ("current quarter", current_quarter()),
        ("previous quarter", previous_quarter(current_quarter())),
    ]:
        print(f"--- {label}: {quarter.label()} "
              f"[{quarter.start.date()} → {quarter.end.date()}) ---")

        # Stage 1: GDELT
        try:
            gdelt = news.fetch_gdelt(company, quarter)
            print(f"  GDELT       : {len(gdelt):3d} headlines")
            for h in gdelt[:3]:
                print(f"    - {h.published_at.date()} | {h.title[:90]}")
        except Exception as e:
            print(f"  GDELT       : EXCEPTION {type(e).__name__}: {e}")

        # Stage 2: Google News RSS
        try:
            google = news.fetch_google_rss(company, quarter)
            print(f"  Google RSS  : {len(google):3d} headlines")
            for h in google[:3]:
                print(f"    - {h.published_at.date()} | {h.title[:90]}")
        except Exception as e:
            print(f"  Google RSS  : EXCEPTION {type(e).__name__}: {e}")

        # Stage 3: Combined + filter + dedupe
        try:
            combined = news.fetch_headlines(ticker, quarter)
            print(f"  After merge : {len(combined):3d} headlines (deduped, filtered)")
            for h in combined[:5]:
                print(f"    - {h.published_at.date()} | [{h.provider}] {h.title[:80]}")
        except Exception as e:
            print(f"  After merge : EXCEPTION {type(e).__name__}: {e}")

        print()


if __name__ == "__main__":
    tk = sys.argv[1] if len(sys.argv) > 1 else "SAP.DE"
    main(tk)
