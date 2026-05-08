# DaxDataDashboard

DAX40 Risk Monitoring Dashboard for a university Enterprise Architecture and
Big Data project.

The project goal is to support auditors and analysts by combining DAX40 company
master data, stock-market movements, and external news/search results. The data
pipeline writes CSV files first, so later dashboard code can read stable files
instead of scraping live every time the app opens.

## Data Pipeline

Run the scripts from the repository root:

```bash
python scrape_dax_companies.py
python scrape_stock_prices.py
python scrape_company_news.py
python scrape_google_search.py
python generate_risk_signals.py
```

The scripts create these files:

```text
data/dax_companies.csv
data/yahoo_ticker_mapping.csv
data/stock_prices.csv
data/company_news.csv
data/google_search_results.csv
data/risk_signals.csv
```

## Company Layer

`scrape_dax_companies.py` fetches the current DAX40 component list.

Preferred source:

```text
STOXX DAX components page
```

Fallback source:

```text
Wikipedia DAX constituents table
```

Output columns:

```text
company_name,sector,source,scraped_at
```

The company layer intentionally does not include Yahoo Finance tickers. Provider
specific stock ticker mapping is handled separately in:

```text
data/yahoo_ticker_mapping.csv
```

## Stock Layer

`scrape_stock_prices.py` reads `data/dax_companies.csv` and
`data/yahoo_ticker_mapping.csv`, fetches recent daily OHLCV data from Yahoo
Finance, and saves:

```text
data/stock_prices.csv
```

Output columns:

```text
company_name,yahoo_ticker,date,open,high,low,close,volume,source,scraped_at
```

## News Layer

`scrape_company_news.py` reads `data/dax_companies.csv`, searches recent company
news through Google News RSS, and saves:

```text
data/company_news.csv
```

Output columns:

```text
company_name,title,url,news_source,published_at,language,snippet,source,scraped_at
```

## Risk Signal Layer

## Google Search Layer

`scrape_google_search.py` optionally fetches Google Custom Search results for
each DAX company and saves:

```text
data/google_search_results.csv
```

This script requires Google credentials as environment variables:

```bash
$env:GOOGLE_API_KEY="your-api-key"
$env:GOOGLE_CSE_ID="your-search-engine-id"
python scrape_google_search.py
```

Output columns:

```text
company_name,rank,title,url,display_link,snippet,query,source,scraped_at
```

If the credentials are missing, the script prints a warning and skips this
optional layer. The rest of the pipeline still works.

## Risk Signal Layer

`generate_risk_signals.py` combines stock and news CSV files and creates simple,
explainable risk indicators:

```text
data/risk_signals.csv
```

Current signal examples:

- daily stock price drop of 5 percent or more
- latest trading volume at least twice the recent average
- negative news keywords such as fraud, lawsuit, investigation, cyberattack, or
  profit warning
- Google search results matching risk keywords

These rules are intentionally simple for the MVP. They can later be replaced by
more advanced scoring, sentiment analysis, or dashboard-side filtering.

Note: `scrape_company_news.py` also contains a GDELT helper, but Google News RSS
is the default because it was more reliable for the full DAX40 list during local
development.
