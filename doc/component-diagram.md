# Component Diagram

The main building blocks of the DAX 40 Audit Risk Radar and who depends on
whom. Arrows point from caller to callee.

## Legend

| Notation | Meaning |
|---|---|
| 🔵 Blue | **Presentation** — Streamlit UI code in `app.py` |
| 🟣 Violet | **Data-access & pipeline layer** — cache wrappers in `app.py` |
| 🟢 Teal | **Service module** — Python module in `services/` |
| 🟠 Amber cylinder | **Data at rest** — YAML catalogs, session/cache state |
| ⚪ Grey, dashed border | **External source** — outside the system boundary |
| `───▶` solid arrow | In-process function call |
| `╌╌╌▶` dotted arrow | Network I/O or local file read |

## Diagram

```mermaid
flowchart TB
    AUDITOR(["👤 Auditor (browser)"])

    subgraph APP["app.py — rerun top-to-bottom on every interaction"]
        UI["Presentation layer<br/>sidebar · price panel · news table<br/>risk radar · drill-downs · export"]
        MID["Data-access & pipeline layer<br/>@st.cache_data / @st.cache_resource wrappers:<br/>cached_headlines · cached_prices ·<br/>cached_analyze · load_models"]
        STATE[("Session & cache state<br/>st.session_state: queue · results · paused<br/>st.cache_data entries")]
    end

    subgraph SVC["services/"]
        PRICES["prices.py<br/>stock prices"]
        NEWS["news.py<br/>fetch · clean · filter news"]
        NLP["nlp.py<br/>translate · sentiment · topics<br/>(3 pretrained transformers)"]
        RISK["risk.py<br/>ISA 315 rule engine"]
        DB["db.py<br/>PostgreSQL persistence<br/>(optional, read-through cache)"]
    end

    DOMAIN[("domain/*.yaml<br/>company aliases · 11 ISA 315 rules")]
    PG[("PostgreSQL risk_data<br/>nlp_cache · headline_cache<br/>(dax-db container, via DATABASE_URL)")]

    YAHOO["Yahoo Finance"]
    NEWSAPI["GDELT + Google News RSS"]
    HF["HuggingFace Hub<br/>(first run only)"]

    AUDITOR -->|"HTTPS + WebSocket<br/>(Streamlit server)"| UI
    UI --> MID
    UI --> STATE
    MID --> STATE
    MID --> PRICES
    MID --> NEWS
    MID --> NLP
    MID --> RISK
    MID --> DB

    DB -.-> PG
    NEWS -.-> DOMAIN
    RISK -.-> DOMAIN
    PRICES -.-> YAHOO
    NEWS -.-> NEWSAPI
    NLP -.-> HF

    classDef ui fill:#2f6bd81a,stroke:#2f6bd8,color:#1c232d
    classDef adapter fill:#7a4dd81a,stroke:#7a4dd8,color:#1c232d
    classDef svc fill:#0e8a761a,stroke:#0e8a76,color:#1c232d
    classDef data fill:#a97a1a1f,stroke:#a97a1a,color:#1c232d
    classDef ext fill:#66707d14,stroke:#66707d,stroke-dasharray:5 3,color:#1c232d
    classDef actor fill:#ffffff,stroke:#1c232d,color:#1c232d

    class UI ui
    class MID adapter
    class PRICES,NEWS,NLP,RISK,DB svc
    class DOMAIN,STATE,PG data
    class YAHOO,NEWSAPI,HF ext
    class AUDITOR actor
```

## Notes

- **Why the middle layer exists:** Streamlit re-executes `app.py` from top
  to bottom on every user interaction, so the presentation code never calls
  the service modules directly for expensive work. All network fetches and
  model inference go through `@st.cache_data` / `@st.cache_resource`
  wrapper functions (`app.py:280-435`), which return memoized results on
  reruns; `st.session_state` carries the streaming pipeline (queue,
  results, paused flag) across reruns.
- **Two cache layers:** the `@st.cache_data` wrappers memoize within the
  running process; `db.py` adds an optional PostgreSQL layer underneath
  (checked before fetching news or running models, written after), so
  transformer output and fetched headlines survive container restarts and
  redeploys. Without `DATABASE_URL` every `db.py` call is a no-op and the
  app is purely in-memory, as before.
- **Exception:** cheap, pure in-memory calls — `risk.evaluate`,
  `prices.summarize`, and the catalog loaders (`news.load_companies`,
  `risk.load_rules`) — are invoked from presentation code directly; they
  are safe and fast to re-run, so caching them would add nothing.
- Everything except the bottom row runs in **one Streamlit process**
  (packaged as a Docker container for CapRover — see
  [`deployment-diagram.md`](deployment-diagram.md)).
- `news.py` strips the publisher suffix Google News RSS appends
  (`"Headline - Source"` → `"Headline"`) at parse time, so filtering,
  dedupe, display, and the models all see the clean headline; the raw
  title is kept on each `Headline` as `title_raw` for traceability.
- `nlp.py` wraps three pretrained models (MarianMT, FinBERT,
  DeBERTa-v3-MNLI), downloaded once from HuggingFace and cached locally.
- Audit rules live in YAML (**rules-as-data**), so `risk.py` stays a thin
  engine and the catalog is reviewable without reading code.
- For how the data moves through these components, see
  [`data-flow.md`](data-flow.md).
