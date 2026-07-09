# DAX40 Audit Risk Radar

This repository currently contains two layers of history:

- the active implementation in `dax/`, which is the current `new_dax_update` version
- older root-level files and legacy batch artifacts that should be treated as archival unless you explicitly need them

The current project is a Streamlit dashboard for ISA 315 support. It uses live news fetching, per-headline streaming analysis, a risk radar, and JSON/PDF workpaper exports.

## Current files to keep

These are the files that match the current project state:

- `dax/app.py`
- `dax/services/news.py`
- `dax/services/prices.py`
- `dax/services/nlp.py`
- `dax/services/risk.py`
- `dax/domain/company_aliases.yaml`
- `dax/domain/isa315_map.yaml`
- `dax/doc/data-flow.md`
- `dax/doc/design-decisions.md`
- `dax/doc/risk-radar-output.md`
- `dax/README.md`
- `dax/pyproject.toml`
- `dax/requirements.txt`
- `dax/uv.lock`
- `diagrams/use-case-diagram.md`
- `diagrams/data-flow-diagram.md`

## Files that are legacy or older

These are the main leftovers from earlier versions of the project:

- `app.py`
- `config.py`
- `data_sources.py`
- `database.py`
- `nlp.py`
- `audit_references.py`
- `audit.jsonl`
- `gdelt_sample.json`
- `test_api.py`
- `pipeline/`
- `data/company_news.csv`
- `data/dax_companies.csv`
- `data/risk_signals.csv`
- `data/yahoo_ticker_mapping.csv`
- root-level `pyproject.toml`
- root-level `requirements.txt`
- root-level `uv.lock`

## Current architecture

The active branch uses:

- GDELT DOC 2.0 and Google News RSS for news
- Yahoo Finance for prices
- Hugging Face transformer models for translation, sentiment, and topic scoring
- a YAML rule catalog for ISA 315 risk mapping
- Streamlit session state for pause/resume/reset streaming behavior

The reporting-period view processes one headline per rerun, so the analyst can pause and resume the pipeline while keeping the UI responsive.

## Where to start

If you want the current version of the project, start with:

- [dax/app.py](dax/app.py)
- [dax/services/news.py](dax/services/news.py)
- [dax/services/risk.py](dax/services/risk.py)
- [dax/README.md](dax/README.md)

The diagrams in [diagrams/use-case-diagram.md](diagrams/use-case-diagram.md) and [diagrams/data-flow-diagram.md](diagrams/data-flow-diagram.md) now match this version.