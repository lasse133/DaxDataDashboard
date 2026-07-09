# Deployment Diagram

Physical view of the DAX 40 Audit Risk Radar deployed on **Streamlit
Community Cloud**: which node runs what, and which protocols connect them.
The whole app — UI, services, and all three transformer models — runs in a
single cloud container; the browser only renders the Streamlit frontend.

## Legend

| Notation | Meaning |
|---|---|
| Frame («device» / «node») | **Node** — a physical or virtual execution environment |
| 🟢 Teal | **Deployed artifact** — this repo's code running on the node |
| 🟠 Amber cylinder | **Data at rest** on the node (model cache) |
| ⚪ Grey, dashed border | **External service** — infrastructure we don't operate |
| `───▶` solid arrow | User traffic (HTTPS + WebSocket) |
| `╌╌╌▶` dotted arrow | Outbound HTTPS or the deploy pipeline |

## Diagram

```mermaid
flowchart LR
    subgraph CLIENT["«device» Auditor's computer"]
        BROWSER["Web browser<br/>renders Streamlit frontend"]
    end

    subgraph CLOUD["«node» Streamlit Community Cloud · Linux container (~2.7 GB RAM)"]
        APP["Streamlit server · Python<br/>app.py · services/ · domain/*.yaml"]
        CACHE[("HF model cache<br/>~1.5 GB · filled on first run")]
    end

    GITHUB["GitHub<br/>lasse133/DaxDataDashboard"]
    YAHOO["Yahoo Finance"]
    NEWSAPI["GDELT + Google News RSS"]
    HF["HuggingFace Hub"]

    BROWSER -->|"HTTPS + WebSocket"| APP
    GITHUB -.->|"auto-redeploy on push to main"| CLOUD
    APP -->|"loads model weights"| CACHE
    APP -.->|"HTTPS"| YAHOO
    APP -.->|"HTTPS"| NEWSAPI
    HF -.->|"HTTPS · first run only"| CACHE

    classDef artifact fill:#0e8a761a,stroke:#0e8a76,color:#1c232d
    classDef store fill:#a97a1a1f,stroke:#a97a1a,color:#1c232d
    classDef ext fill:#66707d14,stroke:#66707d,stroke-dasharray:5 3,color:#1c232d
    classDef client fill:#2f6bd81a,stroke:#2f6bd8,color:#1c232d

    class APP artifact
    class CACHE store
    class GITHUB,YAHOO,NEWSAPI,HF ext
    class BROWSER client
```

## Notes

- **One container does everything.** There is no separate backend, database,
  or GPU — all inference runs on the container's CPU, and results live in
  Streamlit session state (lost when the container restarts).
- **Deploys are git-driven.** Streamlit Cloud watches `main` and rebuilds
  the container on every push; `requirements.txt` pins the CPU-only torch
  wheel to fit the container.
- **Sleep/wake behavior.** Free-tier containers sleep after ~12 h without
  traffic; the model cache is lost on restart, so the first visitor after a
  wake waits for the ~1.5 GB re-download from HuggingFace.
- Companion views: structure in
  [`component-diagram.md`](component-diagram.md), data movement in
  [`data-flow.md`](data-flow.md).
