"""
database.py
-----------
SQLite persistence layer for the DAX 40 Audit Risk Radar.
"""

import sqlite3
import json
from pathlib import Path

# Create a 'data' directory in your project folder if it doesn't exist
DB_PATH = Path(__file__).resolve().parent / "data" / "audit_radar.db"

def get_connection():
    """Establish a connection to the local SQLite file."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is required for Streamlit's multi-threaded environment
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    """Create the table schema if it doesn't already exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS headlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT,
                headline TEXT,
                original_headline TEXT,
                original_language TEXT,
                published TEXT,
                source TEXT,
                source_url TEXT,
                ticker TEXT,
                sector TEXT,
                query TEXT,
                sentiment TEXT,
                confidence REAL,
                risk_score REAL,
                risk_drivers TEXT,
                is_warning BOOLEAN,
                audit_risk_category TEXT,
                financial_statement_level_risk TEXT,
                affected_accounts TEXT,
                affected_assertions TEXT,
                affected_departments TEXT,
                legal_reference TEXT,
                audit_standard_reference TEXT,
                legal_reference_explanation TEXT,
                audit_standard_explanation TEXT,
                reference_responsibility TEXT,
                suggested_audit_response TEXT,
                UNIQUE(company, headline) 
            )
        """)
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(headlines)").fetchall()
        }
        for column, column_type in {
            "original_headline": "TEXT",
            "original_language": "TEXT",
            "ticker": "TEXT",
            "sector": "TEXT",
            "query": "TEXT",
        }.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE headlines ADD COLUMN {column} {column_type}")
        # The UNIQUE constraint ensures we never save duplicate headlines

def headline_exists(company: str, headline: str) -> bool:
    """Check if a headline has already been scored to save AI compute power."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM headlines WHERE company = ? AND headline = ?", 
            (company, headline)
        )
        return cursor.fetchone() is not None

def save_headline(item: dict):
    """Insert a fully scored NLP record into the database."""
    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO headlines (
                company, headline, original_headline, original_language,
                published, source, source_url, ticker, sector, query,
                sentiment, confidence, risk_score, risk_drivers, is_warning,
                audit_risk_category, financial_statement_level_risk, affected_accounts,
                affected_assertions, affected_departments, legal_reference,
                audit_standard_reference, legal_reference_explanation,
                audit_standard_explanation, reference_responsibility, suggested_audit_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.get("company"), item.get("headline"), item.get("original_headline"),
            item.get("original_language"), item.get("published"),
            item.get("source"), item.get("source_url"), item.get("ticker"),
            item.get("sector"), item.get("query"), item.get("sentiment"),
            item.get("confidence"), item.get("risk_score"),
            json.dumps(item.get("risk_drivers", [])),  # Convert Python list to JSON string for SQL
            item.get("is_warning"), item.get("audit_risk_category"),
            item.get("financial_statement_level_risk"), item.get("affected_accounts"),
            item.get("affected_assertions"), item.get("affected_departments"),
            item.get("legal_reference"), item.get("audit_standard_reference"),
            item.get("legal_reference_explanation"), item.get("audit_standard_explanation"),
            item.get("reference_responsibility"), item.get("suggested_audit_response")
        ))

def clear_headlines(companies: list[str] | None = None) -> int:
    """Delete scored headlines from the cache. If `companies` is given, only those
    are removed; otherwise the whole table is wiped. Returns rows deleted."""
    with get_connection() as conn:
        if companies:
            placeholders = ",".join("?" * len(companies))
            cursor = conn.execute(
                f"DELETE FROM headlines WHERE company IN ({placeholders})",
                tuple(companies),
            )
        else:
            cursor = conn.execute("DELETE FROM headlines")
        return cursor.rowcount


def get_recent_headlines(companies: list[str], limit: int = 50) -> list[dict]:
    """Retrieve the most recent scored headlines from the database for the UI."""
    if not companies:
        return []
    
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries instead of tuples
        placeholders = ",".join("?" * len(companies))
        
        query = f"""
            SELECT * FROM headlines 
            WHERE company IN ({placeholders}) 
            ORDER BY id DESC LIMIT ?
        """
        
        cursor = conn.execute(query, (*companies, limit))
        rows = cursor.fetchall()

        # Unpack the rows back into native Python dictionaries for Streamlit
        results = []
        for row in rows:
            item = dict(row)
            item["risk_drivers"] = json.loads(item["risk_drivers"])  # Convert JSON string back to list
            item["is_warning"] = bool(item["is_warning"])
            results.append(item)
            
        return results
