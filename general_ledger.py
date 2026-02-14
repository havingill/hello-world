"""
General Ledger — AASB-compliant basic accounting system.

Implements double-entry bookkeeping aligned with:
  - AASB 101  Presentation of Financial Statements
  - AASB 108  Accounting Policies, Changes in Estimates and Errors
  - AASB Framework (accrual basis, going concern)

Usage:
    python general_ledger.py
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from io import StringIO
from typing import Optional


# ---------------------------------------------------------------------------
# AASB 101 – Account classifications
# ---------------------------------------------------------------------------

class AccountType(Enum):
    """AASB 101 requires these minimum line-item classifications."""
    # Statement of Financial Position (Balance Sheet)
    CURRENT_ASSET = "Current Asset"
    NON_CURRENT_ASSET = "Non-Current Asset"
    CURRENT_LIABILITY = "Current Liability"
    NON_CURRENT_LIABILITY = "Non-Current Liability"
    EQUITY = "Equity"
    # Statement of Profit or Loss
    REVENUE = "Revenue"
    COST_OF_SALES = "Cost of Sales"
    EXPENSE = "Expense"
    OTHER_INCOME = "Other Income"


# Normal balance rules per AASB framework (debit-positive / credit-positive)
DEBIT_NORMAL: set[AccountType] = {
    AccountType.CURRENT_ASSET,
    AccountType.NON_CURRENT_ASSET,
    AccountType.COST_OF_SALES,
    AccountType.EXPENSE,
}
CREDIT_NORMAL: set[AccountType] = {
    AccountType.CURRENT_LIABILITY,
    AccountType.NON_CURRENT_LIABILITY,
    AccountType.EQUITY,
    AccountType.REVENUE,
    AccountType.OTHER_INCOME,
}


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@dataclass
class Account:
    """A single account in the Chart of Accounts."""
    code: str          # e.g. "1-1000"
    name: str          # e.g. "Cash at Bank"
    account_type: AccountType
    description: str = ""
    is_active: bool = True

    @property
    def normal_balance(self) -> str:
        return "debit" if self.account_type in DEBIT_NORMAL else "credit"


# ---------------------------------------------------------------------------
# Chart of Accounts  (AASB 101 structure)
# ---------------------------------------------------------------------------

class ChartOfAccounts:
    """
    Manages the full set of accounts.

    Default accounts follow the AASB 101 minimum presentation requirements
    for a general-purpose financial statement.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}

    # -- mutators -----------------------------------------------------------

    def add_account(self, account: Account) -> None:
        if account.code in self._accounts:
            raise ValueError(f"Account code '{account.code}' already exists.")
        self._accounts[account.code] = account

    def deactivate_account(self, code: str) -> None:
        self._get(code).is_active = False

    # -- queries ------------------------------------------------------------

    def get(self, code: str) -> Account:
        return self._get(code)

    def list_accounts(self, active_only: bool = True) -> list[Account]:
        accounts = self._accounts.values()
        if active_only:
            accounts = [a for a in accounts if a.is_active]
        return sorted(accounts, key=lambda a: a.code)

    # -- internals ----------------------------------------------------------

    def _get(self, code: str) -> Account:
        try:
            return self._accounts[code]
        except KeyError:
            raise KeyError(f"No account with code '{code}'.") from None


# ---------------------------------------------------------------------------
# Journal Entry line & entry
# ---------------------------------------------------------------------------

@dataclass
class JournalLine:
    """One leg of a journal entry (either a debit or a credit)."""
    account_code: str
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.debit < 0 or self.credit < 0:
            raise ValueError("Debit and credit amounts must be non-negative.")
        if self.debit > 0 and self.credit > 0:
            raise ValueError("A journal line cannot have both a debit and a credit.")
        if self.debit == 0 and self.credit == 0:
            raise ValueError("A journal line must have either a debit or a credit.")


@dataclass
class JournalEntry:
    """
    A complete journal entry enforcing double-entry bookkeeping.

    AASB Framework requires that every transaction is recorded with
    equal debits and credits (the duality principle).
    """
    entry_id: int
    entry_date: date
    description: str
    lines: list[JournalLine]
    reference: str = ""
    is_posted: bool = False
    is_reversed: bool = False
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if len(self.lines) < 2:
            raise ValueError("A journal entry must have at least two lines.")
        total_debits = sum(l.debit for l in self.lines)
        total_credits = sum(l.credit for l in self.lines)
        if total_debits != total_credits:
            raise ValueError(
                f"Debits ({total_debits}) and credits ({total_credits}) must be equal."
            )

    @property
    def total(self) -> Decimal:
        return sum(l.debit for l in self.lines)


# ---------------------------------------------------------------------------
# General Ledger
# ---------------------------------------------------------------------------

class GeneralLedger:
    """
    Core ledger that ties together the Chart of Accounts and Journal Entries.

    Supports:
      - Creating and posting journal entries
      - Reversing entries (AASB 108 error correction)
      - Trial balance generation
      - Basic financial statements per AASB 101
      - CSV / JSON export
    """

    def __init__(self, coa: Optional[ChartOfAccounts] = None) -> None:
        self.coa = coa or ChartOfAccounts()
        self._entries: list[JournalEntry] = []
        self._next_id: int = 1
        self.reporting_period_start: date = date(date.today().year, 7, 1)
        self.reporting_period_end: date = date(date.today().year + 1, 6, 30)

    # -- journal entries ----------------------------------------------------

    def create_entry(
        self,
        entry_date: date,
        description: str,
        lines: list[JournalLine],
        reference: str = "",
    ) -> JournalEntry:
        """Create a journal entry. Validates accounts exist and are active."""
        for line in lines:
            acct = self.coa.get(line.account_code)
            if not acct.is_active:
                raise ValueError(f"Account '{acct.code}' is inactive.")

        entry = JournalEntry(
            entry_id=self._next_id,
            entry_date=entry_date,
            description=description,
            lines=lines,
            reference=reference,
        )
        self._entries.append(entry)
        self._next_id += 1
        return entry

    def post_entry(self, entry_id: int) -> None:
        entry = self._find_entry(entry_id)
        if entry.is_posted:
            raise ValueError(f"Entry {entry_id} is already posted.")
        entry.is_posted = True

    def reverse_entry(self, entry_id: int, reversal_date: date) -> JournalEntry:
        """
        AASB 108 – correction of errors via reversal.

        Creates a new entry with debits and credits swapped.
        """
        original = self._find_entry(entry_id)
        if not original.is_posted:
            raise ValueError("Cannot reverse an unposted entry.")
        if original.is_reversed:
            raise ValueError(f"Entry {entry_id} has already been reversed.")

        reversed_lines = []
        for line in original.lines:
            reversed_lines.append(
                JournalLine(
                    account_code=line.account_code,
                    debit=line.credit,
                    credit=line.debit,
                )
            )

        reversal = self.create_entry(
            entry_date=reversal_date,
            description=f"Reversal of entry #{original.entry_id}: {original.description}",
            lines=reversed_lines,
            reference=f"REV-{original.entry_id}",
        )
        reversal.is_posted = True
        original.is_reversed = True
        return reversal

    # -- balances -----------------------------------------------------------

    def account_balance(self, code: str) -> Decimal:
        """Return the current balance for a single account (posted entries only)."""
        acct = self.coa.get(code)
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        for entry in self._entries:
            if not entry.is_posted:
                continue
            for line in entry.lines:
                if line.account_code == code:
                    total_debit += line.debit
                    total_credit += line.credit

        if acct.account_type in DEBIT_NORMAL:
            return (total_debit - total_credit).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return (total_credit - total_debit).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def trial_balance(self) -> list[dict]:
        """
        Generate a trial balance from all posted entries.

        Returns a list of dicts: {code, name, debit, credit}.
        AASB 101 requires that the trial balance balances (total debits == total credits).
        """
        rows: list[dict] = []
        total_dr = Decimal("0.00")
        total_cr = Decimal("0.00")

        for acct in self.coa.list_accounts():
            bal = self.account_balance(acct.code)
            dr = bal if acct.account_type in DEBIT_NORMAL and bal > 0 else Decimal("0.00")
            cr = bal if acct.account_type in CREDIT_NORMAL and bal > 0 else Decimal("0.00")
            # Handle contra balances
            if acct.account_type in DEBIT_NORMAL and bal < 0:
                cr = abs(bal)
            if acct.account_type in CREDIT_NORMAL and bal < 0:
                dr = abs(bal)

            if dr or cr:
                rows.append({
                    "code": acct.code,
                    "name": acct.name,
                    "debit": dr,
                    "credit": cr,
                })
                total_dr += dr
                total_cr += cr

        rows.append({
            "code": "",
            "name": "TOTAL",
            "debit": total_dr,
            "credit": total_cr,
        })
        return rows

    # -- AASB 101 financial statements --------------------------------------

    def income_statement(self) -> dict:
        """
        Statement of Profit or Loss (AASB 101 §81A–105).

        Returns revenue, cost of sales, gross profit, expenses, other income,
        and net profit/loss.
        """
        revenue = Decimal("0.00")
        cost_of_sales = Decimal("0.00")
        expenses = Decimal("0.00")
        other_income = Decimal("0.00")

        for acct in self.coa.list_accounts():
            bal = self.account_balance(acct.code)
            if acct.account_type == AccountType.REVENUE:
                revenue += bal
            elif acct.account_type == AccountType.COST_OF_SALES:
                cost_of_sales += bal
            elif acct.account_type == AccountType.EXPENSE:
                expenses += bal
            elif acct.account_type == AccountType.OTHER_INCOME:
                other_income += bal

        gross_profit = revenue - cost_of_sales
        net_profit = gross_profit - expenses + other_income

        return {
            "revenue": revenue,
            "cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit,
            "other_income": other_income,
            "expenses": expenses,
            "net_profit": net_profit,
        }

    def balance_sheet(self) -> dict:
        """
        Statement of Financial Position (AASB 101 §54–80A).

        Returns current/non-current assets, liabilities, equity, and
        verifies the accounting equation: Assets = Liabilities + Equity.
        """
        current_assets = Decimal("0.00")
        non_current_assets = Decimal("0.00")
        current_liabilities = Decimal("0.00")
        non_current_liabilities = Decimal("0.00")
        equity = Decimal("0.00")

        for acct in self.coa.list_accounts():
            bal = self.account_balance(acct.code)
            if acct.account_type == AccountType.CURRENT_ASSET:
                current_assets += bal
            elif acct.account_type == AccountType.NON_CURRENT_ASSET:
                non_current_assets += bal
            elif acct.account_type == AccountType.CURRENT_LIABILITY:
                current_liabilities += bal
            elif acct.account_type == AccountType.NON_CURRENT_LIABILITY:
                non_current_liabilities += bal
            elif acct.account_type == AccountType.EQUITY:
                equity += bal

        # Retained earnings = net profit for the period
        net_profit = self.income_statement()["net_profit"]

        total_assets = current_assets + non_current_assets
        total_liabilities = current_liabilities + non_current_liabilities
        total_equity = equity + net_profit

        return {
            "current_assets": current_assets,
            "non_current_assets": non_current_assets,
            "total_assets": total_assets,
            "current_liabilities": current_liabilities,
            "non_current_liabilities": non_current_liabilities,
            "total_liabilities": total_liabilities,
            "equity": equity,
            "retained_earnings": net_profit,
            "total_equity": total_equity,
            "total_liabilities_and_equity": total_liabilities + total_equity,
            "balanced": total_assets == total_liabilities + total_equity,
        }

    # -- export -------------------------------------------------------------

    def export_trial_balance_csv(self) -> str:
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Code", "Account Name", "Debit", "Credit"])
        for row in self.trial_balance():
            writer.writerow([row["code"], row["name"], row["debit"], row["credit"]])
        return buf.getvalue()

    def export_journal_json(self) -> str:
        entries = []
        for e in self._entries:
            entries.append({
                "entry_id": e.entry_id,
                "date": e.entry_date.isoformat(),
                "description": e.description,
                "reference": e.reference,
                "is_posted": e.is_posted,
                "is_reversed": e.is_reversed,
                "lines": [
                    {
                        "account_code": l.account_code,
                        "debit": str(l.debit),
                        "credit": str(l.credit),
                    }
                    for l in e.lines
                ],
            })
        return json.dumps(entries, indent=2)

    # -- internals ----------------------------------------------------------

    def _find_entry(self, entry_id: int) -> JournalEntry:
        for e in self._entries:
            if e.entry_id == entry_id:
                return e
        raise KeyError(f"No journal entry with id {entry_id}.")


# ---------------------------------------------------------------------------
# Default Chart of Accounts (AASB 101 compliant)
# ---------------------------------------------------------------------------

def create_default_coa() -> ChartOfAccounts:
    """Seed a chart of accounts with standard AASB 101 classifications."""
    coa = ChartOfAccounts()
    defaults = [
        # Current Assets
        Account("1-1000", "Cash at Bank", AccountType.CURRENT_ASSET),
        Account("1-1010", "Petty Cash", AccountType.CURRENT_ASSET),
        Account("1-1100", "Accounts Receivable", AccountType.CURRENT_ASSET),
        Account("1-1200", "Inventory", AccountType.CURRENT_ASSET),
        Account("1-1300", "Prepaid Expenses", AccountType.CURRENT_ASSET),
        Account("1-1400", "GST Receivable", AccountType.CURRENT_ASSET),
        # Non-Current Assets
        Account("1-2000", "Property, Plant & Equipment", AccountType.NON_CURRENT_ASSET),
        Account("1-2010", "Accumulated Depreciation", AccountType.NON_CURRENT_ASSET),
        Account("1-2100", "Intangible Assets", AccountType.NON_CURRENT_ASSET),
        # Current Liabilities
        Account("2-1000", "Accounts Payable", AccountType.CURRENT_LIABILITY),
        Account("2-1100", "GST Payable", AccountType.CURRENT_LIABILITY),
        Account("2-1200", "PAYG Withholding Payable", AccountType.CURRENT_LIABILITY),
        Account("2-1300", "Superannuation Payable", AccountType.CURRENT_LIABILITY),
        Account("2-1400", "Accrued Expenses", AccountType.CURRENT_LIABILITY),
        Account("2-1500", "Income Tax Payable", AccountType.CURRENT_LIABILITY),
        # Non-Current Liabilities
        Account("2-2000", "Bank Loan", AccountType.NON_CURRENT_LIABILITY),
        Account("2-2100", "Lease Liability", AccountType.NON_CURRENT_LIABILITY),
        # Equity
        Account("3-1000", "Owner's Equity", AccountType.EQUITY),
        Account("3-1100", "Retained Earnings", AccountType.EQUITY),
        Account("3-1200", "Drawings", AccountType.EQUITY),
        # Revenue
        Account("4-1000", "Sales Revenue", AccountType.REVENUE),
        Account("4-1100", "Service Revenue", AccountType.REVENUE),
        # Other Income
        Account("4-2000", "Interest Income", AccountType.OTHER_INCOME),
        Account("4-2100", "Gain on Disposal of Assets", AccountType.OTHER_INCOME),
        # Cost of Sales
        Account("5-1000", "Cost of Goods Sold", AccountType.COST_OF_SALES),
        # Expenses
        Account("6-1000", "Wages & Salaries", AccountType.EXPENSE),
        Account("6-1100", "Superannuation Expense", AccountType.EXPENSE),
        Account("6-1200", "Rent Expense", AccountType.EXPENSE),
        Account("6-1300", "Depreciation Expense", AccountType.EXPENSE),
        Account("6-1400", "Utilities Expense", AccountType.EXPENSE),
        Account("6-1500", "Insurance Expense", AccountType.EXPENSE),
        Account("6-1600", "Office Supplies", AccountType.EXPENSE),
        Account("6-1700", "Advertising & Marketing", AccountType.EXPENSE),
        Account("6-1800", "Professional Fees", AccountType.EXPENSE),
        Account("6-1900", "Bank Fees & Charges", AccountType.EXPENSE),
        Account("6-2000", "Income Tax Expense", AccountType.EXPENSE),
    ]
    for acct in defaults:
        coa.add_account(acct)
    return coa


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _money(val: Decimal) -> str:
    return f"${val:,.2f}"


def print_trial_balance(ledger: GeneralLedger) -> None:
    rows = ledger.trial_balance()
    print("\n" + "=" * 62)
    print("TRIAL BALANCE")
    print(f"Period: {ledger.reporting_period_start} to {ledger.reporting_period_end}")
    print("=" * 62)
    print(f"{'Code':<10} {'Account':<28} {'Debit':>10} {'Credit':>10}")
    print("-" * 62)
    for row in rows:
        code = row["code"]
        name = row["name"]
        dr = _money(row["debit"]) if row["debit"] else ""
        cr = _money(row["credit"]) if row["credit"] else ""
        if name == "TOTAL":
            print("-" * 62)
        print(f"{code:<10} {name:<28} {dr:>10} {cr:>10}")
    print("=" * 62)


def print_income_statement(ledger: GeneralLedger) -> None:
    stmt = ledger.income_statement()
    print("\n" + "=" * 48)
    print("STATEMENT OF PROFIT OR LOSS (AASB 101)")
    print(f"Period: {ledger.reporting_period_start} to {ledger.reporting_period_end}")
    print("=" * 48)
    print(f"  Revenue                    {_money(stmt['revenue']):>14}")
    print(f"  Cost of Sales              {_money(stmt['cost_of_sales']):>14}")
    print(f"                             {'-' * 14}")
    print(f"  Gross Profit               {_money(stmt['gross_profit']):>14}")
    print(f"  Other Income               {_money(stmt['other_income']):>14}")
    print(f"  Expenses                   {_money(stmt['expenses']):>14}")
    print(f"                             {'=' * 14}")
    print(f"  Net Profit / (Loss)        {_money(stmt['net_profit']):>14}")
    print("=" * 48)


def print_balance_sheet(ledger: GeneralLedger) -> None:
    bs = ledger.balance_sheet()
    print("\n" + "=" * 48)
    print("STATEMENT OF FINANCIAL POSITION (AASB 101)")
    print(f"As at {ledger.reporting_period_end}")
    print("=" * 48)
    print("ASSETS")
    print(f"  Current Assets             {_money(bs['current_assets']):>14}")
    print(f"  Non-Current Assets         {_money(bs['non_current_assets']):>14}")
    print(f"                             {'-' * 14}")
    print(f"  Total Assets               {_money(bs['total_assets']):>14}")
    print()
    print("LIABILITIES")
    print(f"  Current Liabilities        {_money(bs['current_liabilities']):>14}")
    print(f"  Non-Current Liabilities    {_money(bs['non_current_liabilities']):>14}")
    print(f"                             {'-' * 14}")
    print(f"  Total Liabilities          {_money(bs['total_liabilities']):>14}")
    print()
    print("EQUITY")
    print(f"  Equity                     {_money(bs['equity']):>14}")
    print(f"  Retained Earnings          {_money(bs['retained_earnings']):>14}")
    print(f"                             {'-' * 14}")
    print(f"  Total Equity               {_money(bs['total_equity']):>14}")
    print()
    print(f"                             {'=' * 14}")
    print(f"  Liabilities + Equity       {_money(bs['total_liabilities_and_equity']):>14}")
    check = "BALANCED" if bs["balanced"] else "*** UNBALANCED ***"
    print(f"  Accounting Equation:       {check:>14}")
    print("=" * 48)


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

def _read_decimal(prompt: str) -> Decimal:
    while True:
        raw = input(prompt).strip()
        try:
            val = Decimal(raw)
            if val < 0:
                print("  Amount must be non-negative.")
                continue
            return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            print("  Invalid number. Try again.")


def _read_date(prompt: str) -> date:
    while True:
        raw = input(prompt).strip()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("  Invalid date. Use YYYY-MM-DD format.")


def cli() -> None:
    """Run an interactive session."""
    ledger = GeneralLedger(create_default_coa())
    print("=" * 62)
    print("  GENERAL LEDGER — AASB Compliant")
    print("  Double-entry bookkeeping system")
    print("=" * 62)

    while True:
        print("\nMenu:")
        print("  1) List accounts")
        print("  2) Add account")
        print("  3) Create journal entry")
        print("  4) Post journal entry")
        print("  5) Reverse journal entry (AASB 108)")
        print("  6) View account balance")
        print("  7) Trial balance")
        print("  8) Income statement  (AASB 101)")
        print("  9) Balance sheet     (AASB 101)")
        print("  10) Export trial balance (CSV)")
        print("  11) Export journal entries (JSON)")
        print("  12) List journal entries")
        print("  0) Exit")

        choice = input("\nSelect option: ").strip()

        if choice == "1":
            print(f"\n{'Code':<10} {'Name':<30} {'Type':<22} {'Normal'}")
            print("-" * 72)
            for a in ledger.coa.list_accounts():
                print(f"{a.code:<10} {a.name:<30} {a.account_type.value:<22} {a.normal_balance}")

        elif choice == "2":
            code = input("  Account code: ").strip()
            name = input("  Account name: ").strip()
            print("  Account types:")
            types = list(AccountType)
            for i, t in enumerate(types, 1):
                print(f"    {i}) {t.value}")
            idx = int(input("  Select type number: ").strip()) - 1
            acct_type = types[idx]
            desc = input("  Description (optional): ").strip()
            try:
                ledger.coa.add_account(Account(code, name, acct_type, desc))
                print(f"  Account '{code} – {name}' added.")
            except ValueError as e:
                print(f"  Error: {e}")

        elif choice == "3":
            entry_date = _read_date("  Date (YYYY-MM-DD): ")
            desc = input("  Description: ").strip()
            ref = input("  Reference (optional): ").strip()
            lines: list[JournalLine] = []
            print("  Enter lines (blank account code to finish):")
            while True:
                acct_code = input("    Account code: ").strip()
                if not acct_code:
                    break
                dr = _read_decimal("    Debit amount  (0 if none): ")
                cr = _read_decimal("    Credit amount (0 if none): ")
                try:
                    lines.append(JournalLine(acct_code, dr, cr))
                except ValueError as e:
                    print(f"    Error: {e}")
            if lines:
                try:
                    entry = ledger.create_entry(entry_date, desc, lines, ref)
                    print(f"  Journal entry #{entry.entry_id} created (unposted).")
                except (ValueError, KeyError) as e:
                    print(f"  Error: {e}")

        elif choice == "4":
            eid = int(input("  Entry ID to post: ").strip())
            try:
                ledger.post_entry(eid)
                print(f"  Entry #{eid} posted.")
            except (ValueError, KeyError) as e:
                print(f"  Error: {e}")

        elif choice == "5":
            eid = int(input("  Entry ID to reverse: ").strip())
            rev_date = _read_date("  Reversal date (YYYY-MM-DD): ")
            try:
                rev = ledger.reverse_entry(eid, rev_date)
                print(f"  Reversal entry #{rev.entry_id} created and posted.")
            except (ValueError, KeyError) as e:
                print(f"  Error: {e}")

        elif choice == "6":
            code = input("  Account code: ").strip()
            try:
                bal = ledger.account_balance(code)
                acct = ledger.coa.get(code)
                print(f"  {acct.name} ({acct.code}): {_money(bal)}")
            except KeyError as e:
                print(f"  Error: {e}")

        elif choice == "7":
            print_trial_balance(ledger)

        elif choice == "8":
            print_income_statement(ledger)

        elif choice == "9":
            print_balance_sheet(ledger)

        elif choice == "10":
            csv_data = ledger.export_trial_balance_csv()
            filename = input("  Output filename [trial_balance.csv]: ").strip() or "trial_balance.csv"
            with open(filename, "w") as f:
                f.write(csv_data)
            print(f"  Saved to {filename}")

        elif choice == "11":
            json_data = ledger.export_journal_json()
            filename = input("  Output filename [journal.json]: ").strip() or "journal.json"
            with open(filename, "w") as f:
                f.write(json_data)
            print(f"  Saved to {filename}")

        elif choice == "12":
            if not ledger._entries:
                print("  No journal entries.")
            for e in ledger._entries:
                status = []
                if e.is_posted:
                    status.append("posted")
                if e.is_reversed:
                    status.append("reversed")
                status_str = ", ".join(status) if status else "unposted"
                print(f"\n  #{e.entry_id}  {e.entry_date}  {e.description}  [{status_str}]")
                if e.reference:
                    print(f"    Ref: {e.reference}")
                for l in e.lines:
                    dr = _money(l.debit) if l.debit else ""
                    cr = _money(l.credit) if l.credit else ""
                    print(f"    {l.account_code:<10} DR {dr:>10}  CR {cr:>10}")

        elif choice == "0":
            print("Exiting.")
            break

        else:
            print("  Invalid option.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
