# DAX 40 Audit Risk Radar — Build Guide

A real-time Streamlit dashboard that screens market + news data and surfaces
ISA-315 risk signals for auditors. This guide walks you through the code
step by step, and the repo already contains a working scaffold you can run now.

---

## 0. What you're building (the 4-step data flow)

```
        INGEST            PROCESS              SCORE                VISUALIZE
   ┌──────────────┐   ┌─────────────┐   ┌──────────────────┐   ┌──────────────┐
   │ News headline│──▶│ Send text   │──▶│ FinBERT sentiment│──▶│ Streamlit    │
   │ + stock tick │   │ to FinBERT  │   │ + risk category  │   │ flashes      │
   │ (data_sources│   │ (nlp.py)    │   │ (nlp.py)         │   │ warning +    │
   │  .py)        │   │             │   │                  │   │ price chart  │
   └──────────────┘   └─────────────┘   └──────────────────┘   └──────────────┘
```

Each layer is one file, so you can build and test them independently:

| File | Layer | Responsibility |
|------|-------|----------------|
| `config.py` | — | Companies, tickers, risk keyword lexicon, settings |
| `data_sources.py` | Ingest | Pull live prices (yfinance) + news stream (mock or NewsAPI) |
| `nlp.py` | Process + Score | FinBERT sentiment + risk-driver extraction |
| `app.py` | Visualize | The Streamlit dashboard + the streaming loop |

> **Design principle:** every layer hands the next one plain Python data
> (dicts / DataFrames). The UI never knows whether news came from a mock feed
> or a real API — which is exactly what lets you swap in live data later
> without touching `app.py`.

---

## 1. Setup (5 minutes)

```bash
# 1. create an isolated environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. run it
streamlit run app.py
```

A browser tab opens at `http://localhost:8501`. The **first run downloads
FinBERT (~400 MB)** from Hugging Face; after that it runs locally and starts
instantly. It works out of the box on a **mock news stream** — no API keys.

---

## 2. Step-by-step: how each file works

### Step 1 — `config.py` (the single source of truth)

Keep all "facts about the world" in one place so the logic stays generic:

- **`DAX40`** — maps each company to its Yahoo Finance ticker (`.DE` suffix for
  Frankfurt). yfinance needs these exact strings.
- **`RISK_DRIVERS`** — this is the audit brain. FinBERT only tells you *how
  negative* a headline is; this dictionary tells you *what kind of risk* it is,
  mapped to ISA-315-style categories (supply chain, regulatory, liquidity,
  governance/fraud, ESG…). Edit these keyword lists to tune what the tool flags.
- **`NEWSAPI_KEY`** — leave `None` to run on the mock stream; set it (or the
  `NEWSAPI_KEY` env var) to flip to live headlines. **This one toggle is your
  mock-to-live switch.**
- **`WARNING_THRESHOLD`** — minimum FinBERT confidence before a headline raises
  a red flag. Raise it to reduce noise.

### Step 2 — `data_sources.py` (Ingest)

Two functions, both wrapped in `try/except` so a network blip never crashes the
dashboard:

- **`get_prices(tickers)`** — one `yfinance.download()` call gets intraday
  candles for every selected company. No API key needed. Returns last price,
  % change, and a price history series per ticker.
- **`poll_news(n)`** — the single entry point the UI calls. If `NEWSAPI_KEY` is
  set it hits NewsAPI's `/everything` endpoint; otherwise it emits random
  headlines from `_MOCK_TEMPLATES` with a fresh timestamp, simulating a live
  wire. Because the UI only ever calls `poll_news()`, swapping sources is
  invisible upstream.

**To go fully live:** sign up at <https://newsapi.org> (free tier), paste the
key into `config.py`, restart. That's the only change required.

### Step 3 — `nlp.py` (Process + Score) — the deep-learning core

- **`_get_pipeline()`** loads `ProsusAI/finbert` once via Hugging Face
  `transformers.pipeline(...)`, cached with `@lru_cache` so the heavy model
  loads a single time per process (critical — Streamlit reruns the script
  constantly).
- **`analyze_sentiment(text)`** returns `{label, score, scores}` where label is
  positive / negative / neutral and `scores` has the probability of each class.
  This is the "Score" step from your plan.
- **`extract_risk_drivers(text)`** does the **Risk Entity Extraction** — matches
  the headline against the `RISK_DRIVERS` lexicon and returns the audit
  categories that fired (e.g. `["Supply chain", "Operational"]`).
- **`score_headline(item)`** glues it together: takes a raw headline dict, adds
  sentiment + drivers + an `is_warning` boolean, and hands back one enriched
  record the UI can render directly.

> **Upgrade path:** swap the keyword lexicon for a financial NER model
> (e.g. a fine-tuned `bert-base-NER`) if you want the model — not a word list —
> to extract entities. The interface (`extract_risk_drivers` returns a list of
> strings) stays the same, so nothing else changes.

### Step 4 — `app.py` (Visualize) — and how streaming actually works

This is the part most people get wrong, so read carefully.

Streamlit **reruns the entire script top-to-bottom on every interaction**. A
naïve `while True:` loop would freeze the page. The clean modern pattern is
`@st.fragment(run_every=N)`:

```python
@st.fragment(run_every=refresh)   # this block re-executes ON ITS OWN every N seconds
def live_feed():
    incoming = data_sources.poll_news(n=2)     # 1. INGEST
    for item in incoming:
        scored = nlp.score_headline(item)      # 2+3. PROCESS + SCORE
        st.session_state.feed.insert(0, scored)
    # 4. VISUALIZE: warnings, metrics, table
```

Key ideas:

1. **`run_every` makes it a stream.** The fragment re-runs on a timer and
   updates *only its part* of the page — the rest of the dashboard stays put.
   Two fragments here: one for the news feed, one for prices.
2. **`st.session_state.feed`** is a rolling buffer (newest first, capped at 50)
   so history survives reruns. `st.session_state.seen` de-dupes by
   (company, headline) so you never score the same article twice.
3. **The warning flash** is `st.error(...)` rendered for any fresh headline
   where `is_warning` is true — your "instantly flash a warning for the
   auditor" requirement.
4. **Prices** render as `st.metric` cards (price + % change, red/green arrow)
   plus a combined `st.line_chart`, so the negative sentiment and the stock
   drop sit side by side.

> If your Streamlit version predates `st.fragment(run_every=...)`, install the
> `streamlit-autorefresh` package and call `st_autorefresh(interval=ms)` at the
> top of the script instead — same effect, slightly less granular.

---

## 3. Test each layer before wiring the UI

Don't debug everything through the browser. Test bottom-up:

```bash
# does FinBERT score correctly?
python -c "import nlp; print(nlp.analyze_sentiment('Siemens faces project delays and a profit warning'))"

# does the lexicon tag the right risk?
python -c "import nlp; print(nlp.extract_risk_drivers('lawsuit and supply chain disruption'))"

# do prices come back?
python -c "import data_sources, config; print(data_sources.get_prices(['SAP.DE']))"

# full enriched record:
python -c "import nlp, data_sources; print(nlp.score_headline(data_sources.poll_news(1)[0]))"
```

If all four print sensible output, `streamlit run app.py` will work.

---

## 4. (Optional) Deploy so auditors just open a URL

Two easy paths:

**A. Streamlit Community Cloud (simplest)**
1. Push this folder to a GitHub repo.
2. Go to <https://share.streamlit.io>, connect the repo, point it at `app.py`.
3. Add `NEWSAPI_KEY` under *Settings → Secrets* (never commit the key).
4. You get a public URL; auditors open it and the dashboard streams live.

**B. GitHub Actions + your own host**
Use Actions only as CI (lint / smoke-test on push); run the app itself on a
small VM or container, since a Streamlit app is a long-running server, not a
batch job. Example smoke test in CI:

```yaml
# .github/workflows/ci.yml
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python -m py_compile app.py config.py data_sources.py nlp.py
```

---

## 5. Why these tools (matches your evaluation)

- **Streamlit, not Tableau** — Tableau on a CSV is batch: data is stale until
  you re-export. Streamlit's `run_every` fragments keep the page awake and
  redraw on every new tick, which is the whole point of a *streaming* tool.
- **FinBERT, not generic sentiment** — it's pre-trained on financial text, so
  "profit warning" reads as strongly negative where a general model might miss
  it.
- **No Hive / big-data store** — you process a small daily volume of headlines;
  an in-memory rolling buffer (and optionally a CSV/SQLite append for the audit
  trail) is the right-sized choice.

---

## 6. Suggested next steps

1. **Persist an audit trail** — append every scored headline to `events.csv` or
   SQLite so the engagement file has documented, timestamped evidence (ISA 315
   wants standardized, documented input).
2. **Tighten company tagging** — the mock/NewsAPI tagger matches the first word
   of a company name; replace it with an entity matcher or a ticker map for
   precision.
3. **Correlate news with price** — flag when a negative headline lands within
   N minutes of a >X% price drop; that co-occurrence is your strongest signal.
4. **Add a per-company risk score** — aggregate recent negative confidence into
   a single 0–100 gauge per DAX name for the planning summary.

---

## File map

```
.
├── app.py              # Streamlit dashboard + streaming loop (Visualize)
├── config.py           # companies, tickers, risk lexicon, settings
├── data_sources.py     # Ingest: yfinance prices + news stream
├── nlp.py              # FinBERT sentiment + risk extraction (Process+Score)
├── requirements.txt
└── .streamlit/
    └── config.toml     # dark theme + dev settings
```
