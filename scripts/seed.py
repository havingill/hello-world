"""Generate the seeded finance-workflow dataset at data/workflows.json.

The reference data (domains, owners, systems, data objects, workflows and their
steps) is hand-authored below so it reads like a real finance operation. Only the
execution history (runs and exceptions) is generated, from a fixed random seed so
the committed JSON is reproducible: re-running this script yields byte-identical
output until the hand-authored data changes.

Usage:
    python scripts/seed.py [--out data/workflows.json]
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20260809
REPO_ROOT = Path(__file__).resolve().parent.parent

# The dataset is generated relative to a pinned "today" so that regenerating it
# later does not churn every timestamp in the diff.
TODAY = datetime(2026, 8, 9, tzinfo=timezone.utc)


DOMAINS = [
    {
        "id": "r2r",
        "name": "Record to Report",
        "description": "Close the books, reconcile balances and produce statutory and management reporting.",
    },
    {
        "id": "o2c",
        "name": "Order to Cash",
        "description": "Bill customers, apply cash, manage credit exposure and collect receivables.",
    },
    {
        "id": "p2p",
        "name": "Procure to Pay",
        "description": "Onboard suppliers, process invoices and settle payables.",
    },
    {
        "id": "fpa",
        "name": "Financial Planning & Analysis",
        "description": "Budgeting, forecasting and variance analysis against plan.",
    },
    {
        "id": "treasury",
        "name": "Treasury",
        "description": "Cash positioning, liquidity management and FX risk.",
    },
    {
        "id": "tax_compliance",
        "name": "Tax & Compliance",
        "description": "Indirect tax filings and internal control assurance.",
    },
]


OWNERS = [
    {"id": "own-mercer", "name": "A. Mercer", "role": "Group Financial Controller", "team": "Controllership"},
    {"id": "own-okafor", "name": "N. Okafor", "role": "Head of Accounting Operations", "team": "Controllership"},
    {"id": "own-delgado", "name": "R. Delgado", "role": "Credit & Collections Manager", "team": "Order to Cash"},
    {"id": "own-svensson", "name": "K. Svensson", "role": "Billing Operations Lead", "team": "Order to Cash"},
    {"id": "own-haruki", "name": "T. Haruki", "role": "Accounts Payable Manager", "team": "Procure to Pay"},
    {"id": "own-bassett", "name": "J. Bassett", "role": "Procurement Operations Lead", "team": "Procure to Pay"},
    {"id": "own-nwosu", "name": "C. Nwosu", "role": "FP&A Director", "team": "FP&A"},
    {"id": "own-lindqvist", "name": "P. Lindqvist", "role": "Group Treasurer", "team": "Treasury"},
    {"id": "own-abadi", "name": "S. Abadi", "role": "Indirect Tax Manager", "team": "Tax"},
    {"id": "own-fenwick", "name": "M. Fenwick", "role": "Internal Controls Lead", "team": "Risk & Compliance"},
]


SYSTEMS = [
    {"id": "sys-erp", "name": "SAP S/4HANA", "kind": "ERP"},
    {"id": "sys-blackline", "name": "BlackLine", "kind": "Close Management"},
    {"id": "sys-coupa", "name": "Coupa", "kind": "Procurement"},
    {"id": "sys-concur", "name": "SAP Concur", "kind": "Expense"},
    {"id": "sys-highradius", "name": "HighRadius", "kind": "Receivables"},
    {"id": "sys-salesforce", "name": "Salesforce", "kind": "CRM"},
    {"id": "sys-kyriba", "name": "Kyriba", "kind": "Treasury Management"},
    {"id": "sys-anaplan", "name": "Anaplan", "kind": "Planning"},
    {"id": "sys-vertex", "name": "Vertex", "kind": "Tax Engine"},
    {"id": "sys-bank", "name": "Bank Portals", "kind": "Banking"},
    {"id": "sys-powerbi", "name": "Power BI", "kind": "Reporting"},
    {"id": "sys-servicenow", "name": "ServiceNow", "kind": "Workflow / Ticketing"},
]


# These are the seeds of the eventual ontology. Steps declare which of these they
# consume and produce, which is exactly the material a later ontology agent needs
# to propose object types and their relationships.
DATA_OBJECTS = [
    {"id": "obj-journal-entry", "name": "Journal Entry", "description": "A debit/credit posting to the general ledger.", "domain_ids": ["r2r"]},
    {"id": "obj-gl-account", "name": "GL Account", "description": "A chart-of-accounts line against which postings are made.", "domain_ids": ["r2r", "fpa"]},
    {"id": "obj-trial-balance", "name": "Trial Balance", "description": "Period-end balances across all GL accounts.", "domain_ids": ["r2r"]},
    {"id": "obj-reconciliation", "name": "Reconciliation", "description": "Evidence that a balance agrees to an independent source.", "domain_ids": ["r2r"]},
    {"id": "obj-legal-entity", "name": "Legal Entity", "description": "A consolidating company in the group structure.", "domain_ids": ["r2r", "tax_compliance", "treasury"]},
    {"id": "obj-financial-statement", "name": "Financial Statement", "description": "Statutory or management reporting output for a period.", "domain_ids": ["r2r", "fpa"]},
    {"id": "obj-customer", "name": "Customer", "description": "A party billed for goods or services.", "domain_ids": ["o2c"]},
    {"id": "obj-sales-order", "name": "Sales Order", "description": "A confirmed customer order awaiting fulfilment and billing.", "domain_ids": ["o2c"]},
    {"id": "obj-customer-invoice", "name": "Customer Invoice", "description": "A receivable raised against a customer.", "domain_ids": ["o2c", "tax_compliance"]},
    {"id": "obj-remittance", "name": "Remittance Advice", "description": "Customer notification of what a payment settles.", "domain_ids": ["o2c"]},
    {"id": "obj-cash-receipt", "name": "Cash Receipt", "description": "Funds received into a bank account.", "domain_ids": ["o2c", "treasury"]},
    {"id": "obj-credit-limit", "name": "Credit Limit", "description": "Approved exposure ceiling for a customer.", "domain_ids": ["o2c"]},
    {"id": "obj-dunning-case", "name": "Dunning Case", "description": "An open collections action against an overdue receivable.", "domain_ids": ["o2c"]},
    {"id": "obj-vendor", "name": "Vendor", "description": "An approved supplier of goods or services.", "domain_ids": ["p2p"]},
    {"id": "obj-purchase-order", "name": "Purchase Order", "description": "A commitment to buy from a vendor.", "domain_ids": ["p2p"]},
    {"id": "obj-goods-receipt", "name": "Goods Receipt", "description": "Confirmation that ordered goods or services were delivered.", "domain_ids": ["p2p"]},
    {"id": "obj-vendor-invoice", "name": "Vendor Invoice", "description": "A payable raised by a supplier.", "domain_ids": ["p2p", "tax_compliance"]},
    {"id": "obj-payment-run", "name": "Payment Run", "description": "A batch of outbound settlements to vendors.", "domain_ids": ["p2p", "treasury"]},
    {"id": "obj-expense-report", "name": "Expense Report", "description": "Employee-submitted reimbursable spend.", "domain_ids": ["p2p"]},
    {"id": "obj-bank-statement", "name": "Bank Statement", "description": "Daily transaction feed from a banking partner.", "domain_ids": ["treasury", "r2r"]},
    {"id": "obj-cash-position", "name": "Cash Position", "description": "Consolidated available liquidity by currency and entity.", "domain_ids": ["treasury"]},
    {"id": "obj-fx-exposure", "name": "FX Exposure", "description": "Net currency exposure requiring hedge consideration.", "domain_ids": ["treasury"]},
    {"id": "obj-hedge-contract", "name": "Hedge Contract", "description": "A derivative booked to offset an exposure.", "domain_ids": ["treasury"]},
    {"id": "obj-budget", "name": "Budget", "description": "The approved annual financial plan.", "domain_ids": ["fpa"]},
    {"id": "obj-forecast", "name": "Forecast", "description": "A rolling projection superseding the budget.", "domain_ids": ["fpa"]},
    {"id": "obj-cost-centre", "name": "Cost Centre", "description": "An organisational unit accountable for spend.", "domain_ids": ["fpa", "r2r"]},
    {"id": "obj-variance", "name": "Variance", "description": "A gap between actual and plan requiring explanation.", "domain_ids": ["fpa"]},
    {"id": "obj-tax-return", "name": "Tax Return", "description": "A periodic filing to a tax authority.", "domain_ids": ["tax_compliance"]},
    {"id": "obj-tax-code", "name": "Tax Code", "description": "The rate and treatment applied to a transaction line.", "domain_ids": ["tax_compliance"]},
    {"id": "obj-control", "name": "Control", "description": "A documented check mitigating a financial reporting risk.", "domain_ids": ["tax_compliance", "r2r"]},
    {"id": "obj-control-evidence", "name": "Control Evidence", "description": "Artefact demonstrating a control operated effectively.", "domain_ids": ["tax_compliance"]},
]


def _step(
    seq: int,
    name: str,
    description: str,
    step_type: str,
    role: str,
    owner_id: str,
    duration_minutes: int,
    system_ids: list[str],
    inputs: list[str],
    outputs: list[str],
    controls: list[dict] | None = None,
) -> dict:
    return {
        "seq": seq,
        "name": name,
        "description": description,
        "type": step_type,
        "role": role,
        "owner_id": owner_id,
        "duration_minutes": duration_minutes,
        "system_ids": system_ids,
        "input_object_ids": inputs,
        "output_object_ids": outputs,
        "controls": controls or [],
    }


def _ctrl(control_id: str, name: str, control_type: str, framework: str = "SOX") -> dict:
    return {"id": control_id, "name": name, "type": control_type, "framework": framework}


WORKFLOWS = [
    {
        "id": "wf-month-end-close",
        "name": "Month-End Close",
        "domain_id": "r2r",
        "description": "Coordinate the group close from sub-ledger cut-off through to signed-off consolidated results.",
        "owner_id": "own-mercer",
        "status": "active",
        "maturity": "managed",
        "criticality": "critical",
        "frequency": "monthly",
        "sla_hours": 120,
        "system_ids": ["sys-erp", "sys-blackline", "sys-powerbi"],
        "tags": ["close", "consolidation", "sox"],
        "risk_notes": "Late sub-ledger cut-off from P2P is the single largest driver of close overrun.",
        "steps": [
            _step(1, "Sub-ledger cut-off", "Freeze AP, AR and payroll sub-ledgers and confirm no further postings.", "system", "Accounting Operations", "own-okafor", 60, ["sys-erp"], ["obj-vendor-invoice", "obj-customer-invoice"], ["obj-trial-balance"], [_ctrl("ctrl-close-01", "Cut-off confirmation sign-off", "preventive")]),
            _step(2, "Accruals and prepayments", "Post recurring accruals, releases and prepayment amortisation.", "manual", "Financial Accountant", "own-okafor", 240, ["sys-erp"], ["obj-gl-account"], ["obj-journal-entry"]),
            _step(3, "Intercompany matching", "Match and eliminate intercompany balances across legal entities.", "manual", "Financial Accountant", "own-okafor", 300, ["sys-erp", "sys-blackline"], ["obj-legal-entity", "obj-journal-entry"], ["obj-journal-entry"], [_ctrl("ctrl-close-02", "Intercompany variance under tolerance", "detective")]),
            _step(4, "Balance sheet reconciliations", "Complete and certify reconciliations for all in-scope accounts.", "review", "Financial Accountant", "own-okafor", 480, ["sys-blackline"], ["obj-gl-account", "obj-bank-statement"], ["obj-reconciliation"], [_ctrl("ctrl-close-03", "Reconciliation preparer/reviewer segregation", "preventive")]),
            _step(5, "Flux analysis", "Explain month-on-month movements above threshold to the controller.", "review", "Financial Controller", "own-mercer", 180, ["sys-erp", "sys-powerbi"], ["obj-trial-balance"], ["obj-variance"]),
            _step(6, "Consolidation run", "Execute group consolidation including FX translation.", "automated", "Systems Accountant", "own-mercer", 45, ["sys-erp"], ["obj-trial-balance", "obj-legal-entity"], ["obj-financial-statement"]),
            _step(7, "Controller sign-off", "Formal approval of results and release to management reporting.", "approval", "Group Financial Controller", "own-mercer", 60, ["sys-blackline"], ["obj-financial-statement"], ["obj-financial-statement"], [_ctrl("ctrl-close-04", "Documented close sign-off", "detective")]),
        ],
    },
    {
        "id": "wf-balance-sheet-recs",
        "name": "Balance Sheet Reconciliation",
        "domain_id": "r2r",
        "description": "Substantiate every balance sheet account against independent supporting evidence.",
        "owner_id": "own-okafor",
        "status": "active",
        "maturity": "managed",
        "criticality": "high",
        "frequency": "monthly",
        "sla_hours": 72,
        "system_ids": ["sys-blackline", "sys-erp"],
        "tags": ["reconciliation", "sox", "close"],
        "risk_notes": "High-risk accounts still rely on spreadsheet support outside BlackLine.",
        "steps": [
            _step(1, "Auto-certify low-risk accounts", "Rules engine certifies zero-balance and immaterial accounts.", "automated", "Systems Accountant", "own-okafor", 20, ["sys-blackline"], ["obj-gl-account"], ["obj-reconciliation"]),
            _step(2, "Pull supporting evidence", "Extract sub-ledger and bank support for remaining accounts.", "system", "Financial Accountant", "own-okafor", 120, ["sys-erp", "sys-bank"], ["obj-gl-account", "obj-bank-statement"], ["obj-control-evidence"]),
            _step(3, "Prepare reconciliations", "Reconcile balances and document reconciling items with ageing.", "manual", "Financial Accountant", "own-okafor", 420, ["sys-blackline"], ["obj-gl-account"], ["obj-reconciliation"]),
            _step(4, "Investigate aged items", "Clear or explain reconciling items older than 60 days.", "manual", "Financial Accountant", "own-okafor", 180, ["sys-blackline", "sys-erp"], ["obj-reconciliation"], ["obj-journal-entry"], [_ctrl("ctrl-rec-01", "Aged reconciling item escalation", "detective")]),
            _step(5, "Independent review", "Reviewer challenges support and approves certification.", "approval", "Financial Controller", "own-mercer", 150, ["sys-blackline"], ["obj-reconciliation"], ["obj-reconciliation"], [_ctrl("ctrl-rec-02", "Preparer/reviewer segregation of duties", "preventive")]),
        ],
    },
    {
        "id": "wf-customer-invoicing",
        "name": "Customer Invoicing",
        "domain_id": "o2c",
        "description": "Convert fulfilled orders into accurate, tax-compliant invoices delivered to the customer.",
        "owner_id": "own-svensson",
        "status": "active",
        "maturity": "optimized",
        "criticality": "high",
        "frequency": "daily",
        "sla_hours": 24,
        "system_ids": ["sys-erp", "sys-salesforce", "sys-vertex"],
        "tags": ["billing", "revenue", "automation"],
        "risk_notes": "Manual pricing overrides on enterprise deals remain the main source of credit notes.",
        "steps": [
            _step(1, "Collect billable events", "Pull fulfilled orders and usage records ready to bill.", "automated", "Billing Analyst", "own-svensson", 15, ["sys-salesforce", "sys-erp"], ["obj-sales-order"], ["obj-sales-order"]),
            _step(2, "Validate pricing and terms", "Check contract rates, discounts and billing schedule.", "system", "Billing Analyst", "own-svensson", 45, ["sys-salesforce"], ["obj-sales-order", "obj-customer"], ["obj-sales-order"], [_ctrl("ctrl-bill-01", "Price-to-contract validation", "preventive")]),
            _step(3, "Determine tax treatment", "Apply jurisdiction tax codes via the tax engine.", "automated", "Tax Analyst", "own-abadi", 10, ["sys-vertex"], ["obj-sales-order", "obj-tax-code"], ["obj-tax-code"]),
            _step(4, "Generate invoice", "Create the receivable and post to the sub-ledger.", "automated", "Billing Analyst", "own-svensson", 10, ["sys-erp"], ["obj-sales-order"], ["obj-customer-invoice"]),
            _step(5, "Exception review", "Review invoices held by validation rules before release.", "review", "Billing Operations Lead", "own-svensson", 90, ["sys-erp"], ["obj-customer-invoice"], ["obj-customer-invoice"], [_ctrl("ctrl-bill-02", "Held-invoice review before release", "detective")]),
            _step(6, "Deliver to customer", "Dispatch via e-invoicing network, portal or email.", "automated", "Billing Analyst", "own-svensson", 10, ["sys-erp"], ["obj-customer-invoice"], ["obj-customer-invoice"]),
        ],
    },
    {
        "id": "wf-cash-application",
        "name": "Cash Application",
        "domain_id": "o2c",
        "description": "Match incoming customer payments to open receivables and clear the ledger.",
        "owner_id": "own-delgado",
        "status": "active",
        "maturity": "managed",
        "criticality": "high",
        "frequency": "daily",
        "sla_hours": 24,
        "system_ids": ["sys-highradius", "sys-erp", "sys-bank"],
        "tags": ["cash", "receivables", "automation"],
        "risk_notes": "Unapplied cash spikes when customers pay by consolidated remittance without invoice references.",
        "steps": [
            _step(1, "Import bank transactions", "Load prior-day statements from all banking partners.", "automated", "Cash Application Analyst", "own-delgado", 15, ["sys-bank", "sys-highradius"], ["obj-bank-statement"], ["obj-cash-receipt"]),
            _step(2, "Auto-match receipts", "Machine matching of receipts to open invoices.", "automated", "Cash Application Analyst", "own-delgado", 20, ["sys-highradius"], ["obj-cash-receipt", "obj-customer-invoice"], ["obj-cash-receipt"]),
            _step(3, "Resolve unmatched cash", "Chase remittance detail and manually apply residual receipts.", "manual", "Cash Application Analyst", "own-delgado", 210, ["sys-highradius", "sys-erp"], ["obj-cash-receipt", "obj-remittance"], ["obj-cash-receipt"]),
            _step(4, "Handle short pays and deductions", "Route disputed deductions to the relevant business owner.", "manual", "Credit Analyst", "own-delgado", 120, ["sys-highradius", "sys-servicenow"], ["obj-cash-receipt"], ["obj-dunning-case"]),
            _step(5, "Post and clear", "Post applications and clear the customer sub-ledger.", "system", "Cash Application Analyst", "own-delgado", 30, ["sys-erp"], ["obj-cash-receipt"], ["obj-customer-invoice"], [_ctrl("ctrl-cash-01", "Unapplied cash ageing review", "detective")]),
        ],
    },
    {
        "id": "wf-collections-dunning",
        "name": "Collections & Dunning",
        "domain_id": "o2c",
        "description": "Pursue overdue receivables through a risk-tiered contact strategy to escalation.",
        "owner_id": "own-delgado",
        "status": "active",
        "maturity": "defined",
        "criticality": "medium",
        "frequency": "weekly",
        "sla_hours": 48,
        "system_ids": ["sys-highradius", "sys-salesforce", "sys-erp"],
        "tags": ["collections", "working-capital"],
        "risk_notes": "Strategy is uniform across segments; strategic accounts receive the same dunning as low-value ones.",
        "steps": [
            _step(1, "Refresh ageing", "Rebuild the receivables ageing and overdue worklist.", "automated", "Credit Analyst", "own-delgado", 20, ["sys-erp", "sys-highradius"], ["obj-customer-invoice"], ["obj-dunning-case"]),
            _step(2, "Segment and prioritise", "Rank accounts by exposure, risk score and days overdue.", "system", "Credit Analyst", "own-delgado", 60, ["sys-highradius"], ["obj-dunning-case", "obj-customer"], ["obj-dunning-case"]),
            _step(3, "Execute contact strategy", "Issue reminders and make collection calls per tier.", "manual", "Credit Analyst", "own-delgado", 300, ["sys-highradius", "sys-salesforce"], ["obj-dunning-case"], ["obj-dunning-case"]),
            _step(4, "Log promises to pay", "Record commitments and diarise follow-up.", "manual", "Credit Analyst", "own-delgado", 90, ["sys-highradius"], ["obj-dunning-case"], ["obj-dunning-case"]),
            _step(5, "Escalate and provision", "Refer non-responsive accounts and propose bad debt provision.", "approval", "Credit & Collections Manager", "own-delgado", 120, ["sys-erp"], ["obj-dunning-case"], ["obj-journal-entry"], [_ctrl("ctrl-coll-01", "Bad debt provision approval", "preventive")]),
        ],
    },
    {
        "id": "wf-credit-review",
        "name": "Customer Credit Review",
        "domain_id": "o2c",
        "description": "Assess and periodically re-assess customer creditworthiness and exposure limits.",
        "owner_id": "own-delgado",
        "status": "under_review",
        "maturity": "defined",
        "criticality": "medium",
        "frequency": "quarterly",
        "sla_hours": 168,
        "system_ids": ["sys-salesforce", "sys-erp"],
        "tags": ["credit", "risk"],
        "risk_notes": "Limits for mid-market accounts have not been refreshed within policy for two cycles.",
        "steps": [
            _step(1, "Identify accounts due", "Select customers due periodic review or breaching limits.", "automated", "Credit Analyst", "own-delgado", 30, ["sys-erp"], ["obj-customer", "obj-credit-limit"], ["obj-customer"]),
            _step(2, "Gather credit data", "Pull bureau scores, payment history and exposure.", "manual", "Credit Analyst", "own-delgado", 180, ["sys-salesforce", "sys-erp"], ["obj-customer", "obj-customer-invoice"], ["obj-customer"]),
            _step(3, "Recommend limit", "Model the proposed limit and payment terms.", "manual", "Credit Analyst", "own-delgado", 120, ["sys-erp"], ["obj-customer"], ["obj-credit-limit"]),
            _step(4, "Approve limit", "Apply delegated authority matrix and record approval.", "approval", "Credit & Collections Manager", "own-delgado", 60, ["sys-erp"], ["obj-credit-limit"], ["obj-credit-limit"], [_ctrl("ctrl-cred-01", "Credit limit delegated authority", "preventive")]),
        ],
    },
    {
        "id": "wf-invoice-processing",
        "name": "Vendor Invoice Processing",
        "domain_id": "p2p",
        "description": "Capture, match and post supplier invoices ready for payment.",
        "owner_id": "own-haruki",
        "status": "active",
        "maturity": "managed",
        "criticality": "high",
        "frequency": "daily",
        "sla_hours": 48,
        "system_ids": ["sys-coupa", "sys-erp", "sys-vertex"],
        "tags": ["accounts-payable", "three-way-match", "sox"],
        "risk_notes": "Goods receipt is often posted late, so match failures cluster at period end.",
        "steps": [
            _step(1, "Capture invoice", "OCR and digitise inbound supplier invoices.", "automated", "AP Analyst", "own-haruki", 15, ["sys-coupa"], ["obj-vendor-invoice"], ["obj-vendor-invoice"]),
            _step(2, "Validate vendor and bank detail", "Confirm the vendor is approved and bank detail unchanged.", "system", "AP Analyst", "own-haruki", 30, ["sys-coupa", "sys-erp"], ["obj-vendor", "obj-vendor-invoice"], ["obj-vendor"], [_ctrl("ctrl-ap-01", "Vendor bank detail change verification", "preventive")]),
            _step(3, "Three-way match", "Match invoice to purchase order and goods receipt.", "automated", "AP Analyst", "own-haruki", 20, ["sys-erp"], ["obj-vendor-invoice", "obj-purchase-order", "obj-goods-receipt"], ["obj-vendor-invoice"], [_ctrl("ctrl-ap-02", "Three-way match tolerance", "preventive")]),
            _step(4, "Resolve match exceptions", "Chase requisitioners for receipts or price approvals.", "manual", "AP Analyst", "own-haruki", 240, ["sys-coupa", "sys-servicenow"], ["obj-vendor-invoice", "obj-purchase-order"], ["obj-vendor-invoice"]),
            _step(5, "Apply tax treatment", "Determine recoverable and irrecoverable input tax.", "system", "Tax Analyst", "own-abadi", 45, ["sys-vertex"], ["obj-vendor-invoice", "obj-tax-code"], ["obj-tax-code"]),
            _step(6, "Post to ledger", "Post the payable and route for payment scheduling.", "automated", "AP Analyst", "own-haruki", 15, ["sys-erp"], ["obj-vendor-invoice"], ["obj-journal-entry"]),
        ],
    },
    {
        "id": "wf-payment-run",
        "name": "Vendor Payment Run",
        "domain_id": "p2p",
        "description": "Select, approve and release scheduled supplier payments.",
        "owner_id": "own-haruki",
        "status": "active",
        "maturity": "managed",
        "criticality": "critical",
        "frequency": "weekly",
        "sla_hours": 24,
        "system_ids": ["sys-erp", "sys-kyriba", "sys-bank"],
        "tags": ["payments", "fraud-risk", "sox"],
        "risk_notes": "Payment release depends on two named approvers; cover during leave is thin.",
        "steps": [
            _step(1, "Build proposal", "Select due invoices by due date, entity and currency.", "automated", "AP Analyst", "own-haruki", 30, ["sys-erp"], ["obj-vendor-invoice"], ["obj-payment-run"]),
            _step(2, "Screen for duplicates and sanctions", "Run duplicate detection and sanctions screening.", "system", "AP Analyst", "own-haruki", 45, ["sys-erp", "sys-kyriba"], ["obj-payment-run", "obj-vendor"], ["obj-payment-run"], [_ctrl("ctrl-pay-01", "Duplicate payment detection", "detective"), _ctrl("ctrl-pay-02", "Sanctions screening", "preventive")]),
            _step(3, "Confirm funding", "Check cleared funds by currency against the position.", "review", "Treasury Analyst", "own-lindqvist", 60, ["sys-kyriba"], ["obj-payment-run", "obj-cash-position"], ["obj-cash-position"]),
            _step(4, "Dual approval", "Two authorised approvers release the payment file.", "approval", "AP Manager", "own-haruki", 45, ["sys-erp", "sys-kyriba"], ["obj-payment-run"], ["obj-payment-run"], [_ctrl("ctrl-pay-03", "Dual authorisation on payment release", "preventive")]),
            _step(5, "Transmit and confirm", "Send the file to the bank and reconcile acknowledgements.", "system", "AP Analyst", "own-haruki", 60, ["sys-bank"], ["obj-payment-run"], ["obj-bank-statement"], [_ctrl("ctrl-pay-04", "Bank acknowledgement reconciliation", "detective")]),
        ],
    },
    {
        "id": "wf-vendor-onboarding",
        "name": "Vendor Onboarding",
        "domain_id": "p2p",
        "description": "Qualify, verify and activate a new supplier in the vendor master.",
        "owner_id": "own-bassett",
        "status": "active",
        "maturity": "defined",
        "criticality": "high",
        "frequency": "weekly",
        "sla_hours": 120,
        "system_ids": ["sys-coupa", "sys-erp", "sys-servicenow"],
        "tags": ["master-data", "fraud-risk", "third-party-risk"],
        "risk_notes": "Bank detail verification is a manual callback with inconsistent evidence retention.",
        "steps": [
            _step(1, "Intake request", "Business submits a supplier request with justification.", "manual", "Requisitioner", "own-bassett", 45, ["sys-servicenow"], ["obj-vendor"], ["obj-vendor"]),
            _step(2, "Due diligence screening", "Sanctions, adverse media and beneficial ownership checks.", "system", "Procurement Analyst", "own-bassett", 120, ["sys-coupa"], ["obj-vendor"], ["obj-vendor"], [_ctrl("ctrl-vend-01", "Third-party screening before activation", "preventive")]),
            _step(3, "Verify bank detail", "Independent callback to a verified contact on file.", "manual", "AP Analyst", "own-haruki", 90, ["sys-coupa"], ["obj-vendor"], ["obj-control-evidence"], [_ctrl("ctrl-vend-02", "Independent bank detail callback", "preventive")]),
            _step(4, "Tax and compliance data", "Collect tax registration and withholding status.", "manual", "Tax Analyst", "own-abadi", 60, ["sys-vertex"], ["obj-vendor", "obj-tax-code"], ["obj-tax-code"]),
            _step(5, "Approve and activate", "Create the vendor master record under segregated access.", "approval", "Procurement Operations Lead", "own-bassett", 45, ["sys-erp"], ["obj-vendor"], ["obj-vendor"], [_ctrl("ctrl-vend-03", "Vendor master maintenance segregation", "preventive")]),
        ],
    },
    {
        "id": "wf-expense-reimbursement",
        "name": "Employee Expense Reimbursement",
        "domain_id": "p2p",
        "description": "Review, approve and reimburse employee-submitted expenses under policy.",
        "owner_id": "own-haruki",
        "status": "active",
        "maturity": "optimized",
        "criticality": "low",
        "frequency": "weekly",
        "sla_hours": 96,
        "system_ids": ["sys-concur", "sys-erp"],
        "tags": ["expenses", "policy"],
        "risk_notes": "Low value, high volume; audit sampling rather than full review is the accepted approach.",
        "steps": [
            _step(1, "Submit claim", "Employee submits receipts and coding.", "manual", "Employee", "own-haruki", 30, ["sys-concur"], ["obj-expense-report"], ["obj-expense-report"]),
            _step(2, "Policy engine check", "Automated policy and duplicate-receipt checks.", "automated", "AP Analyst", "own-haruki", 5, ["sys-concur"], ["obj-expense-report"], ["obj-expense-report"], [_ctrl("ctrl-exp-01", "Automated policy rule enforcement", "preventive")]),
            _step(3, "Line manager approval", "Cost centre owner approves the spend.", "approval", "Line Manager", "own-nwosu", 30, ["sys-concur"], ["obj-expense-report", "obj-cost-centre"], ["obj-expense-report"]),
            _step(4, "Audit sample review", "Risk-based sample reviewed against receipts.", "review", "AP Analyst", "own-haruki", 90, ["sys-concur"], ["obj-expense-report"], ["obj-control-evidence"], [_ctrl("ctrl-exp-02", "Risk-based expense audit sampling", "detective")]),
            _step(5, "Reimburse", "Include in the payment run and post to the ledger.", "automated", "AP Analyst", "own-haruki", 15, ["sys-erp"], ["obj-expense-report"], ["obj-payment-run"]),
        ],
    },
    {
        "id": "wf-rolling-forecast",
        "name": "Rolling Forecast",
        "domain_id": "fpa",
        "description": "Refresh the 12-month rolling forecast with business input and challenge.",
        "owner_id": "own-nwosu",
        "status": "active",
        "maturity": "defined",
        "criticality": "medium",
        "frequency": "monthly",
        "sla_hours": 168,
        "system_ids": ["sys-anaplan", "sys-erp", "sys-powerbi"],
        "tags": ["planning", "forecast"],
        "risk_notes": "Cost centre owners submit late, compressing the challenge window to under a day.",
        "steps": [
            _step(1, "Load actuals", "Push closed-period actuals into the planning model.", "automated", "FP&A Analyst", "own-nwosu", 30, ["sys-erp", "sys-anaplan"], ["obj-trial-balance"], ["obj-forecast"]),
            _step(2, "Seed driver assumptions", "Update volume, price and headcount drivers.", "manual", "FP&A Analyst", "own-nwosu", 180, ["sys-anaplan"], ["obj-forecast"], ["obj-forecast"]),
            _step(3, "Collect business submissions", "Cost centre owners submit their forecast positions.", "manual", "Cost Centre Owner", "own-nwosu", 480, ["sys-anaplan"], ["obj-cost-centre", "obj-forecast"], ["obj-forecast"]),
            _step(4, "Challenge and consolidate", "Challenge submissions against trend and consolidate.", "review", "FP&A Director", "own-nwosu", 300, ["sys-anaplan"], ["obj-forecast"], ["obj-forecast"]),
            _step(5, "Publish forecast pack", "Distribute the approved forecast and commentary.", "automated", "FP&A Analyst", "own-nwosu", 60, ["sys-powerbi"], ["obj-forecast"], ["obj-financial-statement"]),
        ],
    },
    {
        "id": "wf-variance-analysis",
        "name": "Budget Variance Analysis",
        "domain_id": "fpa",
        "description": "Explain actual-to-plan variances above threshold and agree corrective actions.",
        "owner_id": "own-nwosu",
        "status": "active",
        "maturity": "defined",
        "criticality": "medium",
        "frequency": "monthly",
        "sla_hours": 72,
        "system_ids": ["sys-anaplan", "sys-powerbi", "sys-erp"],
        "tags": ["reporting", "variance"],
        "risk_notes": "Commentary quality varies widely by cost centre owner.",
        "steps": [
            _step(1, "Generate variance report", "Compute actual versus budget and forecast by cost centre.", "automated", "FP&A Analyst", "own-nwosu", 30, ["sys-powerbi", "sys-erp"], ["obj-trial-balance", "obj-budget"], ["obj-variance"]),
            _step(2, "Apply materiality filter", "Isolate variances above absolute and percentage thresholds.", "system", "FP&A Analyst", "own-nwosu", 20, ["sys-powerbi"], ["obj-variance"], ["obj-variance"]),
            _step(3, "Request commentary", "Route material variances to cost centre owners.", "manual", "FP&A Analyst", "own-nwosu", 120, ["sys-servicenow"], ["obj-variance", "obj-cost-centre"], ["obj-variance"]),
            _step(4, "Review and agree actions", "Business review meeting agrees corrective actions.", "review", "FP&A Director", "own-nwosu", 120, ["sys-powerbi"], ["obj-variance"], ["obj-variance"]),
        ],
    },
    {
        "id": "wf-cash-positioning",
        "name": "Daily Cash Positioning",
        "domain_id": "treasury",
        "description": "Establish the group cash position and fund the day's obligations.",
        "owner_id": "own-lindqvist",
        "status": "active",
        "maturity": "optimized",
        "criticality": "critical",
        "frequency": "daily",
        "sla_hours": 4,
        "system_ids": ["sys-kyriba", "sys-bank", "sys-erp"],
        "tags": ["liquidity", "treasury", "daily"],
        "risk_notes": "One regional bank still delivers statements by manual download.",
        "steps": [
            _step(1, "Import balances", "Pull opening balances across all bank accounts.", "automated", "Treasury Analyst", "own-lindqvist", 15, ["sys-bank", "sys-kyriba"], ["obj-bank-statement"], ["obj-cash-position"]),
            _step(2, "Layer in known flows", "Add scheduled receipts, payroll and payment runs.", "system", "Treasury Analyst", "own-lindqvist", 45, ["sys-kyriba", "sys-erp"], ["obj-payment-run", "obj-cash-receipt"], ["obj-cash-position"]),
            _step(3, "Determine funding actions", "Decide sweeps, borrowings and investments by currency.", "manual", "Treasury Analyst", "own-lindqvist", 60, ["sys-kyriba"], ["obj-cash-position"], ["obj-cash-position"]),
            _step(4, "Approve and execute", "Approve movements and instruct the banks.", "approval", "Group Treasurer", "own-lindqvist", 30, ["sys-kyriba", "sys-bank"], ["obj-cash-position"], ["obj-bank-statement"], [_ctrl("ctrl-cash-02", "Dual authorisation on treasury movements", "preventive")]),
        ],
    },
    {
        "id": "wf-fx-hedging",
        "name": "FX Exposure & Hedging",
        "domain_id": "treasury",
        "description": "Quantify net currency exposure and execute hedges within policy limits.",
        "owner_id": "own-lindqvist",
        "status": "active",
        "maturity": "managed",
        "criticality": "high",
        "frequency": "monthly",
        "sla_hours": 48,
        "system_ids": ["sys-kyriba", "sys-erp"],
        "tags": ["fx", "risk", "hedge-accounting"],
        "risk_notes": "Exposure data depends on forecast quality from FP&A; late forecasts delay hedge execution.",
        "steps": [
            _step(1, "Aggregate exposures", "Consolidate balance sheet and forecast exposures by currency.", "automated", "Treasury Analyst", "own-lindqvist", 60, ["sys-erp", "sys-kyriba"], ["obj-forecast", "obj-trial-balance"], ["obj-fx-exposure"]),
            _step(2, "Compare to policy limits", "Test net exposure against approved hedge ratios.", "system", "Treasury Analyst", "own-lindqvist", 45, ["sys-kyriba"], ["obj-fx-exposure"], ["obj-fx-exposure"], [_ctrl("ctrl-fx-01", "Hedge ratio within policy band", "detective")]),
            _step(3, "Execute hedges", "Deal forwards or swaps with panel counterparties.", "manual", "Group Treasurer", "own-lindqvist", 90, ["sys-kyriba"], ["obj-fx-exposure"], ["obj-hedge-contract"]),
            _step(4, "Document hedge designation", "Prepare hedge accounting documentation and effectiveness testing.", "manual", "Financial Accountant", "own-mercer", 180, ["sys-erp"], ["obj-hedge-contract"], ["obj-control-evidence"], [_ctrl("ctrl-fx-02", "Hedge designation documented at inception", "preventive")]),
        ],
    },
    {
        "id": "wf-vat-filing",
        "name": "Indirect Tax (VAT) Filing",
        "domain_id": "tax_compliance",
        "description": "Prepare, review and submit periodic indirect tax returns by jurisdiction.",
        "owner_id": "own-abadi",
        "status": "active",
        "maturity": "managed",
        "criticality": "critical",
        "frequency": "monthly",
        "sla_hours": 96,
        "system_ids": ["sys-vertex", "sys-erp"],
        "tags": ["tax", "statutory", "deadline-driven"],
        "risk_notes": "Filing deadlines are statutory; a missed submission carries automatic penalties.",
        "steps": [
            _step(1, "Extract transaction data", "Pull taxable transactions by jurisdiction and tax code.", "automated", "Tax Analyst", "own-abadi", 45, ["sys-erp", "sys-vertex"], ["obj-customer-invoice", "obj-vendor-invoice"], ["obj-tax-code"]),
            _step(2, "Run validation rules", "Test for missing or inconsistent tax determinations.", "system", "Tax Analyst", "own-abadi", 60, ["sys-vertex"], ["obj-tax-code"], ["obj-tax-code"], [_ctrl("ctrl-tax-01", "Tax determination validation rules", "detective")]),
            _step(3, "Resolve exceptions", "Correct misclassified transactions and post adjustments.", "manual", "Tax Analyst", "own-abadi", 240, ["sys-erp"], ["obj-tax-code"], ["obj-journal-entry"]),
            _step(4, "Reconcile to ledger", "Agree the return to the GL tax control accounts.", "review", "Indirect Tax Manager", "own-abadi", 120, ["sys-erp"], ["obj-tax-return", "obj-gl-account"], ["obj-reconciliation"], [_ctrl("ctrl-tax-02", "Return-to-ledger reconciliation", "detective")]),
            _step(5, "Review and submit", "Manager approval and submission to the authority.", "approval", "Indirect Tax Manager", "own-abadi", 90, ["sys-vertex"], ["obj-tax-return"], ["obj-tax-return"], [_ctrl("ctrl-tax-03", "Return approved before submission", "preventive")]),
        ],
    },
    {
        "id": "wf-sox-control-testing",
        "name": "SOX Control Testing",
        "domain_id": "tax_compliance",
        "description": "Test the design and operating effectiveness of key financial reporting controls.",
        "owner_id": "own-fenwick",
        "status": "active",
        "maturity": "defined",
        "criticality": "high",
        "frequency": "quarterly",
        "sla_hours": 336,
        "system_ids": ["sys-servicenow", "sys-blackline", "sys-erp"],
        "tags": ["sox", "assurance", "controls"],
        "risk_notes": "Evidence collection is largely manual; testers chase artefacts by email.",
        "steps": [
            _step(1, "Confirm control scope", "Agree the in-scope control population for the cycle.", "review", "Internal Controls Lead", "own-fenwick", 240, ["sys-servicenow"], ["obj-control"], ["obj-control"]),
            _step(2, "Select samples", "Draw statistically valid samples per control.", "system", "Controls Tester", "own-fenwick", 120, ["sys-servicenow"], ["obj-control"], ["obj-control"]),
            _step(3, "Collect evidence", "Request and chase supporting artefacts from control owners.", "manual", "Controls Tester", "own-fenwick", 900, ["sys-servicenow", "sys-blackline"], ["obj-control"], ["obj-control-evidence"]),
            _step(4, "Perform testing", "Execute test procedures and document conclusions.", "manual", "Controls Tester", "own-fenwick", 720, ["sys-servicenow"], ["obj-control-evidence"], ["obj-control-evidence"]),
            _step(5, "Log and track deficiencies", "Raise findings, agree remediation and track to closure.", "review", "Internal Controls Lead", "own-fenwick", 300, ["sys-servicenow"], ["obj-control-evidence"], ["obj-control"], [_ctrl("ctrl-sox-01", "Deficiency remediation tracked to closure", "detective")]),
        ],
    },
    {
        "id": "wf-lease-accounting",
        "name": "Lease Accounting (IFRS 16)",
        "domain_id": "r2r",
        "description": "Maintain the lease register and post right-of-use asset and liability movements.",
        "owner_id": "own-mercer",
        "status": "draft",
        "maturity": "ad_hoc",
        "criticality": "medium",
        "frequency": "monthly",
        "sla_hours": 96,
        "system_ids": ["sys-erp"],
        "tags": ["ifrs16", "leases", "new-process"],
        "risk_notes": "Currently spreadsheet-driven and undocumented; being formalised ahead of system migration.",
        "steps": [
            _step(1, "Capture new and modified leases", "Collect lease contracts and modifications from the business.", "manual", "Financial Accountant", "own-okafor", 180, ["sys-erp"], ["obj-legal-entity"], ["obj-journal-entry"]),
            _step(2, "Calculate ROU and liability", "Compute right-of-use asset and lease liability schedules.", "manual", "Financial Accountant", "own-okafor", 240, ["sys-erp"], ["obj-journal-entry"], ["obj-journal-entry"]),
            _step(3, "Post monthly movements", "Post depreciation, interest and remeasurements.", "manual", "Financial Accountant", "own-okafor", 120, ["sys-erp"], ["obj-journal-entry"], ["obj-gl-account"]),
            _step(4, "Reconcile lease register", "Agree the register to the ledger and disclosure note.", "review", "Group Financial Controller", "own-mercer", 120, ["sys-erp"], ["obj-gl-account"], ["obj-reconciliation"]),
        ],
    },
]


# Exception templates keyed by workflow, so generated failures read plausibly
# rather than generically.
EXCEPTION_TEMPLATES = {
    "wf-month-end-close": [
        "Intercompany mismatch above tolerance between two entities held the consolidation run.",
        "Payroll accrual received after cut-off required a reopened period.",
        "Consolidation FX rates loaded late, forcing a re-run of the translation.",
    ],
    "wf-balance-sheet-recs": [
        "Aged reconciling items on a clearing account breached the 60-day policy.",
        "Bank support unavailable for one entity; certification deferred.",
        "Reviewer rejected a reconciliation for insufficient supporting evidence.",
    ],
    "wf-customer-invoicing": [
        "Pricing override on an enterprise contract failed price-to-contract validation.",
        "Tax engine returned no jurisdiction for a new territory; invoices held.",
        "E-invoicing network rejected a batch on schema validation.",
    ],
    "wf-cash-application": [
        "Consolidated remittance without invoice references left cash unapplied.",
        "Bank statement feed failed for one partner; manual download required.",
        "Customer deduction disputed and routed to the business for resolution.",
    ],
    "wf-collections-dunning": [
        "Dunning letters suppressed for a strategic account pending relationship review.",
        "Ageing refresh ran against stale receivables data.",
    ],
    "wf-credit-review": [
        "Bureau data unavailable for a private mid-market customer.",
        "Review cycle exceeded policy window; limits carried forward unchanged.",
    ],
    "wf-invoice-processing": [
        "Goods receipt not posted, so three-way match failed at period end.",
        "Vendor bank detail change could not be verified; invoice quarantined.",
        "Price variance outside tolerance awaiting requisitioner approval.",
    ],
    "wf-payment-run": [
        "Duplicate payment candidate flagged and removed from the proposal.",
        "Insufficient cleared funds in one currency delayed release.",
        "Second approver unavailable; release slipped past the cut-off.",
    ],
    "wf-vendor-onboarding": [
        "Adverse media hit required enhanced due diligence before activation.",
        "Bank detail callback reached an unverified contact and was restarted.",
        "Tax registration evidence missing for a cross-border supplier.",
    ],
    "wf-expense-reimbursement": [
        "Duplicate receipt detected across two claims.",
        "Line manager approval outstanding beyond the reimbursement cut-off.",
    ],
    "wf-rolling-forecast": [
        "Cost centre submissions late, compressing the challenge window.",
        "Driver assumptions not refreshed before submissions opened.",
    ],
    "wf-variance-analysis": [
        "Commentary not provided for a material variance before the review meeting.",
        "Budget version mismatch produced misleading variances.",
    ],
    "wf-cash-positioning": [
        "Regional bank statement required manual download, delaying the position.",
        "Unexpected large receipt changed the funding decision after approval.",
    ],
    "wf-fx-hedging": [
        "Forecast exposure arrived late from FP&A, delaying hedge execution.",
        "Hedge ratio drifted outside the policy band before rebalancing.",
    ],
    "wf-vat-filing": [
        "Misclassified transactions in a new jurisdiction required bulk correction.",
        "Return-to-ledger reconciliation showed an unexplained difference.",
        "Authority portal outage on the submission date.",
    ],
    "wf-sox-control-testing": [
        "Control owner did not provide evidence within the agreed window.",
        "Sample selection had to be redrawn after a population error.",
        "Deficiency identified in vendor master segregation of duties.",
    ],
    "wf-lease-accounting": [
        "Lease modification identified after posting, requiring a prior-period adjustment.",
        "Spreadsheet formula error found in the liability schedule.",
    ],
}


# Per-workflow reliability profile: (on-time probability, failure probability,
# mean overrun factor against planned duration).
PROFILES = {
    "wf-month-end-close": (0.72, 0.06, 1.14),
    "wf-balance-sheet-recs": (0.78, 0.04, 1.10),
    "wf-customer-invoicing": (0.95, 0.02, 0.96),
    "wf-cash-application": (0.88, 0.03, 1.02),
    "wf-collections-dunning": (0.82, 0.04, 1.05),
    "wf-credit-review": (0.61, 0.10, 1.28),
    "wf-invoice-processing": (0.84, 0.05, 1.08),
    "wf-payment-run": (0.91, 0.03, 0.98),
    "wf-vendor-onboarding": (0.66, 0.09, 1.24),
    "wf-expense-reimbursement": (0.96, 0.01, 0.94),
    "wf-rolling-forecast": (0.69, 0.05, 1.18),
    "wf-variance-analysis": (0.80, 0.03, 1.06),
    "wf-cash-positioning": (0.97, 0.02, 0.95),
    "wf-fx-hedging": (0.85, 0.04, 1.04),
    "wf-vat-filing": (0.89, 0.05, 1.03),
    "wf-sox-control-testing": (0.58, 0.12, 1.35),
    "wf-lease-accounting": (0.55, 0.14, 1.42),
}


# How many historical runs to generate per cadence, and how far apart they sit.
CADENCE = {
    "daily": (30, 1),
    "weekly": (18, 7),
    "monthly": (12, 30),
    "quarterly": (6, 91),
}

SEVERITIES = ["low", "medium", "high"]


def _planned_hours(workflow: dict) -> float:
    """Sum of step effort, in hours. Used as the baseline for run duration."""
    return sum(step["duration_minutes"] for step in workflow["steps"]) / 60.0


def _period_label(moment: datetime, frequency: str) -> str:
    if frequency == "quarterly":
        return f"{moment.year}-Q{(moment.month - 1) // 3 + 1}"
    if frequency in ("daily", "weekly"):
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m")


def generate_runs(rng: random.Random) -> list[dict]:
    runs: list[dict] = []
    for workflow in WORKFLOWS:
        # A draft process has not been operated yet, so it has no history.
        if workflow["status"] == "draft":
            continue

        count, spacing_days = CADENCE[workflow["frequency"]]
        on_time_p, fail_p, overrun = PROFILES[workflow["id"]]
        planned = _planned_hours(workflow)
        sla = workflow["sla_hours"]
        templates = EXCEPTION_TEMPLATES[workflow["id"]]

        for index in range(count):
            # index 0 is the most recent run; walk backwards in time.
            started = TODAY - timedelta(days=spacing_days * index, hours=rng.uniform(0, 8))
            duration = max(0.25, planned * overrun * rng.uniform(0.72, 1.34))

            roll = rng.random()
            if index == 0 and workflow["frequency"] in ("daily", "weekly") and rng.random() < 0.45:
                status = "in_progress"
            elif roll < fail_p:
                status = "failed"
            else:
                status = "completed"

            if status == "completed" and rng.random() > on_time_p:
                # Overrun the SLA rather than the effort estimate.
                duration = sla * rng.uniform(1.05, 1.6)

            completed_at = None if status == "in_progress" else started + timedelta(hours=duration)
            sla_met = None if status == "in_progress" else (status == "completed" and duration <= sla)

            exceptions = []
            expected_exceptions = 0
            if status == "failed":
                expected_exceptions = rng.randint(1, 2)
            elif sla_met is False:
                expected_exceptions = rng.randint(1, 2)
            elif rng.random() < 0.18:
                expected_exceptions = 1

            for exception_index in range(expected_exceptions):
                step = rng.choice(workflow["steps"])
                severity = "high" if status == "failed" else rng.choice(SEVERITIES)
                exceptions.append(
                    {
                        "id": f"{workflow['id']}-r{index:03d}-e{exception_index}",
                        "step_id": f"{workflow['id']}-s{step['seq']}",
                        "severity": severity,
                        "description": rng.choice(templates),
                        # Recent exceptions are more likely to still be open.
                        "resolved": status != "in_progress" and rng.random() < (0.55 if index < 2 else 0.9),
                    }
                )

            runs.append(
                {
                    "id": f"{workflow['id']}-r{index:03d}",
                    "workflow_id": workflow["id"],
                    "period": _period_label(started, workflow["frequency"]),
                    "started_at": started.replace(microsecond=0).isoformat(),
                    "completed_at": completed_at.replace(microsecond=0).isoformat() if completed_at else None,
                    "status": status,
                    "duration_hours": round(duration, 2) if status != "in_progress" else None,
                    "sla_met": sla_met,
                    "exceptions": exceptions,
                }
            )

    runs.sort(key=lambda run: run["started_at"], reverse=True)
    return runs


def build_dataset() -> dict:
    rng = random.Random(SEED)

    workflows = []
    for workflow in WORKFLOWS:
        steps = []
        for step in workflow["steps"]:
            steps.append({"id": f"{workflow['id']}-s{step['seq']}", **step})
        # Derive the system and data-object rollups from the steps so the
        # workflow header can never drift from what the steps actually declare.
        step_systems = {system for step in steps for system in step["system_ids"]}
        step_objects = {
            obj
            for step in steps
            for obj in step["input_object_ids"] + step["output_object_ids"]
        }
        workflows.append(
            {
                **workflow,
                "steps": steps,
                "system_ids": sorted(step_systems | set(workflow["system_ids"])),
                "data_object_ids": sorted(step_objects),
                "step_count": len(steps),
                "planned_hours": round(_planned_hours(workflow), 2),
            }
        )

    return {
        "generated_at": TODAY.replace(microsecond=0).isoformat(),
        "as_of": TODAY.date().isoformat(),
        "domains": DOMAINS,
        "owners": OWNERS,
        "systems": SYSTEMS,
        "data_objects": DATA_OBJECTS,
        "workflows": workflows,
        "runs": generate_runs(rng),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "workflows.json",
        help="Destination path for the generated dataset.",
    )
    args = parser.parse_args()

    dataset = build_dataset()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")

    print(
        f"Wrote {args.out} "
        f"({len(dataset['workflows'])} workflows, "
        f"{sum(w['step_count'] for w in dataset['workflows'])} steps, "
        f"{len(dataset['runs'])} runs)"
    )


if __name__ == "__main__":
    main()
