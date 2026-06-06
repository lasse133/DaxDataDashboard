# DAX 40 Audit Risk Radar

Real-time screening of market and news data to detect risk signals, summarize
key developments, and support structured audit risk assessment (ISA 315).

---

## Data flow (streaming)

```
     INGEST              PROCESS              SCORE               VISUALIZE
┌──────────────┐   ┌─────────────┐   ┌──────────────────┐   ┌──────────────┐
│ News headline│──▶│ Send text   │──▶│ FinBERT sentiment│──▶│ Streamlit    │
│ + stock tick │   │ to FinBERT  │   │ + risk category  │   │ flashes      │
│ (data_sources│   │ (nlp.py)    │   │ (nlp.py)         │   │ warning +    │
│  .py)        │   │             │   │                  │   │ price chart  │
└──────────────┘   └─────────────┘   └──────────────────┘   └──────────────┘
```

Each layer is one file:

| File | Layer | Responsibility |
|------|-------|----------------|
| `config.py` | — | Companies, tickers, risk keyword lexicon, settings |
| `data_sources.py` | Ingest | Live prices (yfinance) + news stream (mock or NewsAPI) |
| `nlp.py` | Process + Score | FinBERT sentiment + ISA-315 risk-driver extraction |
| `app.py` | Visualize | Streamlit dashboard + auto-refreshing streaming fragments |

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

A browser tab opens at `http://localhost:8501`. The **first run downloads
FinBERT (~400 MB)** from Hugging Face; afterwards it starts instantly.
Works out of the box on a **mock news stream** — no API keys required.

### Switch to live news (optional)

Get a free key at <https://newsapi.org>, then:

```bash
export NEWSAPI_KEY="your-key-here"
streamlit run app.py
```

---

## File map

```
.
├── app.py              # Streamlit dashboard + streaming fragments (Visualize)
├── config.py           # DAX40 companies, tickers, risk lexicon, settings
├── data_sources.py     # Ingest: yfinance prices + news stream
├── nlp.py              # FinBERT sentiment + risk extraction (Process + Score)
├── requirements.txt    # All dependencies
├── .streamlit/
│   └── config.toml     # Dark theme + dev settings
├── pipeline/           # Batch scrapers (run once to seed data/ CSVs)
│   ├── scrape_dax_companies.py
│   ├── scrape_stock_prices.py
│   ├── scrape_company_news.py
│   ├── scrape_google_search.py
│   └── generate_risk_signals.py
└── data/               # CSV outputs from batch pipeline
    ├── dax_companies.csv
    ├── yahoo_ticker_mapping.csv
    ├── stock_prices.csv
    ├── company_news.csv
    └── risk_signals.csv
```

---

## Batch pipeline (optional)

The `pipeline/` scripts scrape and cache static CSVs. They are not required to
run the dashboard but are useful for offline analysis or to seed historical data.

```bash
python pipeline/scrape_dax_companies.py
python pipeline/scrape_stock_prices.py
python pipeline/scrape_company_news.py
python pipeline/scrape_google_search.py   # requires GOOGLE_API_KEY + GOOGLE_CSE_ID
python pipeline/generate_risk_signals.py
```

---

## Testing each layer

```bash
# FinBERT sentiment
python -c "import nlp; print(nlp.analyze_sentiment('Siemens faces project delays and a profit warning'))"

# Risk-driver extraction
python -c "import nlp; print(nlp.extract_risk_drivers('lawsuit and supply chain disruption'))"

# Live prices
python -c "import data_sources; print(data_sources.get_prices(['SAP.DE']))"

# Full enriched record
python -c "import nlp, data_sources; print(nlp.score_headline(data_sources.poll_news(1)[0]))"
```

---

## Suggested next steps

1. **Persist an audit trail** — append scored headlines to `events.csv` or SQLite for documented, timestamped evidence.
2. **Correlate news with price** — flag when a negative headline lands within N minutes of a >X% drop; that co-occurrence is the strongest signal.
3. **Per-company risk gauge** — aggregate recent negative confidence into a 0–100 score per DAX name for the planning summary.
4. **Deploy** — push to GitHub and connect to [Streamlit Community Cloud](https://share.streamlit.io); add `NEWSAPI_KEY` under *Settings → Secrets*.
