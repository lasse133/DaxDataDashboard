# Data Flow Diagram

How data moves through the DAX 40 Audit Risk Radar: from external sources,
through the transforming processes, to the auditor. Every arrow is labeled
with the **data** that moves (nouns); the actions live inside the numbered
processes. Control flow (loops, buttons, ordering) is intentionally
omitted — for structure see [`component-diagram.md`](component-diagram.md).

## Legend

| Notation | Meaning |
|---|---|
| ⚪ Square, dashed border | **External entity** — source or sink of data |
| 🟢 Rounded, numbered | **Process** — transforms inputs into different outputs |
| 🟠 Cylinder | **Data store** — data at rest between processes |
| Labeled arrow | **Data flow** — the named data that moves |

## Diagram

```mermaid
---
<!-- config:
  layout: fixed -->
---
flowchart LR
    AUDITOR["👤 Auditor"] -- company + period --> P1(["1.0 Fetch & filter news"])
    NEWSAPI["GDELT +<br>Google News RSS"] -- raw headlines --> P1
    D2[("D2 · isa315_map.yaml")] -- ISA 315 rules --> P3(["3.0 Analyze &amp; flag risks<br>sentiment · topics · rules"])
    YAHOO["Yahoo Finance"] -- daily prices --> P2(["2.0 Fetch prices"])
    P2 -- price KPIs --> P4(["4.0 Render & export"])
    P4 -- export (JSON/PDF) --> AUDITOR_OUT["👤 Auditor *"]
    P1 -- filtered headlines --> P3
    P3 -- results + flags --> P4

     AUDITOR:::actor
     P1:::process
     NEWSAPI:::entity
     D2:::store
     P3:::process
     YAHOO:::entity
     P2:::process
     P4:::process
     AUDITOR_OUT:::actor
    classDef process fill:#0e8a761a,stroke:#0e8a76,color:#1c232d
    classDef store fill:#a97a1a1f,stroke:#a97a1a,color:#1c232d
    classDef entity fill:#66707d14,stroke:#66707d,stroke-dasharray:5 3,color:#1c232d
    classDef actor fill:#ffffff,stroke:#1c232d,color:#1c232d
```

\* The Auditor appears twice — as data source (left) and data sink (right).
Duplicating an external entity to keep flows from crossing the diagram is
standard DFD practice; the asterisk marks the duplicate.

## Process descriptions

| # | Process | Transformation |
|---|---|---|
| 1.0 | Fetch & filter news | Raw headlines → company-filtered, deduped headline list |
| 2.0 | Fetch prices | Daily OHLC prices → price KPIs |
| 3.0 | Analyze & flag risks | Headline → translated + sentiment + topics → risk flags with ISA 315 references |
| 4.0 | Render & export | Results + price KPIs → risk radar dashboard and JSON/PDF workpaper |
