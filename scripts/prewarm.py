"""Pre-warm the PostgreSQL cache: fetch headlines and run the NLP models
for whole companies/periods ahead of time, so dashboard users only ever
read from the database instead of waiting for CPU inference.

Reuses the exact same modules as the app (services/news.py, nlp.py, db.py),
so cache keys, JSON shapes, and tables match by construction — do not
hand-write SQL against the database.

Usage (DATABASE_URL must point at the target Postgres):

    # everything: all DAX companies, all four quarters of one year
    DATABASE_URL=postgresql://... python -m scripts.prewarm --year 2026

    # a subset
    python -m scripts.prewarm --tickers SAP.DE,SIE.DE --year 2026 --quarters 1,2

    # nightly cron use: current quarter only, all companies
    python -m scripts.prewarm --current-quarter

Run this on a machine with a fast CPU. First run downloads the three
transformer models (~1.5 GB). Safe to interrupt and re-run: already-scored
headlines are skipped (nlp_cache hit), so it always resumes where it left
off. The GDELT fetch is rate-limited (~1 req/5s) by services/news.py.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from services import db, news, nlp, risk

TOPICS_KEY = "v4"  # must match app.py::cached_analyze


def _clean_title(title: str) -> str:
    """Strip the Google News publisher suffix — mirrors app.py exactly."""
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def _headline_dict(h: news.Headline) -> dict:
    """Same shape app.py::cached_headlines stores in headline_cache."""
    ts = datetime.fromisoformat(h.published_at.isoformat())
    return {
        "title": h.title,
        "url": h.url,
        "source": h.source,
        "provider": h.provider,
        "published_at": h.published_at.isoformat(),
        "language_hint": h.language_hint,
        "quarter": f"Q{(ts.month - 1) // 3 + 1} {ts.year}",
    }


def prewarm(ticker: str, year: int, quarters: tuple[int, ...], labels: list[str]) -> tuple[int, int]:
    """Fetch + score one company/period. Returns (n_headlines, n_newly_scored)."""
    diagnostics: list[news.FetchReport] = []
    headlines = news.fetch_headlines_multi(ticker, year, quarters, diagnostics=diagnostics)
    for d in diagnostics:
        if not d.ok:
            print(f"    warn: {d.provider} failed: {d.error}")

    if headlines:
        db.save_headlines(
            db.headlines_key(ticker, year, quarters),
            [_headline_dict(h) for h in headlines],
            [
                {
                    "provider": d.provider, "ok": d.ok, "n_raw": d.n_raw,
                    "n_after_filter": d.n_after_filter, "error": d.error,
                    "http_status": d.http_status,
                }
                for d in diagnostics
            ],
        )

    scored = 0
    for i, h in enumerate(headlines, 1):
        key = db.analysis_key(h.title, h.language_hint, TOPICS_KEY)
        if db.get_analysis(key) is not None:
            continue  # already scored by a previous run or by the app
        t0 = time.monotonic()
        analysis = nlp.analyze(_clean_title(h.title), topic_labels=labels, language_hint=h.language_hint)
        db.save_analysis(key, h.title, h.language_hint, TOPICS_KEY, analysis.as_dict())
        scored += 1
        print(f"    [{i}/{len(headlines)}] {time.monotonic() - t0:5.1f}s  {h.title[:70]}")
    return len(headlines), scored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tickers", default="all",
                        help="comma-separated tickers (e.g. SAP.DE,SIE.DE) or 'all' (default)")
    parser.add_argument("--year", type=int, default=None, help="year to fetch (default: current)")
    parser.add_argument("--quarters", default=None,
                        help="comma-separated quarters, e.g. 1,2,3,4 (default: all four)")
    parser.add_argument("--current-quarter", action="store_true",
                        help="only the current quarter of the current year (for nightly cron)")
    args = parser.parse_args()

    if not db.available():
        print(f"ERROR: database {db.status()} — set DATABASE_URL and retry.", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    if args.current_quarter:
        year, quarters = now.year, ((now.month - 1) // 3 + 1,)
    else:
        year = args.year or now.year
        quarters = tuple(sorted(int(q) for q in (args.quarters or "1,2,3,4").split(",")))

    companies = news.load_companies()
    if args.tickers != "all":
        wanted = {t.strip() for t in args.tickers.split(",")}
        companies = [c for c in companies if c["ticker"] in wanted]
        missing = wanted - {c["ticker"] for c in companies}
        if missing:
            print(f"ERROR: unknown ticker(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    labels = risk.classification_topic_labels()
    print(f"Pre-warming {len(companies)} company(ies), {year} Q{list(quarters)}, "
          f"{len(labels)} topic labels -> {db.status()}")
    print("Loading models (first run downloads ~1.5 GB)...")
    nlp.get_pipeline("translate"), nlp.get_pipeline("sentiment"), nlp.get_pipeline("topics")

    total_h = total_new = 0
    started = time.monotonic()
    for n, company in enumerate(companies, 1):
        print(f"[{n}/{len(companies)}] {company['name']} ({company['ticker']})")
        try:
            n_h, n_new = prewarm(company["ticker"], year, quarters, labels)
        except Exception as exc:  # keep going: one bad company must not kill the batch
            print(f"    ERROR, skipping company: {exc}", file=sys.stderr)
            continue
        total_h += n_h
        total_new += n_new
        print(f"    {n_h} headline(s), {n_new} newly scored")

    mins = (time.monotonic() - started) / 60
    print(f"\nDone in {mins:.1f} min — {total_h} headlines seen, {total_new} newly scored, "
          f"{total_h - total_new} already cached.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
