# DAX 40 Audit Risk Radar

A Streamlit dashboard that helps auditors with **ISA 315** ("Identifying and
Assessing the Risks of Material Misstatement") for DAX 40 companies. Pick a
company and a reporting period; the app fetches news headlines and daily stock
prices, runs each headline through pretrained deep-learning models (translation,
financial sentiment, zero-shot topic classification), and maps the results to a
catalog of ISA 315 audit rules — producing a risk radar with drill-downs into
the exact signals, audit references, and suggested procedures behind every flag.

> **This tool supports the auditor's professional judgment. It does not perform
> the ISA 315 risk assessment itself.**

**Live demo:** https://dax-dashboard.178.105.201.137.nip.io/

## Features

- **Live data, no API keys** — headlines from GDELT DOC 2.0 and Google News RSS
  (English + German), prices from Yahoo Finance via `yfinance`.
- **Deep-learning pipeline** — three pretrained transformers, inference only:
  MarianMT (DE→EN translation), FinBERT (financial sentiment), DeBERTa-v3-MNLI
  (zero-shot topic scoring). Headlines are processed one at a time with
  Pause / Resume controls, so results stream into the table as they finish.
- **Rules-as-data** — the ISA 315 rule catalog lives in
  `domain/isa315_map.yaml`, not in Python. An audit partner can review or edit
  the rules without reading code.
- **Risk radar & drill-downs** — flags aggregated by category and severity;
  every flag shows the model scores that triggered it plus the ISA / IDW
  paragraphs and suggested audit procedures.
- **Workpaper export** — download the full run as a JSON snapshot or a PDF
  workpaper.
- **Optional PostgreSQL persistence** — model output and fetched headlines are
  cached in a database so they survive restarts and redeploys (see
  [Database](#database-optional)).

## Project structure

```
DaxDataDashboard/
├── app.py                          # Streamlit UI (presentation layer only)
├── requirements.txt
├── pyproject.toml                  # uv-compatible project definition
├── dockerfile                      # Container image (Python 3.12-slim, port 8501)
├── captain-definition              # CapRover deploy config (points at dockerfile)
├── domain/
│   ├── company_aliases.yaml        # DAX 40 tickers + name aliases for filtering
│   └── isa315_map.yaml             # ISA 315 rule catalog (rules-as-data)
├── services/
│   ├── news.py                     # GDELT + Google News RSS: fetch, clean, dedupe, filter
│   ├── prices.py                   # yfinance wrapper (daily OHLC)
│   ├── nlp.py                      # translate + sentiment + zero-shot topics
│   ├── risk.py                     # rule engine (analysis → risk flags)
│   └── db.py                       # optional PostgreSQL persistence layer
├── scripts/
│   └── prewarm.py                  # batch ingestion: pre-score companies into the DB
└── doc/
    ├── component-diagram.md        # Building blocks and dependencies
    ├── data-flow.md                # How data moves through the pipeline
    ├── deployment-diagram.md       # Docker / CapRover physical view
    ├── design-decisions.md         # Architecture and design rationale
    └── risk-radar-output.md        # How to interpret the output
```

`app.py` is presentation only: all I/O, model inference, and rule evaluation
live in `services/`, and all audit knowledge lives in `domain/*.yaml`.

## Getting started

Requires Python 3.12+. The first run downloads the three transformer models
(~1.5 GB) from HuggingFace and caches them locally; subsequent runs are fast.

**With [uv](https://github.com/astral-sh/uv)** (manages the virtualenv for you):

```bash
uv run streamlit run app.py
```

**With plain venv:**

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

**With Docker:**

```bash
docker build -t dax-dashboard .
docker run -p 8501:8501 dax-dashboard
```

Then open http://localhost:8501.

## Usage

1. Pick a DAX 40 company, a year, and one or more quarters in the sidebar.
   Stock prices default to year-to-date and can be switched to a custom range.
2. Click **Fetch latest data**. Headlines are fetched, filtered to those that
   actually mention the company, and processed one by one — rows appear in the
   results table as each finishes (Pause / Resume / Reset any time).
3. Review the **Risk radar** and open any flagged headline to see the
   deep-learning signals, the ISA / IDW references, and suggested procedures.
4. Export the run as a JSON snapshot or PDF workpaper.

The "How this report works" expander in the app explains the pipeline and shows
the live rule catalog. For interpreting scores and severity labels, see
[`doc/risk-radar-output.md`](doc/risk-radar-output.md).

## Database (optional)

The app runs fully in-memory by default. If the `DATABASE_URL` environment
variable is set, `services/db.py` persists to PostgreSQL:

- **`nlp_cache`** — the transformer output per headline (the app's most
  expensive computation), so each headline is only ever analyzed once, across
  all sessions and deployments.
- **`headline_cache`** — fetched headlines per company/period, reused for up to
  24 hours so restarts don't re-hit the rate-limited news APIs. The
  **Fetch latest data** button always bypasses this cache and refreshes it.

Tables are created automatically on first connection. If the database is
missing or unreachable, the app simply runs without persistence — the sidebar
shows the current connection state.

```bash
export DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>
```

## Deployment (CapRover)

The repo deploys to a [CapRover](https://caprover.com) server as-is: the
`captain-definition` points CapRover at the `dockerfile`, and a healthcheck on
Streamlit's `/_stcore/health` endpoint tells CapRover when the app is alive.

```bash
npx caprover login    # once
npx caprover deploy   # pick server, branch, and app
```

With CapRover's one-click PostgreSQL app deployed alongside (e.g. as `dax-db`),
set `DATABASE_URL` on the dashboard app under App Configs → Environment
Variables, using the internal hostname:

```
DATABASE_URL=postgresql://postgres:<password>@srv-captain--dax-db:5432/risk_data
```

See [`doc/deployment-diagram.md`](doc/deployment-diagram.md) for the full
physical view.

## Known limitations

- Free news sources have limited historical depth; older quarters may return
  few or no results.
- Zero-shot classification is imperfect. Scores are thresholded, but auditors
  should always review flagged headlines before acting on them.
- DAX 40 index composition changes ~annually. Verify `company_aliases.yaml`
  against the current constituents before an engagement.
