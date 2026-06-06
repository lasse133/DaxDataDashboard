"""
Rule-based audit and legal reference mapping for risk signals.

These mappings do not claim that a company violated a law. They explain why an
external signal may be relevant for audit planning, financial reporting, risk
reporting, or auditor reporting.
"""

from __future__ import annotations


DEFAULT_REFERENCE = {
    "audit_risk_category": "General business context signal",
    "financial_statement_level_risk": "No",
    "affected_accounts": "No specific account identified",
    "affected_assertions": "No specific assertion identified",
    "affected_departments": "Finance, Investor Relations",
    "legal_reference": "",
    "audit_standard_reference": "",
    "legal_reference_explanation": (
        "No specific legal reference is assigned because the signal is not a "
        "negative audit risk warning and no account-specific topic was matched."
    ),
    "audit_standard_explanation": (
        "No specific audit standard reference is assigned for this signal."
    ),
    "reference_responsibility": "Business monitoring",
    "suggested_audit_response": (
        "No further investigation is necessary based on this signal alone."
    ),
}


REFERENCE_MAPPINGS = {
    "going_concern": {
        "keywords": [
            "bankruptcy",
            "covenant",
            "credit downgrade",
            "default",
            "downgrade",
            "financing",
            "going concern",
            "insolvency",
            "liquidity",
            "loss",
            "profit warning",
            "severe losses",
        ],
        "risk_types": ["stock_price_drop", "volume_spike"],
        "risk_drivers": ["Financial / liquidity", "Market / demand"],
        "audit_risk_category": "Going concern / bestandsgefaehrdende Risiken",
        "financial_statement_level_risk": "Yes",
        "affected_accounts": "Cash, borrowings, impairment, provisions, disclosures",
        "affected_assertions": "Valuation, completeness, presentation/disclosure",
        "affected_departments": "Finance, Treasury, Risk Management",
        "legal_reference": "Sec. 91(2) AktG; Sec. 317(4) HGB; Sec. 322 HGB",
        "audit_standard_reference": "IDW PS 340 n.F.; ISA 315 / IDW PS 261",
        "legal_reference_explanation": (
            "Developments that may threaten continued existence are relevant to "
            "management's early-warning responsibilities and auditor reporting."
        ),
        "audit_standard_explanation": (
            "The signal may indicate a financial-statement-level risk requiring "
            "audit attention to going concern, liquidity, valuation, and disclosures."
        ),
        "reference_responsibility": "Management early warning, auditor reporting, audit response",
        "suggested_audit_response": (
            "Review liquidity plans, financing agreements, covenant compliance, "
            "management forecasts, impairment indicators, and going-concern disclosures."
        ),
    },
    "risk_early_warning": {
        "keywords": [
            "cyberattack",
            "data breach",
            "disruption",
            "emissions",
            "outage",
            "production halt",
            "supply chain",
        ],
        "risk_types": ["negative_news_keyword", "google_search_keyword"],
        "risk_drivers": ["Supply chain", "Operational", "ESG / climate"],
        "audit_risk_category": "Risk early-warning system",
        "financial_statement_level_risk": "Possible",
        "affected_accounts": "Inventory, revenue, provisions, impairment, disclosures",
        "affected_assertions": "Completeness, valuation, cut-off, presentation/disclosure",
        "affected_departments": "Operations, IT, Risk Management, Finance",
        "legal_reference": "Sec. 91(2) AktG; Sec. 317(4) HGB",
        "audit_standard_reference": "IDW PS 340 n.F.",
        "legal_reference_explanation": (
            "The signal may be relevant to management's duty to identify, monitor, "
            "aggregate, and respond to significant risks."
        ),
        "audit_standard_explanation": (
            "For listed companies, the auditor may need to consider whether the "
            "risk early-warning system can identify and monitor such risks."
        ),
        "reference_responsibility": "Management early warning, auditor assessment",
        "suggested_audit_response": (
            "Inspect internal risk reports, incident logs, mitigation plans, and "
            "management's aggregation of operational or ESG risks."
        ),
    },
    "legal_compliance": {
        "keywords": [
            "antitrust",
            "fine",
            "fraud",
            "investigation",
            "lawsuit",
            "probe",
            "recall",
            "regulation",
            "sanction",
            "whistleblower",
        ],
        "risk_types": ["negative_news_keyword", "google_search_keyword"],
        "risk_drivers": ["Regulatory / legal", "Governance / fraud"],
        "audit_risk_category": "Legal and compliance risk",
        "financial_statement_level_risk": "Possible",
        "affected_accounts": "Provisions, contingent liabilities, legal expenses, disclosures",
        "affected_assertions": "Completeness, valuation, presentation/disclosure",
        "affected_departments": "Legal, Compliance, Finance",
        "legal_reference": "Sec. 289 HGB / Sec. 315 HGB; Sec. 321 HGB",
        "audit_standard_reference": "ISA 315 / IDW PS 261; EU Audit Regulation Article 10",
        "legal_reference_explanation": (
            "Litigation or compliance signals may need to be reflected in risk "
            "reporting and may become relevant for auditor reporting."
        ),
        "audit_standard_explanation": (
            "The signal may create assertion-level risks for provisions, contingent "
            "liabilities, expenses, and note disclosures."
        ),
        "reference_responsibility": "Financial reporting, risk reporting, auditor reporting",
        "suggested_audit_response": (
            "Interview Legal and Compliance, inspect litigation registers, review "
            "lawyer confirmations, and assess provisions and disclosures."
        ),
    },
    "performance_distribution": {
        "keywords": [
            "dividend",
            "earnings",
            "profit",
            "raises full-year guidance",
            "revenue growth",
            "sales",
        ],
        "risk_types": [],
        "risk_drivers": [],
        "audit_risk_category": "Performance and distribution signal",
        "financial_statement_level_risk": "No",
        "affected_accounts": "Revenue, net income, retained earnings, equity, dividend payable",
        "affected_assertions": "Accuracy, cut-off, classification",
        "affected_departments": "Finance, Investor Relations",
        "legal_reference": "",
        "audit_standard_reference": "",
        "legal_reference_explanation": (
            "No specific legal reference is assigned because this is not a negative "
            "risk warning by itself."
        ),
        "audit_standard_explanation": (
            "Positive performance news may be useful context, but it is not shown "
            "as a legal/audit warning without additional risk indicators."
        ),
        "reference_responsibility": "Financial reporting context",
        "suggested_audit_response": (
            "Compare the announcement with reported revenue, profit, equity, and "
            "dividend-related disclosures if it is material to the audit."
        ),
    },
    "ma_strategic_investment": {
        "keywords": [
            "acquire",
            "acquisition",
            "buys",
            "deal",
            "investment",
            "invests",
            "merger",
            "m&a",
            "pipeline",
            "purchase",
            "takeover",
        ],
        "risk_types": [],
        "risk_drivers": [],
        "audit_risk_category": "M&A / strategic investment signal",
        "financial_statement_level_risk": "No",
        "affected_accounts": (
            "Investments, goodwill, intangible assets, cash, acquisition-related "
            "liabilities, disclosures"
        ),
        "affected_assertions": "Valuation, completeness, classification, presentation/disclosure",
        "affected_departments": "Finance, M&A, Legal, Investor Relations",
        "legal_reference": "",
        "audit_standard_reference": "",
        "legal_reference_explanation": (
            "No specific legal reference is assigned because this article is not a "
            "negative risk warning by itself."
        ),
        "audit_standard_explanation": (
            "The article may still be useful audit context because acquisitions or "
            "strategic investments can affect recognition, valuation, classification, "
            "and disclosure of acquired assets and obligations."
        ),
        "reference_responsibility": "Financial reporting context",
        "suggested_audit_response": (
            "No further investigation is necessary based on this signal alone. If "
            "the transaction is material, compare the article with management's "
            "transaction accounting, purchase price allocation, goodwill/intangible "
            "asset assessment, and disclosures."
        ),
    },
}


def map_audit_reference(
    text: str = "",
    risk_drivers: list[str] | None = None,
    risk_type: str = "",
) -> dict:
    """Return the best matching legal/audit reference mapping for a signal."""
    lowered = text.lower()
    drivers = set(risk_drivers or [])

    best_mapping = DEFAULT_REFERENCE
    best_score = 0
    for mapping in REFERENCE_MAPPINGS.values():
        score = 0
        score += sum(1 for keyword in mapping["keywords"] if keyword in lowered)
        score += 2 if risk_type in mapping["risk_types"] else 0
        score += 2 * len(drivers.intersection(mapping["risk_drivers"]))
        if score > best_score:
            best_score = score
            best_mapping = mapping

    return {
        key: value
        for key, value in best_mapping.items()
        if key not in {"keywords", "risk_types", "risk_drivers"}
    }
