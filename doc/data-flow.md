# Data Flow Diagram

How data moves through the DAX 40 Audit Risk Radar: from external sources,
through the transforming processes, to the auditor. Solid arrows carry the
**data** that moves (nouns); dashed arrows carry the **request or control
signal** that triggers a flow. For structure see
[`component-diagram.md`](component-diagram.md).

## Legend

| Notation | Meaning |
|---|---|
| ⚪ Square, dashed border | **External entity** — source or sink of data |
| 🟢 Rounded, numbered | **Process** — transforms inputs into different outputs |
| 🟠 Cylinder | **Data store** — data at rest between processes |
| `───▶` solid arrow | **Data flow** — the named data that moves |
| `╌╌╌▶` dashed arrow | **Request / control** — the trigger, not the data |

## Diagram

```mermaid
flowchart LR


    %% External actor
    auditor["Audit analyst"]


    %% Main processes
    p1(["1.0 Select company,<br/>period and stock window"])
    p2(["2.0 Fetch external data"])
    p3(["3.0 Enrich and map<br/>audit risk signals"])
    p4(["4.0 Present dashboard results"])
    p5(["5.0 Export workpaper"])


    %% External systems
    news["News sources<br/>GDELT DOC 2.0<br/>Google News RSS"]
    yahoo["Yahoo Finance API"]
    hf["Hugging Face Hub<br/>MarianMT · FinBERT ·<br/>DeBERTa zero-shot"]


    %% Data stores / artifacts
    rules[("Rule and alias catalog<br/>company_aliases.yaml<br/>isa315_map.yaml")]
    cache[("In-memory state<br/>st.cache_data: headlines, prices,<br/>NLP analyses · st.session_state:<br/>results + risk flags")]


    %% Control / request flow = dashed
    auditor -. "selected company,<br/>reporting period,<br/>stock window" .-> p1
    p1 -. "news and price request" .-> p2
    p2 -. "article query" .-> news
    p2 -. "ticker and date range" .-> yahoo
    p3 -. "model download request<br/>(first run only)" .-> hf
    auditor -. "download click" .-> p5


    %% Data flow = solid
    news -- "article data:<br/>headline, URL, source, date" --> p2
    yahoo -- "daily OHLC stock prices" --> p2


    p2 -- "fetched articles<br/>and stock prices" --> p3


    hf -- "pretrained model weights<br/>(cached locally,<br/>inference runs in-app)" --> p3
    rules -- "company aliases<br/>(headline filtering)" --> p2
    rules -- "ISA 315 rules:<br/>categories, thresholds,<br/>severity, references" --> p3


    p3 -- "processed dashboard data:<br/>scored articles, risk flags,<br/>price summary" --> cache


    cache -- "cached results" --> p4
    p4 -- "risk radar,<br/>flagged articles,<br/>stock graph" --> auditor


    cache -- "processed articles,<br/>model outputs, risk flags,<br/>price summary" --> p5
    p5 -- "JSON snapshot /<br/>PDF workpaper<br/>(browser download)" --> auditor


    %% Styling
    classDef external fill:#d9e8ff,stroke:#4472c4,stroke-width:1px,color:#000;
    classDef process fill:#ffffff,stroke:#4472c4,stroke-width:1px,color:#000;
    classDef store fill:#ffe6a6,stroke:#d99000,stroke-width:1px,color:#000;


    class auditor,news,yahoo,hf external;
    class p1,p2,p3,p4,p5 process;
    class rules,cache store;
```

## Process descriptions

| # | Process | Transformation |
|---|---|---|
| 1.0 | Select company, period and stock window | Sidebar selections → fetch parameters (ticker, year + quarters, price date range) |
| 2.0 | Fetch external data | GDELT + Google News RSS headlines → publisher suffix stripped (`" - Source"`, RSS only; raw title kept) → alias-filtered, deduped list; Yahoo Finance → daily OHLC prices |
| 3.0 | Enrich and map audit risk signals | Clean headline → translated (DE→EN, MarianMT) → sentiment (FinBERT) + topic scores (DeBERTa zero-shot) → risk flags with ISA 315 references |
| 4.0 | Present dashboard results | Results + price summary → risk radar, flagged-headline drill-downs, stock graph |
| 5.0 | Export workpaper | Results + price summary → JSON snapshot and PDF workpaper, delivered as browser downloads |
