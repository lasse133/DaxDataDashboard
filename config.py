"""
config.py
---------
Central configuration for the DAX 40 Audit Risk Dashboard.

Everything that is "data about the world" (which companies, which tickers,
which words signal risk) lives here so the rest of the code stays generic.
"""

# --- DAX 40 constituents: display name -> Yahoo Finance ticker ----------------
# Yahoo uses the ".DE" suffix for Frankfurt-listed shares.
# (List is the DAX 40 as of 2025/2026; adjust if the index reshuffles.)
DAX40 = {
    "Adidas": "ADS.DE",
    "Airbus": "AIR.DE",
    "Allianz": "ALV.DE",
    "BASF": "BAS.DE",
    "Bayer": "BAYN.DE",
    "Beiersdorf": "BEI.DE",
    "BMW": "BMW.DE",
    "Brenntag": "BNR.DE",
    "Commerzbank": "CBK.DE",
    "Continental": "CON.DE",
    "Daimler Truck": "DTG.DE",
    "Deutsche Bank": "DBK.DE",
    "Deutsche Boerse": "DB1.DE",
    "Deutsche Post (DHL)": "DHL.DE",
    "Deutsche Telekom": "DTE.DE",
    "E.ON": "EOAN.DE",
    "Fresenius": "FRE.DE",
    "Hannover Rueck": "HNR1.DE",
    "Heidelberg Materials": "HEI.DE",
    "Henkel": "HEN3.DE",
    "Infineon": "IFX.DE",
    "Mercedes-Benz": "MBG.DE",
    "Merck": "MRK.DE",
    "MTU Aero Engines": "MTX.DE",
    "Munich Re": "MUV2.DE",
    "Porsche AG": "P911.DE",
    "Porsche SE": "PAH3.DE",
    "Qiagen": "QIA.DE",
    "Rheinmetall": "RHM.DE",
    "RWE": "RWE.DE",
    "SAP": "SAP.DE",
    "Sartorius": "SRT3.DE",
    "Siemens": "SIE.DE",
    "Siemens Energy": "ENR.DE",
    "Siemens Healthineers": "SHL.DE",
    "Symrise": "SY1.DE",
    "Volkswagen": "VOW3.DE",
    "Vonovia": "VNA.DE",
    "Zalando": "ZAL.DE",
}

# Reverse lookup so we can map a ticker back to a readable name.
TICKER_TO_NAME = {v: k for k, v in DAX40.items()}

# --- Risk driver lexicon ------------------------------------------------------
# Maps an ISA-315-style risk category -> trigger keywords found in headlines.
# FinBERT tells us *sentiment*; this tells us *what kind of risk* it is.
RISK_DRIVERS = {
    "Supply chain": ["supply chain", "shortage", "delay", "logistics", "bottleneck", "disruption"],
    "Financial / liquidity": ["debt", "default", "downgrade", "liquidity", "writedown", "impairment", "loss", "profit warning"],
    "Regulatory / legal": ["lawsuit", "fine", "probe", "investigation", "regulation", "antitrust", "sanction", "recall"],
    "Operational": ["strike", "outage", "plant", "production halt", "accident", "cyberattack", "data breach"],
    "Market / demand": ["demand", "guidance cut", "slump", "weak sales", "competition", "price war"],
    "Governance / fraud": ["fraud", "accounting", "misstatement", "resign", "ceo steps down", "whistleblower"],
    "ESG / climate": ["emissions", "pollution", "climate", "esg", "environmental"],
}

# --- Streaming / refresh settings --------------------------------------------
REFRESH_SECONDS = 3600        # dashboard refresh interval in seconds (1 hour)
PRICE_START_DATE = "2026-01-01"  # first date shown in the stock price chart
PRICE_LOOKBACK = "ytd"        # fallback yfinance period when no start date is set
PRICE_INTERVAL = "1d"         # yfinance candle interval

# --- News source toggle -------------------------------------------------------
# Leave NEWSAPI_KEY = None to run on the built-in mock stream (zero setup).
# Get a free key at https://newsapi.org and paste it here (or set env NEWSAPI_KEY)
# to switch to real, live headlines.
import os
from pathlib import Path

# Load .env file if present (it is gitignored — safe to store secrets there)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", None)

# Sentiment label that should trigger an auditor warning.
RISK_LABEL = "negative"
WARNING_THRESHOLD = 0.60      # min FinBERT confidence to raise a flag
