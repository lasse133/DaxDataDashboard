# DAX 40 Audit Risk Radar

A Streamlit dashboard that helps auditors satisfy **ISA 315** ("Identifying and
Assessing the Risks of Material Misstatement") for DAX 40 companies. It streams
live news and daily stock prices for a selected company and quarter, runs each
headline through pretrained deep-learning models, and maps the output to
concrete audit and legal references.

> **This tool supports the auditor's professional judgment. It does not perform
> the ISA 315 risk assessment itself.**

---

## Required technologies

| Requirement | How it is satisfied |
|---|---|
| **Distributed / stream processing (Streamlit)** | Headlines flow through a staged pipeline (fetch → clean publisher suffix → language detect → translate → sentiment + topics → risk mapping). The app processes one headline per `st.rerun()`, so rows appear incrementally and Pause / Resume controls stay responsive. |
| **Deep learning** | Three pretrained transformer models used for inference only: MarianMT (translation), FinBERT (financial sentiment), DeBERTa-v3-MNLI (zero-shot topic classification). See the sidebar's "Deep-learning stack" panel. |

## Data sources (all free, no API key required)

- **Prices** — Yahoo Finance via `yfinance` (daily OHLC over the selected quarter).
- **News** — GDELT DOC 2.0 API + Google News RSS (English and German).

## Setup with uv

Install `uv` once if it is not already available:

```bash
pip install uv
```

Then run the dashboard from this folder:

```bash
uv run streamlit run app.py
```

`uv` creates and manages the virtual environment automatically from
`pyproject.toml`.

## Setup with plain venv

```bash
python -m venv .venv
source .venv/bin/activate # or .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The first run downloads three transformer models (~1.5 GB total) from
HuggingFace and caches them locally. Subsequent runs are fast.

## Docker / CapRover deployment

The repo ships with a `dockerfile` (Python 3.12-slim, CPU-only torch,
Streamlit on port 8501 with a `/_stcore/health` healthcheck) and a
`captain-definition` so it can be deployed to a [CapRover](https://caprover.com)
server as-is.

Run locally with Docker:

```bash
docker build -t dax-dashboard .
docker run -p 8501:8501 dax-dashboard
```

`requirements.txt` also includes SQLAlchemy and psycopg2 for a PostgreSQL
service provisioned alongside the app on CapRover
(`srv-captain--dax-db:5432`); the app itself does not use the database yet —
see [`doc/deployment-diagram.md`](doc/deployment-diagram.md).

## Using the app

1. Pick a DAX 40 company from the sidebar.
2. Choose a workspace:
   - **Reporting period** for quarter-based audit risk scoring.
   - **Market news** for fast external-news monitoring without running the ML pipeline.
   - **Company channels** for company-owned communications such as press
     releases, investor relations, announcements, and indexed social posts.
3. In **Reporting period**, pick one or more quarters and click
   **🔄 Fetch latest data**. Headlines are fetched and processed one by one —
   rows appear in the results table as each finishes.
   Stock prices default to year-to-date, from January 1 of the current year to
   today, and can be changed to a custom historical range in the sidebar.
4. Review the aggregated **Risk radar** and open any expander to see:
   - the exact deep-learning signals (sentiment score, matched topics),
   - the ISA / IDW paragraphs that apply,
   - suggested audit procedures.
5. Export the reporting-period workpaper as JSON or PDF. The PDF export is
   headline-level evidence; it does not summarize full article bodies.

The lightweight news workspaces include keyword search and risk-driver term
charts for quick auditor scanning.

For a detailed explanation of the risk radar, top-topic scores, and
high/medium/low flag labels, see
[`doc/risk-radar-output.md`](doc/risk-radar-output.md).

## Project layout

```
dax/
├── app.py                          # Streamlit UI (thin — presentation only)
├── requirements.txt
├── dockerfile                      # Container image (Python 3.12-slim, port 8501)
├── captain-definition              # CapRover deploy config (points at dockerfile)
├── doc/
│   ├── component-diagram.md        # Building blocks and dependencies
│   ├── data-flow.md                # Mermaid diagrams for the pipeline
│   ├── deployment-diagram.md       # Docker/CapRover physical view
│   ├── design-decisions.md         # Architecture and design rationale
│   └── risk-radar-output.md        # How to interpret the output
├── domain/
│   ├── company_aliases.yaml        # 40 tickers + name aliases for filtering
│   └── isa315_map.yaml             # ISA 315 rule catalog (rules-as-data)
└── services/
    ├── news.py                     # GDELT + Google News RSS, dedupe + filter
    ├── prices.py                   # yfinance wrapper
    ├── nlp.py                      # translate + sentiment + zero-shot topics
    └── risk.py                     # rule engine (analysis → RiskFlag[])
```

## Design principles

- **Rules-as-data.** All audit rules live in `domain/isa315_map.yaml`, not in
  Python. An audit partner can review the catalog without reading code.
- **Manual refresh only.** The page is frozen until the user clicks Refresh,
  so screenshots are stable — important for workpapers.
- **Traceable flags.** Every flag exposes the deep-learning outputs that
  triggered it (topic scores, sentiment label + confidence) and the exact
  ISA / IDW paragraphs invoked.
- **Reproducibility.** Pretrained model IDs are pinned; language detection is
  seeded; the snapshot export contains the full model registry.

## Known limitations

- Free news sources have limited historical depth. Older quarters may return
  few or no results — this is expected.
- Zero-shot classification is imperfect; scores are thresholded but auditors
  should always review flagged headlines before acting on them.
- DAX 40 index composition changes ~annually. Verify `company_aliases.yaml`
  against the current index constituents before an engagement.
