# DAX40 Dashboard Documentation

Based only on the current `new_dax_update` branch.

## a. Title Page

**Project title:** DAX40 Dashboard

**Subtitle:** Streamlit dashboard for DAX 40 audit risk monitoring with news, prices, and transformer-based risk signals

**Branch:** `new_dax_update`

**Scope:** This documentation describes the implementation that is present in the current branch, especially the Streamlit application in `dax/app.py`, the services in `dax/services/`, and the supporting YAML domain data in `dax/domain/`.

---

## b. Abstract / Intro

DAX40 Dashboard is a Streamlit application for audit risk monitoring. It supports the auditor's professional judgment by fetching live market and news data, scoring headlines with pretrained transformer models, and mapping the results to ISA 315-related risk rules.

The branch implements a live-fetch workflow with three main service areas:

- news retrieval from GDELT DOC 2.0 and Google News RSS,
- price retrieval from Yahoo Finance via `yfinance`,
- NLP-based translation, sentiment analysis, and zero-shot topic classification.

The application is designed around reporting periods rather than intraday trading. It uses quarter-based selection, manual refresh, cached model loading, and a rule catalog stored as data in YAML. The output is a risk radar view, flagged headline drill-downs, and a workpaper snapshot export in JSON and PDF.

The tool does not perform ISA 315 risk assessment itself. It provides transparent evidence and traceable risk flags for an auditor to review.

---

## c. Use Case Diagram and Use Cases

The branch includes a Mermaid use case diagram in `README.md` and the same idea is reflected in the Streamlit UI. The primary actor is the engagement team or audit analyst.

### Main use cases

- Select company: choose a DAX40 company from the sidebar.
- Select reporting period: choose one or more quarters for the reporting view.
- Fetch latest data: trigger live retrieval of news and prices.
- Score and tag headlines: run language detection, translation, sentiment analysis, and topic classification.
- Review risk signals and warnings: inspect the flagged headlines and the aggregated risk radar.
- Inspect article implications: open the expandable drill-downs with audit references and suggested procedures.
- View stock prices: inspect the price panel and KPI row for the selected period.
- Clear cached headlines: reset the cached news and analysis state.

### How the use cases relate

The sidebar controls initiate the fetch flow. The fetch flow feeds the scoring layer, which produces flags and summary outputs. Those outputs are then displayed in the risk radar, the table of headlines, and the workpaper export.

The branch's diagram keeps the analyst outside the system boundary and shows the internal actions as part of the dashboard system, which is the correct notation for the current documentation set.

See also: `README.md`, `dax/doc/data-flow.md`.

---

## d. Results as Data Preview or UX Screenshots

The branch does not contain stored screenshot files, so this section is described from the implemented UI instead of fabricated images.

### Output views present in the app

- The main risk radar section shows aggregated flags by ISA 315 category and severity.
- The flagged-headline drill-down shows the headline, risk rule, sentiment, matched topics, audit references, and suggested procedures.
- The workpaper snapshot section provides JSON and PDF downloads.
- The reporting-period workspace includes stock price KPIs and a price chart.
- The lightweight news workspaces provide diagnostics, keyword search, and risk-driver term charts.
- The sidebar exposes the selected company, year, quarter selection, stock price range, and the deep-learning model registry.

### Suggested screenshot set for a report

If you want to include screenshots in a submission, the branch supports capturing these views:

- sidebar and company selection,
- reporting-period results table,
- risk radar chart,
- one expanded flagged headline,
- JSON and PDF workpaper download area,
- price chart and KPI row.

These are the actual UX elements implemented in the branch; no additional screenshot content is implied here.

---

## e. Ideal and Real Architecture

### Ideal architecture

The documentation in the branch presents the system as a layered architecture:

- UI layer: Streamlit app in `dax/app.py`
- Service layer: `dax/services/news.py`, `dax/services/prices.py`, `dax/services/nlp.py`, `dax/services/risk.py`
- Domain layer: YAML rule and alias catalogs in `dax/domain/`
- External sources: GDELT DOC 2.0, Google News RSS, Yahoo Finance, and Hugging Face model downloads on first run

The data flow is:

1. The user selects a company and reporting period.
2. News and price data are fetched live.
3. Headlines are translated if needed, then scored for sentiment and topics.
4. The YAML rule catalog is evaluated against the NLP output.
5. The dashboard renders the risk radar, detailed flags, and exportable workpaper output.

### Real architecture in the branch

The implemented architecture is a single-user Streamlit application running locally with cached model loading and local SQLite storage for scored headlines.

Key runtime characteristics:

- Streamlit provides the UI and rerun-based interaction model.
- `services/news.py` fetches and merges headlines from free news sources and filters them to the selected company.
- `services/prices.py` fetches daily OHLC bars from Yahoo Finance.
- `services/nlp.py` loads pretrained transformer pipelines lazily and runs one headline at a time.
- `services/risk.py` maps analysis results to risk flags from `dax/domain/isa315_map.yaml`.
- The app exports a JSON snapshot and a PDF workpaper from the processed results.

### Deployment view

The branch does not include a container or multi-server deployment design. The practical deployment is a local Python environment started through Streamlit. The repository includes both `requirements.txt` and `pyproject.toml` / `uv.lock`, so the application can be run with either a virtual environment or uv-based setup.

---

## f. Design Decisions

The current branch records several clear design choices.

- The primary user is an auditor, not a general analyst. The UI and output focus on traceability and workpaper value.
- Quarter-based reporting is used instead of intraday streaming because the audit use case is period-based.
- Refresh is manual. The app updates when the user clicks the fetch button, which keeps the view stable and reduces unnecessary API calls.
- The UI is in English, while the headline handling supports German and English input.
- The rule catalog is stored as YAML, which keeps audit rules reviewable without reading Python code.
- The scoring process is transparent. Each flag exposes the matched topics, sentiment, audit references, and suggested procedures.
- The app uses free sources and lightweight infrastructure: GDELT DOC 2.0, Google News RSS, and Yahoo Finance.
- Results are cached so repeat views are fast and repeated model runs are reduced.
- The dashboard supports export of JSON and PDF workpaper artifacts.

The branch also documents deliberate constraints: no multi-user auth, no Kafka or Spark, and no intraday streaming.

---

## g. Implementation Details

This branch implements the system through a small set of focused modules.

### Streamlit UI

`dax/app.py` contains the presentation layer. It configures the page, renders the sidebar, drives the fetch flow, shows the main charts and tables, and builds the JSON and PDF exports.

The UI is designed around a one-headline-per-rerun pipeline. That means Streamlit processes a single headline on each rerun, which keeps the pause and resume behavior responsive.

### News handling

`dax/services/news.py` provides the news layer.

- It loads the company alias catalog from `dax/domain/company_aliases.yaml`.
- It fetches headlines from GDELT DOC 2.0 and Google News RSS.
- It retries and throttles GDELT calls to stay within rate limits.
- It filters headlines to the selected company.
- It deduplicates near-identical headlines with RapidFuzz.
- It returns diagnostics so the UI can show why a result set is empty.

### Stock prices

`dax/services/prices.py` fetches daily OHLC data from Yahoo Finance.

- The branch uses daily bars rather than intraday prices.
- The code also supports a custom date range and a small summary object for the KPI row.

### NLP pipeline

`dax/services/nlp.py` loads three pretrained transformer pipelines:

- MarianMT for German to English translation,
- FinBERT for sentiment analysis,
- a DeBERTa-v3-based zero-shot classifier for audit-topic classification.

The language detector is seeded for reproducibility. The output is packaged into an analysis object that the UI can render and the rule engine can inspect.

### Risk mapping

`dax/services/risk.py` evaluates the NLP analysis against `dax/domain/isa315_map.yaml`.

- The rule threshold for topics is `0.55`.
- Rules can require a matching sentiment label and minimum sentiment score.
- Each fired rule becomes a structured risk flag with audit references and suggested procedures.
- The rule catalog currently contains 11 ISA 315-related categories.

### Export and traceability

The app builds a JSON snapshot and a PDF workpaper from the processed results. That snapshot includes the company, selected period, price summary, model registry, headlines, analysis output, and the fired flags.

### Runtime and packaging

The branch includes both `dax/requirements.txt` and `dax/pyproject.toml` with `uv.lock`. That means the app can be run with either plain pip or uv-based dependency management.

---

## h. Expert Comment and Outlook

The branch does not name actual experts, so the section below is a fill-in template rather than invented names.

### Business expert

**Name:** To be provided outside the branch

**Domain:** Business

**Comment:** The dashboard is useful as a structured evidence view for audit workflows because it turns live news and market data into an explainable risk summary.

**Outlook:** Future work could focus on clearer engagement-level reporting and more explicit audit workflow support.

### EA expert

**Name:** To be provided outside the branch

**Domain:** EA

**Comment:** The architecture is intentionally simple and layered. The UI, service layer, domain rules, and external sources are separated cleanly.

**Outlook:** A future architectural extension could add a clearer deployment story if the tool needs to move beyond local Streamlit execution.

### Big Data expert

**Name:** To be provided outside the branch

**Domain:** Big Data

**Comment:** The project uses live external APIs, caching, deduplication, and pretrained models, but it does not use a distributed compute stack.

**Outlook:** If scale or throughput becomes important, the news ingestion and scoring stages would be the first candidates for further data-pipeline work.

---

## References in the branch

- `README.md`
- `dax/README.md`
- `dax/doc/data-flow.md`
- `dax/doc/design-decisions.md`
- `dax/doc/risk-radar-output.md`
- `dax/app.py`
- `dax/services/news.py`
- `dax/services/prices.py`
- `dax/services/nlp.py`
- `dax/services/risk.py`
- `dax/domain/isa315_map.yaml`
- `dax/domain/company_aliases.yaml`
