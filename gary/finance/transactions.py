"""Transactions, CSV/image import, and cashflow breakdown.

Parses common bank CSV exports (either a signed ``Amount`` column or separate
``Debit``/``Credit`` columns), categorizes each transaction with simple keyword
rules, and summarizes cashflow. Image "snapshots" are supported best-effort via
OCR (Tesseract); CSVs give the most accurate breakdown.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

# description keyword -> category (checked in order)
_CATEGORY_RULES: list[tuple[str, str]] = [
    (r"payroll|salary|direct dep|paycheck|deposit from|ach credit", "Income"),
    (r"interest|dividend", "Income"),
    (r"rent|mortgage|landlord", "Housing"),
    (r"electric|water|gas bill|utility|comcast|internet|verizon|at&t|t-mobile", "Utilities"),
    (r"grocery|supermarket|whole foods|trader joe|safeway|kroger|aldi|costco", "Groceries"),
    (r"restaurant|coffee|starbucks|mcdonald|uber eats|doordash|grubhub|dining", "Dining"),
    (r"uber|lyft|shell|chevron|exxon|gas station|transit|parking|fuel", "Transport"),
    (r"netflix|spotify|hulu|disney|subscription|prime|patreon", "Subscriptions"),
    (r"amazon|target|walmart|store|shop", "Shopping"),
    (r"pharmacy|cvs|walgreens|doctor|medical|dental|clinic|insurance", "Health"),
    (r"transfer|venmo|zelle|paypal|cash app", "Transfers"),
]


@dataclass
class Transaction:
    date: str
    description: str
    amount: float  # positive = money in (income), negative = money out (expense)
    category: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def categorize(description: str, amount: float) -> str:
    desc = (description or "").lower()
    for pattern, category in _CATEGORY_RULES:
        if re.search(pattern, desc):
            if category == "Income" and amount < 0:
                continue  # a refund of a subscription etc. shouldn't be income
            return category
    return "Income" if amount > 0 else "Other"


def parse_amount(raw: str) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.replace("(", "").replace(")", "")
    s = re.sub(r"[^0-9.\-]", "", s)  # strip $, commas, spaces
    if s in ("", "-", ".", "-."):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if negative else val


def _norm_date(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw  # leave as-is if unrecognized


def _cell(row: list[str], i: int | None) -> str:
    return row[i] if i is not None and i < len(row) else ""


def _find(header: list[str], *names: str) -> int | None:
    low = [h.strip().lower() for h in header]
    for name in names:
        for i, h in enumerate(low):
            if name in h:
                return i
    return None


def parse_csv(text: str) -> list[Transaction]:
    """Parse a bank CSV into transactions. Returns [] if it can't be parsed."""
    text = text.lstrip("\ufeff")
    try:
        sample = text[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = list(csv.reader(io.StringIO(text), dialect))
    if not reader:
        return []

    header = reader[0]
    _hdr_re = r"date|desc|amount|debit|credit|memo|payee"
    has_header = any(re.search(_hdr_re, h, re.I) for h in header)
    rows = reader[1:] if has_header else reader

    if has_header:
        di = _find(header, "date")
        desci = _find(header, "description", "memo", "payee", "name", "detail")
        ai = _find(header, "amount")
        debit_i = _find(header, "debit", "withdrawal")
        credit_i = _find(header, "credit", "deposit")
    else:
        di, desci, ai, debit_i, credit_i = 0, 1, 2, None, None

    txns: list[Transaction] = []
    for row in rows:
        if not row or all(not c.strip() for c in row):
            continue

        date = _norm_date(_cell(row, di))
        desc = _cell(row, desci).strip()
        amount: float | None = None
        if ai is not None:
            amount = parse_amount(_cell(row, ai))
        elif debit_i is not None or credit_i is not None:
            debit = parse_amount(_cell(row, debit_i))
            credit = parse_amount(_cell(row, credit_i))
            if credit:
                amount = abs(credit)
            elif debit:
                amount = -abs(debit)
        if amount is None:
            continue
        txns.append(Transaction(date=date, description=desc,
                                amount=round(amount, 2), category=categorize(desc, amount)))
    return txns


def dedupe(existing: list[Transaction], incoming: list[Transaction]) -> list[Transaction]:
    seen = {(t.date, t.description, t.amount) for t in existing}
    merged = list(existing)
    for t in incoming:
        key = (t.date, t.description, t.amount)
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return merged


def _months_span(txns: list[Transaction]) -> int:
    months = {t.date[:7] for t in txns if len(t.date) >= 7 and t.date[4] == "-"}
    return max(1, len(months))


def cashflow_summary(txns: list[Transaction]) -> dict[str, Any]:
    income = round(sum(t.amount for t in txns if t.amount > 0), 2)
    expenses = round(-sum(t.amount for t in txns if t.amount < 0), 2)
    months = _months_span(txns)

    by_category: dict[str, float] = defaultdict(float)
    by_source: dict[str, float] = defaultdict(float)
    by_month: dict[str, float] = defaultdict(float)
    for t in txns:
        by_month[t.date[:7]] += t.amount
        if t.amount < 0:
            by_category[t.category] += -t.amount
        else:
            by_source[t.description or "Income"] += t.amount

    top_expenses = sorted(({"category": k, "amount": round(v, 2)}
                           for k, v in by_category.items()), key=lambda x: -x["amount"])
    top_income = sorted(({"source": k, "amount": round(v, 2)}
                         for k, v in by_source.items()), key=lambda x: -x["amount"])[:6]

    return {
        "transaction_count": len(txns),
        "months": months,
        "total_income": income,
        "total_expenses": expenses,
        "net_cashflow": round(income - expenses, 2),
        "avg_monthly_income": round(income / months, 2),
        "avg_monthly_expenses": round(expenses / months, 2),
        "avg_monthly_net": round((income - expenses) / months, 2),
        "expenses_by_category": top_expenses,
        "income_by_source": top_income,
        "by_month": [{"month": k, "net": round(v, 2)} for k, v in sorted(by_month.items())],
    }


def ocr_import(image_bytes: bytes) -> list[Transaction]:
    """Best-effort: OCR an image snapshot and extract date+amount lines.

    Less reliable than CSV; used for bank/statement screenshots.
    """
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
    except Exception:
        return []

    txns: list[Transaction] = []
    date_re = re.compile(r"(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})")
    amt_re = re.compile(r"-?\(?\$?\s?\d[\d,]*\.\d{2}\)?")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        amt_match = list(amt_re.finditer(line))
        if not amt_match:
            continue
        amount = parse_amount(amt_match[-1].group())
        if amount is None:
            continue
        date_match = date_re.search(line)
        date = _norm_date(date_match.group()) if date_match else ""
        desc = amt_re.sub("", date_re.sub("", line)).strip(" -\t")
        txns.append(Transaction(date=date, description=desc or "OCR item",
                                amount=round(amount, 2), category=categorize(desc, amount)))
    return txns
