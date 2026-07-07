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
| **Distributed / stream processing (Streamlit)** | Headlines flow through a staged pipeline (fetch → language detect → translate → sentiment + topics → risk mapping) executed by a `ThreadPoolExecutor`. Rows appear in the UI **as each headline finishes**, not in one batch — a Streamlit-native streaming dashboard. |
| **Deep learning** | Three pretrained transformer models used for inference only: MarianMT (translation), FinBERT (financial sentiment), DeBERTa-v3-MNLI (zero-shot topic classification). See the sidebar's "Deep-learning stack" panel. |

## Data sources (all free, no API key required)

- **Prices** — Yahoo Finance via `yfinance` (daily OHLC over the selected quarter).
- **News** — GDELT DOC 2.0 API + Google News RSS (English and German).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The first run downloads three transformer models (~1.5 GB total) from
HuggingFace and caches them locally. Subsequent runs are fast.

## Using the app

1. Pick a DAX 40 company from the sidebar.
2. Pick a quarter (defaults to the current quarter).
3. Click **🔄 Fetch latest data**. Headlines are fetched and processed one by
   one — rows appear in the results table as each finishes.
4. Review the aggregated **Risk radar** and open any expander to see:
   - the exact deep-learning signals (sentiment score, matched topics),
   - the ISA / IDW paragraphs that apply,
   - suggested audit procedures.
5. Click **⬇️  Download JSON snapshot** to export a workpaper artifact with
   every model version, score, and flag for that quarter.

## Project layout

```
dax/
├── app.py                          # Streamlit UI (thin — presentation only)
├── requirements.txt
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
