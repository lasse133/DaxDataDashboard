from __future__ import annotations

import datetime as dt
import csv
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import config

PROJECT_ROOT = Path(__file__).resolve().parent
# NOTE: This app is fully streaming — every value is fetched live from an API at
# request time. No scraped CSV in data/ is read at runtime (the data/ folder only
# holds the SQLite cache of already-scored headlines, audit_radar.db).


# =============================================================================
# 1. STOCK PRICES  (live, no API key required, NO fallback to CSV)
# =============================================================================

def get_prices(tickers: Iterable[str], start_date=None):
    """Fetch live stock prices directly from Yahoo's hidden JSON API."""
    import requests
    import pandas as pd
    from urllib.parse import quote

    out = {}
    tickers = list(tickers)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    price_start_date = start_date or config.PRICE_START_DATE

    # 1. Dynamically calculate the date range
    if price_start_date:
        # Convert the Streamlit calendar date into a Unix timestamp (period1)
        p1 = int(pd.to_datetime(price_start_date).timestamp())
        # Set the end date to right now (period2)
        p2 = int(pd.Timestamp.now().timestamp())
        
        api_params = {
            "period1": p1,
            "period2": p2,
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }
    else:
        # Fallback if no date is selected
        api_params = {
            "range": "1y",
            "interval": "1d",
            "includePrePost": "false",
            "events": "history",
        }

    for ticker in tickers:
        try:
            # 2. Hit the Yahoo Chart API
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}"
            
            res = requests.get(url, params=api_params, headers=headers, timeout=5)
            res.raise_for_status()
            data = res.json()

            # 3. Parse the JSON payload
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue

            timestamps = result[0].get("timestamp", [])
            quote_data = result[0].get("indicators", {}).get("quote", [{}])[0]
            closes = quote_data.get("close", [])

            if not timestamps or not closes:
                continue

            # 4. Convert to a Pandas DataFrame
            history_df = pd.DataFrame({
                "date": pd.to_datetime(timestamps, unit="s", utc=True),
                "close": closes
            }).dropna()

            if history_df.empty:
                continue

            # 5. Format the output for the Streamlit UI
            history_series = history_df.set_index("date")["close"]
            
            last = float(history_series.iloc[-1])
            first = float(history_series.iloc[0])
            pct = (last - first) / first * 100 if first else 0.0

            out[ticker] = {
                "last": last,
                "pct_change": pct,
                "history": history_series
            }

        except Exception as e:
            print(f"[get_prices] Direct API fetch failed for {ticker}: {e}")
            continue
            
    return out

import time
import streamlit as st

# =============================================================================
# 2. NEWS STREAM (Live NewsAPI Mode)
# =============================================================================

# Non-Latin scripts (CJK, Cyrillic, Hebrew, Arabic, Thai) — an English backstop
# on top of NewsAPI's language=en filter.
_NON_LATIN = re.compile(
    "[぀-ヿ㐀-鿿가-힯"   # Japanese kana, CJK, Hangul
    "Ѐ-ӿ֐-׿؀-ۿ"      # Cyrillic, Hebrew, Arabic
    "฀-๿]"                               # Thai
)


def _is_probably_english(text: str) -> bool:
    """English backstop: reject titles containing non-Latin-script characters."""
    return bool(text) and not _NON_LATIN.search(text)


DATE_WINDOWS = [
    ("2025-01-01", "2025-02-01"),
    ("2025-02-01", "2025-03-01"),
    ("2025-03-01", "2025-04-01"),
    ("2025-04-01", "2025-05-01"),
    ("2025-05-01", "2025-06-01"),
    ("2025-06-01", "2025-07-01"),
    ("2025-07-01", "2025-08-01"),
    ("2025-08-01", "2025-09-01"),
    ("2025-09-01", "2025-10-01"),
    ("2025-10-01", "2025-11-01"),
    ("2025-11-01", "2025-12-01"),
    ("2025-12-01", "2026-01-01"),
    ("2026-01-01", "2026-02-01"),
    ("2026-02-01", "2026-03-01"),
    ("2026-03-01", "2026-04-01"),
    ("2026-04-01", "2026-05-01"),
    ("2026-05-01", "2026-06-01"),
    ("2026-06-01", "2026-07-01"),
    ("2026-07-01", "2026-08-01"),
    ("2026-08-01", "2026-09-01"),
]

COMPANY_ALIASES = {
    "Adidas": ["Adidas", "adidas AG", "Adidas Germany", "Adidas Originals"],
    "Airbus": ["Airbus", "Airbus SE", "Airbus Group", "Airbus Defence", "Airbus Helicopters", "A320", "A350"],
    "Allianz": ["Allianz", "Allianz SE", "Allianz Group", "Allianz Global Investors", "AllianzGI", "PIMCO"],
    "BASF": ["BASF", "BASF SE", "BASF Group", "BASF chemicals", "BASF Ludwigshafen"],
    "Bayer": ["Bayer", "Bayer AG", "Bayer Group", "Monsanto", "Roundup", "glyphosate", "Glyphosat", "Crop Science"],
    "Beiersdorf": ["Beiersdorf", "Beiersdorf AG", "Nivea", "Eucerin", "La Prairie", "Hansaplast"],
    "BMW": ["BMW", "BMW AG", "BMW Group", "Bayerische Motoren Werke", "MINI", "Rolls-Royce Motor Cars", "BMW Motorrad"],
    "Brenntag": ["Brenntag", "Brenntag SE", "Brenntag Group", "Brenntag Essentials", "Brenntag Specialties"],
    "Commerzbank": ["Commerzbank", "Commerzbank AG", "Commerzbank Group", "Comdirect", "mBank", "Commerz Real"],
    "Continental": ["Continental", "Continental AG", "Conti", "Continental Automotive", "Continental Tires", "ContiTech"],
    "Daimler Truck": ["Daimler Truck", "Daimler Truck Holding", "Mercedes-Benz Trucks", "Freightliner", "FUSO"],
    "Deutsche Bank": ["Deutsche Bank", "Deutsche Bank AG", "DBK", "DWS", "Postbank"],
    "Deutsche Boerse": ["Deutsche Boerse", "Deutsche Börse", "Clearstream", "Eurex", "Xetra", "STOXX", "ISS STOXX"],
    "Deutsche Post (DHL)": ["DHL", "DHL Group", "Deutsche Post", "Deutsche Post DHL", "DHL Express", "DHL Supply Chain"],
    "Deutsche Telekom": ["Deutsche Telekom", "Deutsche Telekom AG", "Telekom", "T-Mobile", "T-Mobile US", "Magenta"],
    "E.ON": ["E.ON", "Eon", "E.ON SE", "E.ON Group", "Westenergie", "PreussenElektra"],
    "Fresenius": ["Fresenius", "Fresenius SE", "Fresenius Group", "Fresenius Kabi", "Fresenius Helios", "Helios Kliniken"],
    "Fresenius Medical Care": ["Fresenius Medical Care", "FMC", "Fresenius Medical Care AG", "dialysis provider", "renal care"],
    "GEA": ["GEA", "GEA Group", "GEA Group AG", "GEA engineering", "GEA food processing"],
    "Hannover Rueck": ["Hannover Rueck", "Hannover Rück", "Hannover Re", "Hannover Reinsurance"],
    "Heidelberg Materials": ["Heidelberg Materials", "HeidelbergCement", "Heidelberg Cement", "cement group", "building materials"],
    "Henkel": ["Henkel", "Henkel AG", "Henkel KGaA", "Persil", "Schwarzkopf", "Loctite", "Pritt"],
    "Hochtief": ["HOCHTIEF", "Hochtief AG", "Hochtief Group", "Turner Construction", "CIMIC", "ACS Hochtief"],
    "Infineon": ["Infineon", "Infineon Technologies", "Infineon Technologies AG", "chipmaker Infineon"],
    "Mercedes-Benz": ["Mercedes-Benz", "Mercedes Benz", "Mercedes-Benz Group", "Mercedes-Benz Group AG", "Daimler"],
    "Merck": ["Merck KGaA", "Merck Germany", "Merck Darmstadt", "Merck Healthcare", "Merck Life Science", "EMD Group"],
    "MTU Aero Engines": ["MTU Aero Engines", "MTU Aero", "MTU Aero Engines AG", "MTU maintenance"],
    "Munich Re": ["Munich Re", "Münchener Rück", "Muenchener Rueck", "Munich Reinsurance", "ERGO", "MEAG"],
    "Qiagen": ["Qiagen", "QIAGEN", "Qiagen N.V.", "QIAstat", "NeuMoDx", "Sample to Insight"],
    "Rheinmetall": ["Rheinmetall", "Rheinmetall AG", "Rheinmetall Defence", "Rheinmetall ammunition"],
    "RWE": ["RWE", "RWE AG", "RWE Renewables", "RWE Power", "RWE Generation"],
    "SAP": ["SAP", "SAP SE", "SAP software", "SAP cloud", "SAP S/4HANA", "SAP SuccessFactors", "SAP Concur"],
    "Scout24": ["Scout24", "Scout24 SE", "ImmoScout24", "ImmobilienScout24"],
    "Siemens": ["Siemens", "Siemens AG", "Siemens Digital Industries", "Siemens Smart Infrastructure", "Siemens Mobility"],
    "Siemens Energy": ["Siemens Energy", "Siemens Energy AG", "Siemens Gamesa", "Gamesa"],
    "Siemens Healthineers": ["Siemens Healthineers", "Siemens Healthineers AG", "Healthineers", "Varian", "Atellica"],
    "Symrise": ["Symrise", "Symrise AG", "Symrise Group", "Diana Food", "Holzminden Symrise"],
    "Volkswagen": ["Volkswagen", "VW", "Volkswagen AG", "Volkswagen Group", "Audi", "Skoda", "SEAT", "Cupra", "Bentley", "MAN", "Traton"],
    "Vonovia": ["Vonovia", "Vonovia SE", "Vonovia Group", "Deutsche Wohnen", "residential landlord Vonovia"],
    "Zalando": ["Zalando", "Zalando SE", "Zalando Group", "Zalando Lounge"],
}


AUDIT_RISK_QUERY_TERMS = {
    "regulatory_legal": ["lawsuit", "litigation", "fine", "antitrust", "regulatory investigation", "Klage", "Rechtsstreit", "Bußgeld", "Kartellamt", "Ermittlung"],
    "provisions_contingent_liabilities": ["provision", "litigation reserve", "contingent liability", "claims", "damages", "Rückstellung", "Eventualverbindlichkeit", "Schadenersatz"],
    "financial_liquidity": ["liquidity", "cash flow", "debt", "downgrade", "capital increase", "financing pressure", "Liquidität", "Cashflow", "Schulden", "Kapitalerhöhung"],
    "earnings_forecast_impairment": ["profit warning", "loss", "earnings decline", "revenue decline", "forecast cut", "impairment", "Gewinnwarnung", "Verlust", "Umsatzrückgang", "Wertminderung"],
    "operational_supply_chain": ["supply chain", "delivery delay", "production halt", "plant closure", "shortage", "Lieferkette", "Lieferverzug", "Produktionsstopp", "Engpass"],
    "restructuring_labor": ["restructuring", "job cuts", "layoffs", "cost cutting", "strike", "Restrukturierung", "Stellenabbau", "Sparprogramm", "Streik"],
    "product_quality_recall": ["recall", "defect", "safety issue", "quality issue", "product liability", "Rückruf", "Defekt", "Sicherheitsproblem", "Produkthaftung"],
    "cyber_it_data": ["cyberattack", "ransomware", "data breach", "IT outage", "security incident", "Cyberangriff", "Ransomware", "Datenleck", "IT-Ausfall"],
    "governance_fraud_accounting": ["fraud", "corruption", "accounting issue", "restatement", "internal controls", "Betrug", "Korruption", "Bilanzfehler", "interne Kontrollen"],
    "tax_customs_trade": ["tax investigation", "tax dispute", "customs", "tariffs", "trade restrictions", "Steuerprüfung", "Steuerstreit", "Zoll", "Handelsbeschränkung"],
    "esg_climate_environment": ["emissions", "climate lawsuit", "greenwashing", "pollution", "supply chain law", "Emissionen", "Klimaklage", "Greenwashing", "Lieferkettengesetz"],
    "market_demand_macro": ["weak demand", "order decline", "price pressure", "margin pressure", "China slowdown", "schwache Nachfrage", "Auftragsrückgang", "Margendruck", "China-Schwäche"],
    "ma_strategy_assets": ["acquisition", "takeover", "merger", "divestment", "spin-off", "joint venture", "Übernahme", "Fusion", "Akquisition", "Abspaltung"],
}


SECTOR_SPECIFIC_QUERY_TERMS = {
    "Consumer Goods": ["recall", "consumer demand", "inventory", "brand pressure", "pricing pressure", "Rückruf", "Konsumnachfrage", "Lagerbestand", "Preisdruck"],
    "Consumer Services": ["online sales", "weak consumer spending", "returns", "pricing pressure", "Online-Umsatz", "schwacher Konsum", "Retouren", "Preisdruck"],
    "Pharma and Healthcare": ["clinical trial failure", "drug approval", "FDA warning", "patent expiry", "side effects", "Studienfehlschlag", "Arzneimittelzulassung", "Patentablauf", "Nebenwirkungen"],
    "Utilities": ["power outage", "grid failure", "energy prices", "gas supply", "coal phase-out", "Stromausfall", "Netzausfall", "Energiepreise", "Gasversorgung", "Kohleausstieg"],
    "Finance, Insurance and Real Estate": ["loan loss provisions", "credit losses", "capital ratio", "solvency ratio", "catastrophe losses", "property valuation", "Kreditrisikovorsorge", "Kapitalquote", "Solvenzquote", "Immobilienbewertung"],
    "Information Technology": ["software outage", "cloud outage", "cybersecurity", "license revenue", "semiconductor demand", "Softwareausfall", "Cloud-Ausfall", "Cybersicherheit", "Lizenzerlöse"],
    "Industrials": ["order intake", "project delay", "cost overrun", "supply chain", "industrial demand", "defense orders", "Auftragseingang", "Projektverzögerung", "Kostenüberschreitung", "Lieferkette"],
    "Basic Materials": ["chemical prices", "raw material costs", "energy costs", "plant shutdown", "environmental regulation", "Chemiepreise", "Rohstoffkosten", "Energiekosten", "Anlagenstillstand"],
    "Telecomunication": ["network outage", "data breach", "spectrum auction", "regulatory fine", "Netzausfall", "Datenleck", "Frequenzauktion", "Bußgeld"],
}


LOW_VALUE_NEWS_DOMAINS = {
    "insidermonkey.com",
    "marketbeat.com",
    "defenseworld.net",
    "etfdailynews.com",
    "modernreaders.com",
    "theenterprisereader.com",
    "theenterpriseleader.com",
    "tickerreport.com",
    "wkbr13.com",
    "dailypolitical.com",
}

LOW_VALUE_HEADLINE_TERMS = [
    "bull case",
    "stocks to buy",
    "stock could",
    "trending ai stocks",
    "wall street radar",
    "shares purchased",
    "makes new investment",
    "new position in",
    "lowers position",
    "boosts stock position",
    "acquires shares",
    "sells shares",
    "dividend stock",
    "mega-cap stock",
]

HIGH_VALUE_AUDIT_TERMS = [
    "lawsuit", "litigation", "fine", "antitrust", "probe", "investigation",
    "regulatory", "compliance", "cyberattack", "data breach", "outage",
    "profit warning", "forecast cut", "guidance cut", "earnings decline",
    "revenue decline", "margin pressure", "impairment", "restructuring",
    "job cuts", "layoffs", "cost cutting", "cash flow", "liquidity", "debt",
    "acquisition", "takeover", "divestment", "merger",
    "klage", "rechtsstreit", "ermittlung", "kartellamt", "bussgeld",
    "gewinnwarnung", "umsatzrueckgang", "restrukturierung", "stellenabbau",
]

BUSINESS_RELEVANCE_TERMS = [
    "earnings", "revenue", "profit", "margin", "forecast", "guidance",
    "outlook", "results", "annual report", "quarter", "cloud revenue",
    "cloud growth", "free cash flow", "operating profit", "operating margin",
    "ai", "cloud", "software", "s/4hana",
]


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _csv_rows() -> list[dict]:
    path = PROJECT_ROOT / "data" / "dax_companies.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _ticker_mapping() -> dict[str, str]:
    path = PROJECT_ROOT / "data" / "yahoo_ticker_mapping.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {
            _norm(row.get("company_name", "")): row.get("yahoo_ticker", "")
            for row in csv.DictReader(f)
            if row.get("company_name") and row.get("yahoo_ticker")
        }


def _row_for_company(display_name: str) -> dict:
    rows = _csv_rows()
    ticker_map = _ticker_mapping()
    aliases = {
        "Deutsche Post (DHL)": ["DEUTSCHE POST", "DHL GROUP"],
        "Deutsche Boerse": ["DEUTSCHE BOERSE", "DEUTSCHE BÖRSE"],
        "Hannover Rueck": ["HANNOVER RUECK", "HANNOVER RÜCK"],
        "Mercedes-Benz": ["MERCEDES-BENZ GROUP"],
        "Munich Re": ["MUENCHENER RUECK", "MÜNCHENER RÜCK"],
        "Volkswagen": ["VOLKSWAGEN PREF", "VOLKSWAGEN"],
        "Henkel": ["HENKEL PREF", "HENKEL"],
        "GEA": ["GEA GRP", "GEA"],
        "Hochtief": ["HOCHTIEF"],
    }
    candidates = [display_name, *aliases.get(display_name, [])]
    for row in rows:
        if _norm(row.get("company_name", "")) in {_norm(c) for c in candidates}:
            out = dict(row)
            out["display_name"] = display_name
            out["ticker"] = (
                ticker_map.get(_norm(row.get("company_name", "")))
                or config.DAX40.get(display_name, "")
            )
            return out
    return {
        "company_name": display_name,
        "display_name": display_name,
        "sector": "",
        "ticker": ticker_map.get(_norm(display_name), config.DAX40.get(display_name, "")),
        "source": "config.py",
        "scraped_at": "",
    }


def _aliases_for_company(display_name: str, official_name: str) -> list[str]:
    lookup = {_norm(k): v for k, v in COMPANY_ALIASES.items()}
    aliases = lookup.get(_norm(display_name), [])
    if not aliases:
        aliases = lookup.get(_norm(official_name), [])
    merged = [official_name, display_name, *aliases]
    return [a for i, a in enumerate(merged) if a and a not in merged[:i]]


def _terms(*groups: str, limit: int = 5) -> str:
    terms = []
    for group in groups:
        terms.extend(AUDIT_RISK_QUERY_TERMS.get(group, []))
    return " ".join(dict.fromkeys(terms[:limit]))


def build_news_queries(company_row: dict, max_queries: int = 12) -> list[str]:
    """Generate capped German/English company + audit-risk queries."""
    display_name = company_row.get("display_name") or company_row.get("company_name", "")
    official_name = company_row.get("company_name", display_name)
    ticker = company_row.get("ticker", "")
    sector = company_row.get("sector", "")
    aliases = _aliases_for_company(display_name, official_name)
    primary = aliases[0] if aliases else display_name

    queries = [f'"{official_name}"']
    if ticker:
        queries.append(f'"{ticker}"')
    queries.extend(f'"{a}"' for a in aliases[1:5])
    queries.extend([
        f'"{primary}" {_terms("regulatory_legal", limit=5)}',
        f'"{primary}" {_terms("regulatory_legal", "provisions_contingent_liabilities", limit=5)}',
        f'"{primary}" {_terms("financial_liquidity", "earnings_forecast_impairment", limit=5)}',
        f'"{primary}" {_terms("operational_supply_chain", "restructuring_labor", limit=5)}',
        f'"{primary}" {_terms("cyber_it_data", "governance_fraud_accounting", limit=5)}',
    ])
    sector_terms = SECTOR_SPECIFIC_QUERY_TERMS.get(sector, [])
    if sector_terms:
        queries.append(f'"{primary}" {" ".join(sector_terms[:5])}')
        queries.append(f'"{primary}" {" ".join(sector_terms[5:10])}')

    deduped = []
    for query in queries:
        if query not in deduped:
            deduped.append(query)
    return deduped[:max_queries]


def _or_query(values: list[str]) -> str:
    return " OR ".join(f'"{value}"' for value in values if value)


def _compact_gdelt_queries(company_row: dict) -> list[str]:
    display_name = company_row.get("display_name") or company_row.get("company_name", "")
    official_name = company_row.get("company_name", display_name)
    aliases = _aliases_for_company(display_name, official_name)[:4]
    anchors = [official_name, company_row.get("ticker", ""), *aliases]
    anchors = list(dict.fromkeys([a for a in anchors if a]))

    risk_terms = [
        "lawsuit", "litigation", "fine", "investigation",
        "Klage", "Rechtsstreit", "Bußgeld", "Ermittlung",
        "liquidity", "debt", "capital increase", "cash flow",
        "Liquidität", "Schulden", "Kapitalerhöhung", "Cashflow",
        "profit warning", "loss", "earnings decline", "impairment",
        "Gewinnwarnung", "Verlust", "Umsatzrückgang", "Wertminderung",
        "supply chain", "delivery delay", "production halt", "plant closure",
        "Lieferkette", "Lieferverzug", "Produktionsstopp", "Werksschließung",
        "restructuring", "job cuts", "layoffs", "cost cutting",
        "Restrukturierung", "Stellenabbau", "Sparprogramm", "Streik",
    ]
    risk_terms.extend(SECTOR_SPECIFIC_QUERY_TERMS.get(company_row.get("sector", ""), [])[:8])
    risk_terms = list(dict.fromkeys(risk_terms[:36]))

    if not anchors:
        return []
    return [f"({_or_query(anchors)}) ({_or_query(risk_terms)})"]


def _gdelt_anchor(company_row: dict) -> str:
    display_name = company_row.get("display_name") or company_row.get("company_name", "")
    official_name = company_row.get("company_name", display_name)
    aliases = _aliases_for_company(display_name, official_name)
    preferred_markers = (" AG", " SE", " GROUP", " KGAA", " N.V.", " HOLDING")
    for alias in aliases:
        if any(marker in alias.upper() for marker in preferred_markers):
            return alias
    return official_name or display_name


def _compact_gdelt_queries(company_row: dict) -> list[str]:
    """Use one narrow monthly GDELT query to avoid timeouts on full-year runs."""
    anchor = _gdelt_anchor(company_row)
    if not anchor:
        return []

    risk_terms = [
        "lawsuit", "litigation", "fine", "investigation",
        "Klage", "Rechtsstreit", "Ermittlung",
        "profit warning", "earnings decline", "impairment",
        "Gewinnwarnung", "Verlust", "Wertminderung",
        "restructuring", "job cuts", "cost cutting",
        "Restrukturierung", "Stellenabbau", "Sparprogramm",
    ]
    risk_terms.extend(SECTOR_SPECIFIC_QUERY_TERMS.get(company_row.get("sector", ""), [])[:4])
    risk_terms = list(dict.fromkeys(risk_terms[:20]))
    return [
        f'"{anchor}"',
        f'"{anchor}" ({_or_query(risk_terms)})',
    ]


def _monthly_windows(start_date, end_date) -> list[tuple[dt.date, dt.date]]:
    """Return configured monthly windows overlapping [start_date, end_date]."""
    if not start_date:
        start_date = dt.date.fromisoformat(DATE_WINDOWS[0][0])
    if not end_date:
        end_date = dt.date.today()
    # UI end date is inclusive; query windows use exclusive end.
    requested_start = start_date
    requested_end_exclusive = end_date + dt.timedelta(days=1)
    windows = []
    for start_s, end_s in DATE_WINDOWS:
        start = dt.date.fromisoformat(start_s)
        end = dt.date.fromisoformat(end_s)
        if start < requested_end_exclusive and end > requested_start:
            windows.append((max(start, requested_start), min(end, requested_end_exclusive)))
    return windows or [(requested_start, requested_end_exclusive)]


def _quarter_sample_windows(windows: list[tuple[dt.date, dt.date]]) -> list[tuple[dt.date, dt.date]]:
    selected = []
    seen_quarters = set()
    for start, end in windows:
        quarter = (start.year, (start.month - 1) // 3 + 1)
        if quarter in seen_quarters:
            continue
        seen_quarters.add(quarter)
        selected.append((start, end))
    return selected or windows


def _language_allowed(lang: str, title: str) -> tuple[bool, str]:
    lang = (lang or "").strip().lower()
    if lang in ("german", "deu", "ger", "de"):
        return True, "de"
    if lang in ("english", "eng", "en", "") and _is_probably_english(title):
        return True, "en"
    return False, lang or "unknown"


def _dedupe_key(item: dict) -> tuple[str, str, str, str]:
    url = re.sub(r"[?#].*$", "", (item.get("source_url") or "").strip().lower())
    headline = re.sub(r"\s+", " ", (item.get("headline") or "").strip().lower())
    published = (item.get("published") or "")[:10]
    return (item.get("company", ""), url or headline, headline, published)


def _month_key(item: dict) -> str:
    published = item.get("published", "")
    if len(published) >= 6 and published[:6].isdigit():
        return f"{published[:4]}-{published[4:6]}"
    if len(published) >= 7:
        try:
            parsed = parsedate_to_datetime(published)
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except Exception:  # noqa: BLE001
            return published[:7]
    return "unknown"


def _is_low_value_article(item: dict) -> bool:
    headline = (item.get("headline") or "").lower()
    source = (item.get("source") or "").lower()
    if source in LOW_VALUE_NEWS_DOMAINS:
        return True
    return any(term in headline for term in LOW_VALUE_HEADLINE_TERMS)


def _relevance_score(item: dict) -> int:
    headline = (item.get("headline") or "").lower()
    source = (item.get("source") or "").lower()
    score = 0
    score += 5 * sum(1 for term in HIGH_VALUE_AUDIT_TERMS if term in headline)
    score += 2 * sum(1 for term in BUSINESS_RELEVANCE_TERMS if term in headline)
    if source in {"reuters.com", "bloomberg.com", "ft.com", "handelsblatt.com"}:
        score += 2
    if _is_low_value_article(item):
        score -= 20
    return score


def _rank_for_dashboard(items: list[dict]) -> list[dict]:
    useful = [item for item in items if not _is_low_value_article(item)]
    ranked = useful if useful else items
    return sorted(
        ranked,
        key=lambda item: (_relevance_score(item), item.get("published", "")),
        reverse=True,
    )


def _balanced_by_month(items: list[dict], limit: int) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        buckets.setdefault(_month_key(item), []).append(item)

    selected = []
    month_keys = sorted(buckets)
    while len(selected) < limit and any(buckets.values()):
        for key in month_keys:
            if buckets[key]:
                selected.append(buckets[key].pop(0))
                if len(selected) >= limit:
                    break
    return selected


def _new_debug(company_row: dict, queries: list[str], windows: list[tuple[dt.date, dt.date]]) -> dict:
    return {
        "selected_company": company_row.get("display_name", company_row.get("company_name", "")),
        "ticker": company_row.get("ticker", ""),
        "sector": company_row.get("sector", ""),
        "generated_queries": queries,
        "date_windows": [(s.isoformat(), e.isoformat()) for s, e in windows],
        "raw_articles_fetched": 0,
        "removed_as_duplicates": 0,
        "removed_by_language_filter": 0,
        "sent_to_nlp_scoring": 0,
        "saved_to_sqlite": 0,
        "skipped_already_cached": 0,
        "nlp_model_error_skipped": 0,
        "nlp_exception_skipped": 0,
        "incoming_from_poll": 0,
        "incoming_headline_sample": [],
    }


_LAST_NEWS_DEBUG: dict = {}


def get_last_news_debug() -> dict:
    """Expose the most recent ingestion diagnostics to Streamlit."""
    return dict(_LAST_NEWS_DEBUG)


def debug_gdelt_raw(company: str, start_date, end_date, max_windows: int = 2) -> dict:
    """Fetch a small raw GDELT sample before normal filtering/scoring."""
    company_row = _row_for_company(company)
    windows = _monthly_windows(start_date, end_date)[:max_windows]
    anchor = _gdelt_anchor(company_row)
    queries = [
        f'"{anchor}"',
        *_compact_gdelt_queries(company_row),
    ]
    queries = [q for i, q in enumerate(queries) if q and q not in queries[:i]]

    runs = []
    totals = {
        "raw_articles": 0,
        "language_kept": 0,
        "language_removed": 0,
    }
    for start, end in windows:
        start_str = f"{start.strftime('%Y%m%d')}000000"
        end_str = f"{(end - dt.timedelta(days=1)).strftime('%Y%m%d')}235959"
        for query in queries:
            articles = _cached_gdelt_fetch(query, start_str, end_str, 10)
            kept = 0
            removed = 0
            sample = []
            for article in articles[:10]:
                title = article.get("title") or ""
                allowed, detected_lang = _language_allowed(article.get("language", ""), title)
                if allowed:
                    kept += 1
                else:
                    removed += 1
                sample.append({
                    "title": title,
                    "language": article.get("language", ""),
                    "detected_language": detected_lang,
                    "kept_by_language_filter": allowed,
                    "date": article.get("seendate", ""),
                    "source": article.get("domain", "GDELT"),
                    "url": article.get("url", ""),
                })

            totals["raw_articles"] += len(articles)
            totals["language_kept"] += kept
            totals["language_removed"] += removed
            runs.append({
                "query": query,
                "window": f"{start.isoformat()} to {end.isoformat()}",
                "raw_articles": len(articles),
                "language_kept_in_sample": kept,
                "language_removed_in_sample": removed,
                "sample": sample,
            })

    return {
        "company": company,
        "official_company": company_row.get("company_name", ""),
        "ticker": company_row.get("ticker", ""),
        "sector": company_row.get("sector", ""),
        "windows_tested": [(s.isoformat(), e.isoformat()) for s, e in windows],
        "queries_tested": queries,
        "totals": totals,
        "runs": runs,
    }


# Cache results for 1 hour so repeated clicks for the same query don't burn the
# NewsAPI free-tier daily quota.
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_newsapi_fetch(
    query: str,
    from_str: str | None,
    to_str: str | None,
    page_size: int,
    language: str,
):
    """Call NewsAPI /everything and return the raw article list (cached)."""
    import requests

    params = {
        "q": query,
        # Match the company in the HEADLINE only. NewsAPI's default full-text
        # search floods results with articles that merely mention the word in
        # the body, which the company tag below would then discard.
        "searchIn": "title,description",
        "language": language,
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": config.NEWSAPI_KEY,
    }
    if from_str:
        params["from"] = from_str
    if to_str:
        params["to"] = to_str

    r = None
    try:
        r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("articles", [])
    except requests.exceptions.HTTPError:
        # NewsAPI returns a JSON error body (quota exceeded, invalid key, etc.).
        try:
            msg = r.json().get("message", r.text)
        except Exception:  # noqa: BLE001
            msg = r.text if r is not None else "unknown error"
        st.error(f"NewsAPI error: {msg}")
        return []
    except Exception as e:  # noqa: BLE001
        st.error(f"NewsAPI request failed: {e}")
        return []


def _newsapi_news(
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
    page_size: int = 10,
):
    """Fetch and normalise NewsAPI headlines for the selected company."""
    if not config.NEWSAPI_KEY:
        st.error("NEWSAPI_KEY is not set — add it to your .env file to fetch news.")
        return []

    selected = list(companies) if companies else ["Siemens", "Volkswagen", "SAP"]
    query = " OR ".join(f'"{c}"' for c in selected)

    # NewsAPI's free tier only serves the last 30 days. Clamp the start date and
    # tell the user instead of silently returning nothing.
    today = dt.date.today()
    earliest = today - dt.timedelta(days=30)
    from_str = to_str = None
    if start_date:
        if start_date < earliest:
            st.info(
                f"NewsAPI free tier only covers the last 30 days — showing news "
                f"from {earliest} instead of {start_date}."
            )
        from_str = max(start_date, earliest).isoformat()
    if end_date:
        to_str = end_date.isoformat()

    # Fetch a few extra so the English/company filters still leave a useful list.
    articles = _cached_newsapi_fetch(query, from_str, to_str, max(page_size, 12), "en")

    results = []
    for a in articles:
        title = a.get("title") or ""
        if not _is_probably_english(title):
            continue

        company = next(
            (name for name in config.DAX40 if name.split()[0].lower() in title.lower()),
            "",
        )
        if selected and company not in selected:
            company = selected[0] if len(selected) == 1 else "DAX 40"

        results.append({
            "company": company,
            "headline": title,
            "published": a.get("publishedAt", ""),
            "source": (a.get("source") or {}).get("name", "NewsAPI"),
            "source_url": a.get("url", ""),
        })
    return results


def _newsapi_news_expanded(
    company_row: dict,
    queries: list[str],
    windows: list[tuple[dt.date, dt.date]],
    debug: dict,
    page_size: int = 10,
):
    """Fetch and normalise recent NewsAPI headlines for expanded company queries."""
    if not config.NEWSAPI_KEY:
        st.error("NEWSAPI_KEY is not set - add it to your .env file to fetch news.")
        return []

    today = dt.date.today()
    earliest = today - dt.timedelta(days=30)
    results = []
    display_name = company_row.get("display_name") or company_row.get("company_name", "")

    for start, end in windows:
        if end <= earliest:
            continue
        from_str = max(start, earliest).isoformat()
        to_str = min(end, today + dt.timedelta(days=1)).isoformat()
        for query in queries:
            for language in ("en", "de"):
                articles = _cached_newsapi_fetch(
                    query, from_str, to_str, max(page_size, 10), language
                )
                debug["raw_articles_fetched"] += len(articles)
                for article in articles:
                    title = article.get("title") or ""
                    allowed, detected_lang = _language_allowed(language, title)
                    if not allowed:
                        debug["removed_by_language_filter"] += 1
                        continue
                    results.append({
                        "company": display_name,
                        "headline": title,
                        "original_headline": title,
                        "original_language": detected_lang,
                        "published": article.get("publishedAt", ""),
                        "source": (article.get("source") or {}).get("name", "NewsAPI"),
                        "source_url": article.get("url", ""),
                        "ticker": company_row.get("ticker", ""),
                        "sector": company_row.get("sector", ""),
                        "query": query,
                    })
    return results


def _gdelt_news_expanded(
    company_row: dict,
    queries: list[str],
    windows: list[tuple[dt.date, dt.date]],
    debug: dict,
    page_size: int = 10,
):
    """Normalise GDELT results into the same dict shape as NewsAPI."""
    results = []
    display_name = company_row.get("display_name") or company_row.get("company_name", "")

    for start, end in windows:
        start_str = f"{start.strftime('%Y%m%d')}000000"
        end_str = f"{(end - dt.timedelta(days=1)).strftime('%Y%m%d')}235959"
        for query in queries:
            articles = _cached_gdelt_fetch(query, start_str, end_str, min(page_size, 5))
            debug["raw_articles_fetched"] += len(articles)
            for article in articles:
                title = article.get("title") or ""
                allowed, detected_lang = _language_allowed(article.get("language", ""), title)
                if not allowed:
                    debug["removed_by_language_filter"] += 1
                    continue
                results.append({
                    "company": display_name,
                    "headline": title,
                    "original_headline": title,
                    "original_language": detected_lang,
                    "published": article.get("seendate", ""),
                    "source": article.get("domain", "GDELT"),
                    "source_url": article.get("url", ""),
                    "ticker": company_row.get("ticker", ""),
                    "sector": company_row.get("sector", ""),
                    "query": query,
                })
    return results


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_google_news_fetch(query: str, language: str, page_size: int):
    """Fetch Google News RSS search results for a query."""
    import requests
    from urllib.parse import quote_plus

    if language == "de":
        params = "hl=de&gl=DE&ceid=DE:de"
    else:
        params = "hl=en&gl=US&ceid=US:en"
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&{params}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as e:  # noqa: BLE001
        st.warning(f"Google News RSS fetch failed: {e}")
        return []

    articles = []
    for item in root.findall(".//item")[:page_size]:
        articles.append({
            "title": item.findtext("title") or "",
            "published": item.findtext("pubDate") or "",
            "source": item.findtext("source") or "Google News",
            "url": item.findtext("link") or "",
        })
    return articles


def _google_news_history(
    company_row: dict,
    windows: list[tuple[dt.date, dt.date]],
    debug: dict,
    page_size: int = 12,
):
    """Use Google News RSS for the normal dashboard history sample."""
    display_name = company_row.get("display_name") or company_row.get("company_name", "")
    anchor = _gdelt_anchor(company_row)
    if not anchor:
        return []

    results = []
    terms_by_language = {
        "en": "earnings OR revenue OR profit OR forecast OR restructuring OR lawsuit OR investigation",
        "de": "Gewinn OR Umsatz OR Prognose OR Restrukturierung OR Klage OR Ermittlung",
    }
    per_query = max(3, page_size // max(1, len(windows)))
    for start, end in windows:
        for language, terms in terms_by_language.items():
            query = f'"{anchor}" ({terms}) after:{start.isoformat()} before:{end.isoformat()}'
            articles = _cached_google_news_fetch(query, language, per_query)
            debug["raw_articles_fetched"] += len(articles)
            for article in articles:
                title = article.get("title") or ""
                allowed, detected_lang = _language_allowed(language, title)
                if not allowed:
                    debug["removed_by_language_filter"] += 1
                    continue
                results.append({
                    "company": display_name,
                    "headline": title,
                    "original_headline": title,
                    "original_language": detected_lang,
                    "published": article.get("published", ""),
                    "source": article.get("source", "Google News"),
                    "source_url": article.get("url", ""),
                    "ticker": company_row.get("ticker", ""),
                    "sector": company_row.get("sector", ""),
                    "query": query,
                })
    return results


# =============================================================================
# 2b. DEEP-HISTORY FALLBACK (GDELT — covers dates older than NewsAPI's 30 days)
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def _cached_gdelt_fetch(query: str, start_str: str | None, end_str: str | None, page_size: int):
    """Call GDELT DOC 2.0 ArtList. GDELT throttles to 1 request / 5 seconds, so
    we back off (>=6s) on HTTP 429 and tolerate its non-JSON error bodies."""
    import requests

    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords": page_size}
    if start_str:
        params["startdatetime"] = start_str
        if end_str:
            params["enddatetime"] = end_str
    else:
        params["timespan"] = "1month"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for attempt in range(2):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=8)
            if r.status_code == 429:  # GDELT requires >=5s spacing
                time.sleep(3 + attempt * 2)
                continue
            r.raise_for_status()
            text = r.text.strip()
            if not text or text[0] not in "[{":  # empty / plain-text notice, not JSON
                if attempt < 1:
                    time.sleep(3)
                    continue
                return []
            return r.json().get("articles", [])
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                st.warning(f"GDELT history fetch failed: {e}")
                return []
    return []


def _gdelt_news(companies=None, start_date=None, end_date=None, page_size: int = 10):
    """Normalise GDELT results into the same dict shape as NewsAPI (English only)."""
    selected = list(companies) if companies else ["Siemens", "Volkswagen", "SAP"]
    query = " OR ".join(f'"{c}"' for c in selected)
    start_str = f"{start_date.strftime('%Y%m%d')}000000" if start_date else None
    end_str = f"{end_date.strftime('%Y%m%d')}235959" if end_date else None

    articles = _cached_gdelt_fetch(query, start_str, end_str, max(page_size, 12))

    results = []
    for a in articles:
        title = a.get("title") or ""
        lang = (a.get("language") or "").strip().lower()
        if lang and lang not in ("english", "eng", "en"):
            continue
        if not _is_probably_english(title):
            continue
        company = next(
            (name for name in config.DAX40 if name.split()[0].lower() in title.lower()), "",
        )
        if selected and company not in selected:
            company = selected[0] if len(selected) == 1 else "DAX 40"
        results.append({
            "company": company,
            "headline": title,
            "published": a.get("seendate", ""),
            "source": a.get("domain", "GDELT"),
            "source_url": a.get("url", ""),
        })
    return results


# =============================================================================
# 2c. ENTRY POINT — hybrid NewsAPI (recent) + GDELT (history)
# =============================================================================
def poll_news(
    n: int = 5,
    companies: Iterable[str] | None = None,
    start_date=None,
    end_date=None,
):
    """Single entry point for the UI.

    NewsAPI serves the last 30 days (clean, reliable); GDELT covers anything
    older (NewsAPI's free tier can't reach it). The two are merged and
    de-duplicated so the requested window is fully covered.
    """
    global _LAST_NEWS_DEBUG

    selected = list(companies) if companies else ["SAP"]
    company_row = _row_for_company(selected[0])
    queries = build_news_queries(company_row, max_queries=12)
    gdelt_queries = _compact_gdelt_queries(company_row)
    windows = _monthly_windows(start_date, end_date)
    gdelt_windows = _quarter_sample_windows(windows)
    gdelt_queries_for_fetch = gdelt_queries[:1]
    debug = _new_debug(company_row, queries, gdelt_windows)
    debug["selected_period_windows"] = [(s.isoformat(), e.isoformat()) for s, e in windows]
    debug["gdelt_queries"] = []
    debug["normal_history_source"] = "Google News RSS"

    combined = []
    combined += _newsapi_news_expanded(company_row, queries, windows, debug, page_size=n)
    combined += _google_news_history(company_row, gdelt_windows, debug, page_size=n)

    # De-duplicate after fetching across aliases, queries, and monthly windows.
    seen, deduped = set(), []
    for item in combined:
        key = _dedupe_key(item)
        if key in seen:
            debug["removed_as_duplicates"] += 1
            continue
        seen.add(key)
        deduped.append(item)
    debug["deduped_before_limit"] = len(deduped)
    ranked = _rank_for_dashboard(deduped)
    debug["removed_low_value"] = max(0, len(deduped) - len(ranked))
    deduped = _balanced_by_month(ranked, n)
    deduped = _rank_for_dashboard(deduped)
    debug["sent_to_nlp_scoring"] = len(deduped)
    debug["incoming_from_poll"] = len(deduped)
    debug["incoming_headline_sample"] = [
        {
            "headline": item.get("headline", ""),
            "language": item.get("original_language", ""),
            "source": item.get("source", ""),
            "published": item.get("published", ""),
            "query": item.get("query", ""),
        }
        for item in deduped[:10]
    ]
    _LAST_NEWS_DEBUG = debug
    return deduped
