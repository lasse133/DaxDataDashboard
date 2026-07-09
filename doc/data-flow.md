# Data Flow Diagram

End-to-end data flow of the DAX 40 Audit Risk Radar, from user click to
rendered risk flag. All diagrams are Mermaid — GitHub, VS Code, and most
Markdown viewers render them inline.

---

## 1. High-level system view

```mermaid
flowchart TB
    subgraph User["👤 Auditor"]
        UI_ACT["Select ticker, year, quarters<br/>Click 🔄 Fetch"]
    end

    subgraph StreamlitApp["Streamlit App (app.py)"]
        SIDEBAR["Sidebar controls"]
        PRICE_PANEL["Price panel + KPI row"]
        NEWS_PANEL["News table (streamed rows)"]
        RISK_PANEL["Risk radar chart + drill-downs"]
        SNAPSHOT["JSON snapshot export"]
    end

    subgraph Services["Services (services/*)"]
        PRICES["prices.py<br/>yfinance wrapper"]
        NEWS["news.py<br/>GDELT + Google RSS<br/>+ dedupe + filter"]
        NLP["nlp.py<br/>translate → sentiment + topics"]
        RISK["risk.py<br/>YAML rule engine"]
    end

    subgraph Domain["Domain data (domain/*.yaml)"]
        ALIASES[("company_aliases.yaml<br/>39 DAX tickers")]
        RULES[("isa315_map.yaml<br/>11 audit rules")]
    end

    subgraph External["External sources (free, no key)"]
        YAHOO["Yahoo Finance API"]
        GDELT["GDELT DOC 2.0 API"]
        GRSS["Google News RSS"]
        HF["HuggingFace Model Hub<br/>(first-run download)"]
    end

    UI_ACT --> SIDEBAR
    SIDEBAR --> PRICES
    SIDEBAR --> NEWS
    PRICES --> YAHOO
    PRICES --> PRICE_PANEL
    NEWS --> GDELT
    NEWS --> GRSS
    NEWS --> ALIASES
    NEWS --> NEWS_PANEL
    NEWS_PANEL --> NLP
    NLP --> HF
    NLP --> RISK
    RISK --> RULES
    RISK --> NEWS_PANEL
    RISK --> RISK_PANEL
    NEWS_PANEL --> SNAPSHOT
    RISK_PANEL --> SNAPSHOT
```

---

## 2. Per-headline processing pipeline

The streaming pipeline. One headline flows through these stages per
`st.rerun()`; the app processes exactly one row per script pass so that
Pause / Resume buttons remain responsive.

```mermaid
flowchart LR
    QUEUE([session_state.queue]) --> POP["Pop next headline"]
    POP --> LANG["Language detect<br/>(langdetect, seeded)"]
    LANG -->|de| TRANS["Translate DE→EN<br/>MarianMT ~74M"]
    LANG -->|en| PASS[/pass-through/]
    TRANS --> SENT["Sentiment<br/>FinBERT ~110M"]
    PASS --> SENT
    TRANS --> TOPICS["Zero-shot topics<br/>DeBERTa-v3-MNLI ~184M"]
    PASS --> TOPICS
    SENT --> ANALYSIS[[Analysis object]]
    TOPICS --> ANALYSIS
    ANALYSIS --> MAPPER["Rule engine<br/>(risk.py)"]
    MAPPER --> RULES[("isa315_map.yaml")]
    MAPPER --> FLAGS[[RiskFlag list]]
    ANALYSIS --> RESULTS([session_state.results])
    FLAGS --> RESULTS
    RESULTS --> RERUN["st.rerun()<br/>→ process next"]
    RERUN --> QUEUE
```

Cache boundaries around this pipeline (all in `app.py`):

- `@st.cache_resource` on `load_models()` — transformers loaded once per
  Streamlit process
- `@st.cache_data` on `cached_analyze(title, hint, topics_key)` — same
  headline text always yields the same output; the cache lets a Reset skip
  redundant re-inference

---

## 3. News fetch flow

Details of how a click on **Fetch latest data** turns into a headline
list. The multi-quarter path collapses GDELT into a single API call to
stay under its rate limit.

```mermaid
flowchart TB
    START(["🔄 Fetch clicked"]) --> BUMP["Bump refresh_nonce<br/>Clear caches"]
    BUMP --> MULTI["news.fetch_headlines_multi<br/>(ticker, year, quarters)"]
    MULTI --> WIDE["Compute period_start / period_end<br/>= min(Qs).start → max(Qs).end"]
    WIDE --> GDELT_CALL{"GDELT call<br/>throttled ≥5s"}
    GDELT_CALL -->|"HTTP 200"| GDELT_PARSE["Parse JSON<br/>Build Headline objects"]
    GDELT_CALL -->|"HTTP 429"| BACKOFF["Backoff 3s → 6s → 12s<br/>(3 attempts)"]
    BACKOFF --> GDELT_CALL
    GDELT_CALL -->|"Non-JSON / net error"| DIAG_ERR["Record error in FetchReport"]

    MULTI --> LOOP_Q["For each selected quarter"]
    LOOP_Q --> RSS_EN["Google RSS · en-US"]
    LOOP_Q --> RSS_DE["Google RSS · de-DE"]
    RSS_EN --> RSS_PARSE["Parse feed<br/>Filter to quarter window"]
    RSS_DE --> RSS_PARSE

    GDELT_PARSE --> MERGE["Merge headline lists"]
    RSS_PARSE --> MERGE
    MERGE --> FILTER["Filter: title mentions<br/>any company alias"]
    FILTER --> ALIAS_YAML[("company_aliases.yaml")]
    FILTER --> DEDUPE["Dedupe by fuzzy title match<br/>(rapidfuzz ≥ 88)"]
    DEDUPE --> SORTED["Sort newest-first"]
    SORTED --> QUARTER_STAMP["Bucket each headline<br/>into its actual quarter"]
    QUARTER_STAMP --> OUT([List of Headline dicts])
    DIAG_ERR --> DIAG_UI["Diagnostics expander<br/>in UI"]
```

---

## 4. State transitions during processing

How `st.session_state` evolves while the pipeline runs. Every rerun of the
Streamlit script inspects this state, processes at most one headline, and
triggers the next rerun.

```mermaid
stateDiagram-v2
    [*] --> Empty: page load
    Empty --> Fetching: click 🔄 Fetch
    Fetching --> Priming: headlines returned, signature stored
    Fetching --> Empty: 0 headlines (show diagnostics)
    Priming --> Processing: queue populated
    Processing --> Processing: process 1 headline / rerun
    Processing --> Paused: click ⏸ Pause
    Paused --> Processing: click ▶ Resume
    Processing --> Done: queue empty
    Paused --> Priming: click ↺ Reset
    Done --> Priming: click ↺ Reset
    Done --> Fetching: click 🔄 Fetch again
    Paused --> Fetching: click 🔄 Fetch again
```

---

## 5. Snapshot export flow

A workpaper artifact — everything an auditor would need to reproduce the
current view offline.

```mermaid
flowchart LR
    RESULTS[/session_state.results/] --> BUILD["Build snapshot dict"]
    COMPANY[/ticker + aliases/] --> BUILD
    PRICE_SUMMARY[/price summary KPIs/] --> BUILD
    PERIOD[/year + quarters/] --> BUILD
    MODEL_REG[/MODELS registry<br/>services.nlp.MODELS/] --> BUILD
    BUILD --> JSON["Serialize to JSON<br/>(indent=2)"]
    JSON --> DOWNLOAD["⬇️ Download button<br/>Filename: TICKER_YEAR_Q1-Q2-..._snapshot.json"]
```
