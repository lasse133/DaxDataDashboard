# Component Diagram

The main building blocks of the DAX 40 Audit Risk Radar and who depends on
whom. Arrows point from caller to callee.

## Legend

| Notation | Meaning |
|---|---|
| 🔵 Blue | **Presentation** — Streamlit UI (`app.py`) |
| 🟢 Teal | **Service module** — Python module in `services/` |
| 🟠 Amber cylinder | **Domain data** — YAML files (rules-as-data) |
| ⚪ Grey, dashed border | **External source** — outside the system boundary |
| `───▶` solid arrow | In-process function call |
| `╌╌╌▶` dotted arrow | Network I/O or local file read |

## Diagram

```mermaid
flowchart TB
    AUDITOR(["👤 Auditor (browser)"])

    APP["app.py — Streamlit UI<br/>sidebar · price panel · news table · risk radar · export"]

    subgraph SVC["services/"]
        PRICES["prices.py<br/>stock prices"]
        NEWS["news.py<br/>fetch + filter news"]
        NLP["nlp.py<br/>translate · sentiment · topics<br/>(3 pretrained transformers)"]
        RISK["risk.py<br/>ISA 315 rule engine"]
    end

    DOMAIN[("domain/*.yaml<br/>company aliases · 11 ISA 315 rules")]

    YAHOO["Yahoo Finance"]
    NEWSAPI["GDELT + Google News RSS"]
    HF["HuggingFace Hub<br/>(first run only)"]

    AUDITOR --> APP
    APP --> PRICES
    APP --> NEWS
    APP --> NLP
    APP --> RISK

    NEWS -.-> DOMAIN
    RISK -.-> DOMAIN
    PRICES -.-> YAHOO
    NEWS -.-> NEWSAPI
    NLP -.-> HF

    classDef ui fill:#2f6bd81a,stroke:#2f6bd8,color:#1c232d
    classDef svc fill:#0e8a761a,stroke:#0e8a76,color:#1c232d
    classDef data fill:#a97a1a1f,stroke:#a97a1a,color:#1c232d
    classDef ext fill:#66707d14,stroke:#66707d,stroke-dasharray:5 3,color:#1c232d
    classDef actor fill:#ffffff,stroke:#1c232d,color:#1c232d

    class APP ui
    class PRICES,NEWS,NLP,RISK svc
    class DOMAIN data
    class YAHOO,NEWSAPI,HF ext
    class AUDITOR actor
```

## Notes

- Everything except the bottom row runs in **one Streamlit process**.
- `nlp.py` wraps three pretrained models (MarianMT, FinBERT,
  DeBERTa-v3-MNLI), downloaded once from HuggingFace and cached locally.
- Audit rules live in YAML (**rules-as-data**), so `risk.py` stays a thin
  engine and the catalog is reviewable without reading code.
- For how the data moves through these components, see
  [`data-flow.md`](data-flow.md).
