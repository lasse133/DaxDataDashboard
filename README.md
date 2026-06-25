# DAX 40 Audit Risk Radar

Real-time screening of market and news data to detect risk signals, summarize key
developments, and support structured audit risk assessment (ISA 315).

> **Streaming-first:** every value shown in the dashboard is fetched **live from an
> API at request time**. No scraped CSV is read at runtime — the project focuses on
> data streaming, not batch files. (The `data/` folder only holds a SQLite cache of
> already-scored headlines.)

---

## Data flow

```
     INGEST                  PROCESS              SCORE                  VISUALIZE
┌──────────────────┐   ┌─────────────┐   ┌────────────────────┐   ┌──────────────┐
│ GDELT headline   │──▶│ Send title  │──▶│ FinBERT sentiment  │──▶│ Streamlit:   │
│ + Yahoo price    │   │ to the NLP  │   │ + BART zero-shot   │   │ warning rows,│
│ tick             │   │ models      │   │ risk drivers       │   │ metrics,     │
│ (data_sources.py)│   │ (nlp.py)    │   │ + audit references │   │ price chart  │
└──────────────────┘   └─────────────┘   └────────────────────┘   └──────────────┘
                                                  │
                                       scored records cached in
                                       SQLite (database.py)
```

## Data sources (all live APIs)

| Data | Source | Key? | Notes |
|------|--------|------|-------|
| News | **GDELT DOC 2.0** | no | Deep history, English-filtered. Rate-limited (1 req / 5 s), so fetches are throttled/cached. |
| Stock prices | **Yahoo Finance chart API** | no | Direct JSON endpoint. |

News is filtered to **English** and to the **selected company**. No API key is required.

> Looking for a NewsAPI + GDELT hybrid (NewsAPI for the last 30 days, GDELT for older
> history)? That variant lives on the **`hybrid`** branch.

---

## Architecture

```
.
├── app.py              # Streamlit dashboard: UI, manual fetch, scoring orchestration
├── config.py           # DAX 40 companies/tickers, risk labels, settings
├── data_sources.py     # Streaming ingest: GDELT news + Yahoo prices
├── nlp.py              # FinBERT sentiment + BART zero-shot risk-driver extraction
├── audit_references.py # Maps risk drivers -> ISA-315 audit / legal references
├── database.py         # SQLite cache of scored headlines (data/audit_radar.db)
├── .streamlit/config.toml
├── requirements.txt / pyproject.toml / uv.lock
├── data/
│   └── audit_radar.db  # runtime SQLite cache (NOT scraped data)
└── pipeline/           # OPTIONAL legacy batch scrapers — NOT used by the dashboard
```

> `pipeline/` and the CSVs it produces (`data/company_news.csv`, `dax_companies.csv`,
> etc.) are leftovers from an earlier batch design. The streaming dashboard does **not**
> read them; they can be ignored or deleted.

---

## How it works

- **Manual fetch.** News is fetched **on demand** when you click **🔄 Fetch latest
  news** — the feed otherwise just displays what is already scored in the cache.
- **Scoring.** Each *new* headline is run through **FinBERT** (`ProsusAI/finbert`) for
  financial sentiment and **BART zero-shot** (`facebook/bart-large-mnli`) for ISA-315
  risk categories, then enriched with audit/legal references.
- **Investigation flags.** A negative headline above the confidence threshold is flagged:
  its table row is tinted red and its implications headline is shown in red.

### Caching (two layers)

1. **API responses** — `@st.cache_data(ttl=3600)` keeps each GDELT response for **1 hour**,
   so repeat clicks for the same company/window don't re-hit the API (and stay under
   GDELT's rate limit).
2. **Scored headlines** — persisted **permanently** in SQLite (`data/audit_radar.db`)
   with a `UNIQUE(company, headline)` constraint, so a headline is only scored once.

---

## Quick start

### With uv

```bash
uv sync
uv run streamlit run app.py
```

### With pip

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The dashboard opens at **http://localhost:8501**. No API keys are required (GDELT and
the Yahoo price API are both keyless). The first scoring run loads FinBERT (~400 MB) and
BART (~1.6 GB) from the Hugging Face cache.

> **`accelerate` is required.** transformers 5.x loads model weights on the `meta` device
> and needs `accelerate` to move them to CPU — without it you get
> `NotImplementedError: Cannot copy out of meta tensor`. It is included in `pyproject.toml`
> (so `uv sync` installs it); pip users should run `pip install accelerate` as well.

---

## Disclaimer

Decision-support tool for audit planning (ISA 315). Sentiment and risk categories are
model-generated and must be reviewed by the engagement team.
