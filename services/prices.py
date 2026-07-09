"""Stock price fetching via yfinance.

We deliberately pull daily OHLC rather than intraday: the app's unit of
work is a quarter, and daily bars are enough for a price-in-context chart
next to the news feed.

If Yahoo returns nothing (delisted ticker, transient failure, ...), we
return an empty DataFrame — the caller renders a placeholder rather than
crashing.
"""

from __future__ import annotations

from datetime import date, timedelta
import pandas as pd
import yfinance as yf

from services.news import Quarter


def fetch_prices(ticker: str, quarter: Quarter) -> pd.DataFrame:
    """Daily OHLC for the quarter. Returns an empty DataFrame on failure.

    Columns: Open, High, Low, Close, Volume — with a DatetimeIndex (UTC-naive,
    matching yfinance's default).
    """
    try:
        df = yf.download(
            ticker,
            start=quarter.start.date().isoformat(),
            end=quarter.end.date().isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance sometimes returns a MultiIndex on columns when called with a
    # single ticker — flatten it so downstream code can just do df["Close"].
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def fetch_prices_range(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Daily OHLC for a user-selected date range.

    `end` is inclusive for the app UI; yfinance treats it as exclusive, so the
    request adds one day.
    """
    if end < start:
        return pd.DataFrame()
    try:
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def summarize(df: pd.DataFrame) -> dict:
    """A few headline numbers for the KPI row above the chart.

    Returns an empty dict when the DataFrame is empty so the caller can
    branch cleanly.
    """
    if df.empty or "Close" not in df.columns:
        return {}

    close = df["Close"].dropna()
    if close.empty:
        return {}

    first, last = float(close.iloc[0]), float(close.iloc[-1])
    ret_pct = (last / first - 1.0) * 100.0 if first else 0.0
    return {
        "last_close": last,
        "period_return_pct": ret_pct,
        "period_high": float(df["High"].max()),
        "period_low": float(df["Low"].min()),
        "avg_volume": float(df["Volume"].mean()) if "Volume" in df.columns else 0.0,
        "trading_days": int(len(close)),
    }
