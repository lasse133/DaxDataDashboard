# Design Decisions

Living record of the architectural choices made for the DAX 40 Audit Risk
Radar. Each entry names the decision, the alternatives considered, and the
reason we picked what we did. Update this file whenever a decision changes.

---

## 1. Framing & scope

### 1.1 Users are auditors, not analysts
The primary user is an external / internal auditor performing ISA 315 risk
identification for a DAX 40 client. Everything else follows from that:

- **Traceability over cleverness** — every flag on screen must expose the
  model that produced it, the score, the threshold, and the ISA / IDW
  paragraph invoked.
- **Reproducibility** — a JSON snapshot export is a first-class feature
  (workpaper artifact).
- **The tool supports professional judgment; it does not perform the ISA 315
  assessment.** A disclaimer to that effect lives in the sidebar.

### 1.2 Time unit = quarter, refresh = manual
- **Quarter, not real-time.** Auditors think in reporting periods. Daily OHLC
  bars are sufficient — no intraday ticker.
- **Manual refresh button, not auto-poll.** Screenshots stay stable between
  clicks (matters for workpapers) and free news APIs stay under quota.

### 1.3 UI in English, headlines in DE + EN
The tool is aimed at German audit firms but the UI language is English.
News is fetched in both German and English and translated to English before
downstream NLP.

---

## 2. Required technologies — how they're satisfied

| Requirement | Approach |
|---|---|
| **Distributed / stream processing (Streamlit)** | Not a real stream processor (no Kafka / Spark). Instead, headlines flow through a staged pipeline (fetch → language detect → translate → sentiment + topics → risk mapping), and the UI updates **one row at a time** by processing a single headline per `st.rerun()`. This gives us a pausable, event-at-a-time stream in the Streamlit-native sense. |
| **Deep learning** | Three pretrained transformers used for **inference only** — no training / fine-tuning: MarianMT (translation), FinBERT (financial sentiment), DeBERTa-v3-MNLI (zero-shot topic classification). Full model registry is rendered in the sidebar for auditor traceability. |

We do **not** use a real distributed stream processor because the project
constraints demand "simple, free, no infrastructure". Pipelined per-headline
processing satisfies the spirit of the requirement.

---

## 3. Data sources

Decision: **only free, no-key sources**. This eliminates NewsAPI, Finnhub,
Marketaux, Google Custom Search, etc.

| Source | Purpose | Why chosen |
|---|---|---|
| **Yahoo Finance** (via `yfinance`) | Daily OHLC prices | Free, no key, well-known Python wrapper. Unofficial and occasionally unstable — abstracted behind `services/prices.py::fetch_prices` for easy swap. |
| **GDELT DOC 2.0** | Primary news source | Free, no key, unlimited history, DE + EN coverage. Aggressively rate-limited (~1 req / 5 s) — mitigated via a process-wide throttle + retry-with-backoff. |
| **Google News RSS** | Secondary news source | Free, no key, near-real-time. Not date-range queryable — filtered client-side. Requires a browser User-Agent header (otherwise 403). |

Dropped from the original design (all violated "free, simple"):

- NewsAPI, Finnhub, Marketaux — free tiers too restricted or paid.
- Named-entity recognition model — alias regex is sufficient for company
  detection at this scale.
- Google Custom Search JSON API — quota is too small; costs money above it.

---

## 4. Deep-learning stack

All models are loaded lazily and cached process-wide via `@lru_cache` (in
`services/nlp.py`) and `@st.cache_resource` (in `app.py`). Neither is
fine-tuned; we use pretrained checkpoints as-is.

| Role | Model | Params | Rationale |
|---|---|---|---|
| DE → EN translation | `Helsinki-NLP/opus-mt-de-en` | ~74M | Small, mature, produces reasonable output for financial jargon. Runs on CPU. |
| Sentiment (EN) | `ProsusAI/finbert` | ~110M | Explicitly tuned on financial text — beats generic sentiment models on earnings-style headlines. |
| Zero-shot topics (EN) | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | ~184M | Swapped in for `facebook/bart-large-mnli` (~406M) — ~2× smaller, ~3–4× faster on CPU, comparable accuracy on financial headlines. |

### Why zero-shot classification
The alternative (supervised classification) requires thousands of labeled
audit-relevant headlines, which we do not have. Zero-shot lets an audit
partner add a new ISA rule to `domain/isa315_map.yaml` — including a new
topic string — and it works immediately without retraining.

### Language handling
Translate-then-analyze (Option A from earlier design discussion) rather
than a multilingual dual pipeline (Option B). Reasons:

- One model stack downstream — no drift between DE and EN behavior.
- When an auditor challenges a flag, showing the translation + original is
  defensible.
- Financial NLP models are more mature in English.

---

## 5. Rules-as-data (ISA 315 catalog)

`domain/isa315_map.yaml` is the crown jewel of the tool. It is designed so
an **audit partner can review it without reading Python**:

- 11 rules covering going concern, fraud, litigation, regulatory, M&A,
  impairment, revenue recognition, related parties, governance, cyber,
  subsequent events.
- Each rule = `id`, `category`, `severity`, `triggers` (topics + optional
  sentiment gate), `audit_ref` (ISA + IDW paragraphs), `description`,
  concrete `procedures`.
- A rule fires when at least one of its `triggers.topics` has a zero-shot
  score ≥ `DEFAULT_TOPIC_THRESHOLD` (0.55) AND (if specified) the FinBERT
  sentiment matches with score ≥ `sentiment_threshold`.

The mapper (`services/risk.py::evaluate`) is a **pure function** over
`Analysis → list[RiskFlag]`. Easily unit-testable; no side effects.

---

## 6. Application architecture

### 6.1 Layered layout

```
app.py                  ← Streamlit UI (presentation only)
services/
  news.py               ← GDELT + Google RSS, dedupe, alias filter
  prices.py             ← yfinance wrapper
  nlp.py                ← translate + sentiment + zero-shot topics
  risk.py               ← YAML rule engine, pure function
domain/
  company_aliases.yaml  ← 39 DAX tickers + aliases
  isa315_map.yaml       ← ISA 315 rule catalog
```

Flat, minimal. No `infra/`, no protocol classes for the two providers, no
Pydantic models — `@dataclass` is enough.

### 6.2 Caching strategy

| Cache | Type | Invalidation | Purpose |
|---|---|---|---|
| Deep-learning models | `@lru_cache` + `@st.cache_resource` | Process life | A transformer load per rerun would be fatal. |
| Headlines | `@st.cache_data(nonce, ticker, year, quarters)` | Refresh button bumps nonce | Free APIs have quotas / rate limits. |
| Prices | `@st.cache_data(nonce, ticker, year, quarters)` | Refresh button | Same. |
| Per-headline NLP | `@st.cache_data(title, hint, topics_key)` | Explicit `.clear()` on Refresh | Same title → same output; no reason to re-run the transformers. Cache key includes the topic-label version so a rule catalog change re-runs analysis. |

### 6.3 Streaming pipeline (pause/resume)

Streamlit ignores button clicks while a Python function is running.
A `ThreadPoolExecutor` blocking the whole script would eat every Pause
click until it finished — not what an auditor expects.

The pipeline therefore uses a **one-headline-per-rerun** loop driven by
`st.session_state`:

- `queue`: headlines not yet processed
- `results`: headlines already processed
- `paused`: flag flipped by the Pause / Resume buttons
- On each rerun: if not paused and queue non-empty → process **one**
  headline → append to results → `st.rerun()`
- Pause / Resume / Reset buttons flip state between reruns, so they are
  honored immediately

Trade-off: single-threaded, so total wall time = sum of per-headline
inference (~0.3–1 s each with DeBERTa-v3-base). We accept this because
responsiveness is the whole point of Pause.

### 6.4 Rate-limiting GDELT
GDELT is aggressive with 429s. Two mitigations, both in `services/news.py`:

1. **Process-wide throttle** — a `threading.Lock` + monotonic timestamp
   enforces ≥ 5 s between GDELT calls.
2. **Single call over multi-quarter window** — `fetch_headlines_multi`
   collapses all selected quarters into one GDELT query spanning
   `min.start → max.end`, then buckets returned headlines by quarter
   client-side. Before this fix, selecting Q1+Q2+Q3+Q4 fired four GDELT
   requests → guaranteed 429.
3. **Retry with exponential backoff** on 429 (3 attempts, 3s → 6s → 12s).

---

## 7. UI decisions

- **Real `st.dataframe`, not markdown table.** The initial implementation
  emitted one `st.markdown()` per row, which Streamlit rendered as separate
  blocks so headers and bodies never aligned. Now: a single `st.dataframe`
  with a Pandas `Styler` for row highlighting.
- **Light-red row background for negative sentiment.** `#fdecea` — readable,
  WCAG-safe, unambiguous "further notice needed" signal to the auditor.
- **Year dropdown + quarter multi-select** (rather than a single "Q2 2026"
  selectbox). Auditors often investigate a full-year picture or a
  half-year, not always one quarter. Multi-select captures that.
- **Diagnostics expander** on every fetch. Always shows raw / filtered
  counts per provider + HTTP status. Auto-opens when the result list is
  empty. Prevents "why is my table empty?" questions.
- **Model registry sidebar expander.** Lists each transformer's HuggingFace
  ID, architecture, param count, and purpose. Auditors will ask which
  model produced a given flag; this is the answer.

---

## 8. Deliberately deferred

Things we explicitly chose *not* to build for the MVP:

- **Fine-tuning** any model on labeled audit data. We have no dataset and
  pretrained inference is enough for a demo.
- **Multi-user auth / user accounts.** Single-user demo tool.
- **Persistent database.** All state is in-memory (session) + on-disk
  YAML. Snapshot export is JSON-per-run. *Update:* a PostgreSQL service is
  now provisioned on the CapRover host and the connectors (SQLAlchemy +
  psycopg2) are in `requirements.txt`, but the app does not use it yet —
  see §9.
- **Real distributed stream processor** (Kafka / Spark / Flink). Explicitly
  ruled out for simplicity.
- **NER model** for company matching. Alias regex is enough.
- **True intra-day price streaming.** Daily bars, quarter unit.
- **UI in German.** English only, per requirements.
- **All 40 DAX constituents.** Currently 39 — DAX composition drifts
  ~annually; verify before an engagement.

---

## 9. Deployment: Docker + CapRover

### 9.1 Containerized, self-hosted (replaces Streamlit Community Cloud)
The app now ships as a Docker image (`dockerfile`, base `python:3.12-slim`)
deployed to a **CapRover** server via `captain-definition`. Reasons over
Streamlit Community Cloud:

- **No sleep/wake cycle.** Free-tier Streamlit Cloud containers sleep after
  ~12 h and lose the ~1.5 GB model cache; a self-hosted container stays up.
- **Room to grow.** CapRover lets us run companion services on the same
  host — a PostgreSQL instance (`srv-captain--dax-db:5432`, db `risk_data`)
  is already provisioned for future persistence.
- **Reproducible builds.** System deps (`build-essential`, `libpq-dev`) are
  pinned in the image; a Docker `HEALTHCHECK` on `/_stcore/health` lets
  CapRover detect a dead app.

Trade-off: the model cache still lives inside the container, so every
redeploy re-downloads the models on first use.

### 9.2 Headline cleaning at fetch time
Google News RSS titles arrive as `"Headline - Publisher"`. The publisher
suffix skews sentiment and topic scores, pollutes company-alias filtering
(publisher names can contain company names), and weakens fuzzy dedupe
(the same story from two publishers differs only by suffix). So
`services/news.py` strips the suffix **once, at RSS parse time**, before
anything downstream sees the title:

- The strip is guarded: it removes `" - {source_name}"` only when the
  title actually ends with the feed entry's own source name, falling back
  to splitting on the last `" - "`. Headlines that legitimately contain
  `" - "` survive intact.
- GDELT titles are untouched — the suffix convention is Google-specific.
- The original string is kept as `Headline.title_raw` and flows into the
  JSON snapshot, preserving traceability to what the source emitted.
- Side effect: the per-headline NLP cache key is now the clean title, so
  the same story syndicated by several publishers shares one model run.

An earlier version did this inside `app.py`'s `cached_analyze`, which
cleaned the text for the models but left filtering, dedupe, display, and
exports on the raw title.

### 9.3 Translation is scored, and now shown
`nlp.analyze` has always run FinBERT and the zero-shot classifier on the
**English** text (MarianMT translates German first — both scoring models
were trained on English). The translation is now also surfaced where the
auditor reads results: an "English" column in the results tables (filled
only for German headlines) and an `EN:` line under German headlines in the
PDF workpaper. Translation is deliberately **not** used in fetch/filter/
dedupe or the pre-analysis keyword search — those run before the ML
pipeline, and translating every raw headline would defeat the lightweight
paths.
