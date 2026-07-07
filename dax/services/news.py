"""News fetching for the DAX 40 Audit Risk Radar.

Two free, no-key sources are used:
  * GDELT DOC 2.0 API   — https://api.gdeltproject.org/api/v2/doc/doc
  * Google News RSS     — https://news.google.com/rss/search

Results are merged, deduplicated, and filtered to headlines that actually
mention the selected company (via `company_aliases.yaml`).

Design notes
------------
* Everything is a plain function — no classes, no provider protocol. Two
  sources do not justify an abstraction.
* Headlines are returned as a list of `Headline` dataclasses so downstream
  code has predictable field names.
* Fetch functions RECORD exceptions into a per-call diagnostics list so the
  UI can surface "why is my table empty?" instead of silently returning [].
"""

from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests
import yaml
from rapidfuzz import fuzz


# Some servers reject requests with the default python-requests / feedparser
# User-Agent. A browser-like UA gets us through consistently.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# GDELT DOC 2.0 is aggressively rate-limited (empirically ~1 req / 5 s).
# We enforce a minimum spacing between calls process-wide via a lock.
_GDELT_MIN_INTERVAL_S = 5.0
_gdelt_last_call_ts: float = 0.0
_gdelt_lock = threading.Lock()


def _gdelt_throttle() -> None:
    """Block until at least _GDELT_MIN_INTERVAL_S has passed since the last call."""
    global _gdelt_last_call_ts
    with _gdelt_lock:
        now = time.monotonic()
        wait = _GDELT_MIN_INTERVAL_S - (now - _gdelt_last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _gdelt_last_call_ts = time.monotonic()


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class Headline:
    """A single news item after fetch + filter, before NLP."""
    title: str
    url: str
    source: str
    provider: str
    published_at: datetime
    language_hint: str = ""


@dataclass
class FetchReport:
    """Per-provider diagnostic info surfaced in the UI."""
    provider: str
    ok: bool
    n_raw: int = 0            # headlines returned by the provider
    n_after_filter: int = 0   # headlines that mentioned the company
    error: str = ""           # non-empty when ok=False
    http_status: int | None = None


# ---------------------------------------------------------------------------
# Company alias catalog
# ---------------------------------------------------------------------------

_ALIASES_PATH = Path(__file__).parent.parent / "domain" / "company_aliases.yaml"


def load_companies() -> list[dict]:
    with _ALIASES_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get_company(ticker: str) -> dict:
    for c in load_companies():
        if c["ticker"] == ticker:
            return c
    raise KeyError(f"Unknown DAX 40 ticker: {ticker}")


# ---------------------------------------------------------------------------
# Quarter helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Quarter:
    year: int
    q: int

    @property
    def start(self) -> datetime:
        month = (self.q - 1) * 3 + 1
        return datetime(self.year, month, 1, tzinfo=timezone.utc)

    @property
    def end(self) -> datetime:
        if self.q == 4:
            return datetime(self.year + 1, 1, 1, tzinfo=timezone.utc)
        return datetime(self.year, self.q * 3 + 1, 1, tzinfo=timezone.utc)

    def label(self) -> str:
        return f"Q{self.q} {self.year}"


# ---------------------------------------------------------------------------
# Provider 1: GDELT DOC 2.0
# ---------------------------------------------------------------------------

_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_gdelt(
    company: dict,
    quarter: Quarter | None = None,
    max_records: int = 250,
    report: FetchReport | None = None,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Headline]:
    """Query GDELT for a company within a date window.

    Pass EITHER a `quarter` OR an explicit (`start`, `end`) pair — the latter
    lets a caller collapse several adjacent quarters into a single GDELT call,
    which the rate limiter strongly prefers.

    IMPORTANT: GDELT does not tolerate very long OR-queries — the API returns
    an empty result silently. Use the primary company name only; the alias
    filter is applied AFTER fetch anyway.
    """
    rep = report or FetchReport(provider="gdelt", ok=False)

    if start is None or end is None:
        if quarter is None:
            raise ValueError("fetch_gdelt requires either quarter or (start, end)")
        start, end = quarter.start, quarter.end

    query = f'"{company["name"]}"'
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
        "sort": "DateDesc",
    }

    # Retry with exponential backoff on 429. GDELT sometimes needs several
    # seconds between requests; the throttle usually handles it, but a stale
    # counter from a prior session can still hit us on the first call.
    max_attempts = 3
    backoff = 3.0  # seconds; doubled per retry
    r = None
    last_err: str = ""
    for attempt in range(1, max_attempts + 1):
        _gdelt_throttle()
        try:
            r = requests.get(
                _GDELT_URL, params=params, timeout=25, headers={"User-Agent": _UA}
            )
            rep.http_status = r.status_code
            if r.status_code == 429:
                last_err = f"HTTP 429 Too Many Requests (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                rep.ok = False
                rep.error = last_err + " — GDELT throttled; try again in a minute."
                return []
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                rep.ok = False
                rep.error = f"GDELT returned non-JSON (first 120 chars): {r.text[:120]!r}"
                return []
            break
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_attempts:
                time.sleep(backoff)
                backoff *= 2
                continue
            rep.ok = False
            rep.error = last_err
            return []

    articles = data.get("articles", []) or []
    out: list[Headline] = []
    for art in articles:
        try:
            ts = datetime.strptime(art["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        title = html.unescape((art.get("title") or "").strip())
        if not title:
            continue
        out.append(
            Headline(
                title=title,
                url=art.get("url", ""),
                source=art.get("domain", ""),
                provider="gdelt",
                published_at=ts,
                language_hint=(art.get("language") or "").lower()[:2],
            )
        )
    rep.ok = True
    rep.n_raw = len(out)
    return out


# ---------------------------------------------------------------------------
# Provider 2: Google News RSS
# ---------------------------------------------------------------------------

def _google_rss_url(query: str, lang: str) -> str:
    hl = {"en": "en-US", "de": "de"}[lang]
    gl = {"en": "US", "de": "DE"}[lang]
    ceid = f"{gl}:{lang}"
    return (
        "https://news.google.com/rss/search"
        f"?q={requests.utils.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )


def fetch_google_rss(
    company: dict,
    quarter: Quarter,
    max_records: int = 40,
    report: FetchReport | None = None,
) -> list[Headline]:
    """Google News RSS is not date-range queryable — we fetch recent items and
    filter to the quarter window ourselves. Requesting via the plain
    `feedparser.parse(url)` route fails on some networks because Google blocks
    the default urllib User-Agent — so we fetch with requests + UA first.
    """
    rep = report or FetchReport(provider="google", ok=False)

    query = f'"{company["name"]}"'
    out: list[Headline] = []
    errors: list[str] = []

    for lang in ("en", "de"):
        url = _google_rss_url(query, lang)
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except requests.RequestException as e:
            errors.append(f"{lang}: {type(e).__name__}: {e}")
            continue

        for entry in feed.entries[:max_records]:
            pp = getattr(entry, "published_parsed", None)
            if not pp:
                continue
            ts = datetime(*pp[:6], tzinfo=timezone.utc)
            if not (quarter.start <= ts < quarter.end):
                continue
            source_info = getattr(entry, "source", None) or {}
            source_name = source_info.get("title", "") if isinstance(source_info, dict) else ""
            title = html.unescape((entry.title or "").strip())
            if not title:
                continue
            out.append(
                Headline(
                    title=title,
                    url=entry.link,
                    source=source_name,
                    provider="google",
                    published_at=ts,
                    language_hint=lang,
                )
            )

    if errors and not out:
        rep.ok = False
        rep.error = " | ".join(errors)
    else:
        rep.ok = True
    rep.n_raw = len(out)
    return out


# ---------------------------------------------------------------------------
# Merging: dedupe + company-name filter
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> str:
    return " " + " ".join(_WORD_RE.findall(text.lower())) + " "


def _mentions_company(text: str, aliases: list[str]) -> bool:
    haystack = _tokens(text)
    return any(_tokens(a) in haystack for a in aliases)


def _dedupe(headlines: Iterable[Headline], similarity: int = 88) -> list[Headline]:
    kept: list[Headline] = []
    for h in headlines:
        if any(fuzz.token_set_ratio(h.title, k.title) >= similarity for k in kept):
            continue
        kept.append(h)
    return kept


def fetch_headlines(
    ticker: str,
    quarter: Quarter,
    diagnostics: list[FetchReport] | None = None,
) -> list[Headline]:
    """Return merged, deduped, filtered headlines. If `diagnostics` is passed,
    per-provider reports are appended to it so the UI can show why the list
    is empty.
    """
    company = get_company(ticker)

    rep_gdelt = FetchReport(provider="gdelt", ok=False)
    rep_google = FetchReport(provider="google", ok=False)
    gdelt = fetch_gdelt(company, quarter, report=rep_gdelt)
    google = fetch_google_rss(company, quarter, report=rep_google)

    aliases = company["aliases"]
    gdelt_kept = [h for h in gdelt if _mentions_company(h.title, aliases)]
    google_kept = [h for h in google if _mentions_company(h.title, aliases)]
    rep_gdelt.n_after_filter = len(gdelt_kept)
    rep_google.n_after_filter = len(google_kept)

    if diagnostics is not None:
        diagnostics.append(rep_gdelt)
        diagnostics.append(rep_google)

    combined = [*gdelt_kept, *google_kept]
    combined.sort(key=lambda h: h.published_at, reverse=True)
    return _dedupe(combined)


def fetch_headlines_multi(
    ticker: str,
    year: int,
    quarters: Iterable[int],
    diagnostics: list[FetchReport] | None = None,
) -> list[Headline]:
    """Multi-quarter fetch that collapses GDELT into a SINGLE HTTP call
    spanning the whole period, then merges with per-quarter Google RSS.

    Rationale: GDELT is aggressively rate-limited. Firing one call per quarter
    causes 429s. GDELT accepts any date window, so one wide call is strictly
    better. Google RSS is fetched per quarter because its client-side date
    filter needs a narrow window to be meaningful.
    """
    company = get_company(ticker)
    aliases = company["aliases"]
    qs = sorted(set(quarters))
    if not qs:
        return []

    period_start = Quarter(year=year, q=qs[0]).start
    period_end = Quarter(year=year, q=qs[-1]).end

    # --- Single GDELT call over the entire period -------------------------
    rep_gdelt = FetchReport(provider="gdelt", ok=False)
    gdelt = fetch_gdelt(
        company, start=period_start, end=period_end, report=rep_gdelt
    )
    gdelt_kept = [h for h in gdelt if _mentions_company(h.title, aliases)]
    rep_gdelt.n_after_filter = len(gdelt_kept)

    # --- Google RSS: one call per (language, quarter) ---------------------
    rep_google = FetchReport(provider="google", ok=True)
    google_kept: list[Headline] = []
    for q in qs:
        per_q_rep = FetchReport(provider="google", ok=False)
        google_q = fetch_google_rss(company, Quarter(year=year, q=q), report=per_q_rep)
        rep_google.n_raw += per_q_rep.n_raw
        rep_google.ok = rep_google.ok and per_q_rep.ok
        if per_q_rep.error and per_q_rep.error not in rep_google.error:
            rep_google.error = (rep_google.error + " | " + per_q_rep.error).strip(" |")
        google_kept.extend(h for h in google_q if _mentions_company(h.title, aliases))
    rep_google.n_after_filter = len(google_kept)

    if diagnostics is not None:
        diagnostics.append(rep_gdelt)
        diagnostics.append(rep_google)

    combined = [*gdelt_kept, *google_kept]
    combined.sort(key=lambda h: h.published_at, reverse=True)
    return _dedupe(combined)
