"""
Extract structured data from Xero PDF reports and run deterministic checks.

Usage:
    python extract_reports.py <folder_or_files...> --out findings.json

Accepts either:
  - One or more PDF paths
  - A single folder containing the 5 reports
File-type detection is content-based (filename optional).

Output: JSON with extracted data + automatic_checks. Designed to be read by
Claude as the input to a qualitative review.
"""

from __future__ import annotations
import argparse, json, re, sys
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pdfplumber


# ----- helpers ---------------------------------------------------------------

NUM_RE = re.compile(r"^\(?-?[\d,]+\.\d{2}\)?$")


def to_decimal(s: str) -> Optional[Decimal]:
    """Convert a Xero-formatted number string to Decimal. Returns None if not a number.
    '1,234.56' -> 1234.56;  '(75.00)' -> -75.00;  '-' or '' -> None."""
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if t in ("", "-", "—", "–"):
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg = True
        t = t[1:-1]
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    v = Decimal(t)
    if neg:
        v = -v
    return v


def d2f(v):
    """Decimal -> float for JSON. None passes through."""
    return float(v) if isinstance(v, Decimal) else v


def extract_text_lines(pdf_path: Path) -> list[str]:
    """Extract text lines with proper spacing reconstructed from word positions.
    Xero PDFs collapse spaces in extract_text(); going via extract_words() with
    a tight tolerance restores the original word boundaries."""
    lines: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1, use_text_flow=False)
            if not words:
                continue
            rows: dict[int, list[dict]] = {}
            for w in words:
                key = round(w["top"] / 4) * 4
                rows.setdefault(key, []).append(w)
            for y in sorted(rows.keys()):
                row_words = sorted(rows[y], key=lambda w: w["x0"])
                lines.append(" ".join(w["text"] for w in row_words))
    return lines


# ----- report classification -------------------------------------------------

def classify_report(lines: list[str]) -> str:
    head = "\n".join(lines[:6]).lower()
    if "balance sheet" in head:
        return "balance_sheet"
    if "profit and loss" in head or "profit & loss" in head:
        return "profit_loss"
    if "aged receivables" in head:
        return "aged_receivables"
    if "aged payables" in head:
        return "aged_payables"
    if "account transactions" in head:
        return "account_transactions"
    return "unknown"


# ----- balance sheet & p&l ---------------------------------------------------

def parse_two_column_report(lines: list[str]) -> dict:
    """Parse Balance Sheet or P&L: account name + trailing number, with section headers.
    Returns {sections: {section_name: {accounts: [(name, val)], total: val}}, totals: {...}}."""
    sections: dict[str, dict] = {}
    totals: dict[str, Decimal] = {}
    current_section = None

    KNOWN_SECTIONS = {
        "Assets", "Bank", "Current Assets", "Fixed Assets", "Non-Current Assets",
        "Liabilities", "Current Liabilities", "Non-Current Liabilities",
        "Equity",
        "Trading Income", "Income", "Cost of Sales", "Gross Profit",
        "Operating Expenses", "Other Income", "Other Expenses",
    }
    KNOWN_TOTAL_PREFIXES = (
        "Total Bank", "Total Current Assets", "Total Fixed Assets",
        "Total Non-Current Assets",
        "Total Assets",
        "Total Current Liabilities", "Total Non-Current Liabilities",
        "Total Liabilities",
        "Net Assets",
        "Total Equity",
        "Total Trading Income", "Total Income", "Total Cost of Sales",
        "Gross Profit",
        "Total Operating Expenses", "Total Other Income", "Total Other Expenses",
        "Net Profit", "Net Loss",
    )
    NUM_AT_END = re.compile(r"(\(?-?[\d,]+\.\d{2}\)?)\s*$")
    LINE_IS_JUST_NUMBER = re.compile(r"^\(?-?[\d,]+\.\d{2}\)?$")

    # Pre-pass: merge cases where a known label appears alone on a line and the next
    # non-blank line is just a number.
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        no_num = NUM_AT_END.search(line) is None
        is_known_label = (line in KNOWN_SECTIONS) or any(
            line.lower() == p.lower() or line.lower().startswith(p.lower() + " ")
            for p in KNOWN_TOTAL_PREFIXES
        )
        if no_num and is_known_label and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if LINE_IS_JUST_NUMBER.match(nxt):
                merged.append(f"{line} {nxt}")
                i += 2
                continue
        merged.append(line)
        i += 1

    for raw in merged:
        line = raw.strip()
        if not line:
            continue
        m = NUM_AT_END.search(line)
        if not m:
            if line in KNOWN_SECTIONS:
                current_section = line
                sections.setdefault(current_section, {"accounts": [], "total": None})
            continue
        num = to_decimal(m.group(1))
        name = line[: m.start()].strip()
        if not name:
            continue

        # Total / summary lines
        matched_total = None
        for prefix in KNOWN_TOTAL_PREFIXES:
            if name.lower() == prefix.lower() or name.lower().startswith(prefix.lower() + " "):
                matched_total = prefix
                break
        if matched_total:
            totals[matched_total] = num
            if matched_total.startswith("Total ") and current_section:
                trimmed = matched_total[len("Total "):]
                if current_section in sections and trimmed.lower() == current_section.lower():
                    sections[current_section]["total"] = num
            continue

        if name in KNOWN_SECTIONS:
            current_section = name
            sections.setdefault(current_section, {"accounts": [], "total": None})
            continue

        if current_section is None:
            current_section = "_unsectioned"
            sections.setdefault(current_section, {"accounts": [], "total": None})
        sections[current_section]["accounts"].append({"name": name, "value": d2f(num)})

    return {
        "sections": {
            sec: {"accounts": data["accounts"], "total": d2f(data["total"])}
            for sec, data in sections.items()
        },
        "totals": {k: d2f(v) for k, v in totals.items()},
    }


# ----- aged reports ----------------------------------------------------------

def parse_aged_report(lines: list[str]) -> dict:
    """Aged Receivables/Payables Summary: extract the Total row with bucket breakdown.
    Buckets have '-' as placeholder for zero."""
    out = {"contacts": [], "total": None, "buckets": {}}
    bucket_names = ["current", "lt_1_month", "1_month", "2_months", "3_months", "older", "total"]

    for raw in lines:
        line = raw.strip()
        low = line.lower()
        # The Total row sits after the contact rows. Some files have "Total" and others
        # "Total Aged Receivables" / "Total Aged Payables" — accept any of those.
        if low.startswith("total ") and "percentage" not in low \
                and not low.startswith("total aged receivables s") \
                and not low.startswith("total aged payables s"):
            # Skip the report-title bottom line "Aged Receivables Summary Demo Co... Page X"
            if "summary" in low or "page " in low:
                continue
            tokens = line.split()
            # Pull off trailing tokens that are either a number or a dash placeholder
            tail: list[Optional[Decimal]] = []
            i = len(tokens) - 1
            while i > 0 and len(tail) < 7:
                tok = tokens[i]
                if tok in ("-", "—", "–"):
                    tail.insert(0, Decimal(0))
                    i -= 1
                    continue
                v = to_decimal(tok)
                if v is None:
                    break
                tail.insert(0, v)
                i -= 1
            if len(tail) >= 7:
                values = tail[-7:]
                for name, v in zip(bucket_names, values):
                    out["buckets"][name] = d2f(v)
                out["total"] = d2f(values[-1])
                # Don't break — a "Total Aged Receivables" sub-total may come first;
                # accept the latest valid Total row found.
    return out


# ----- account transactions --------------------------------------------------

@dataclass
class Txn:
    account: str
    date: str
    source: str
    description: str
    reference: str
    debit: Optional[float]
    credit: Optional[float]
    running_balance: Optional[float]
    gross: Optional[float]
    gst: Optional[float]


DATE_RE = re.compile(r"^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\s+", re.I)


# Column anchors found by inspecting Xero "Account Transactions" PDF header positions.
# Words are assigned to the column whose anchor is closest. Numbers are right-aligned
# so we use a generous match window.
TXN_COLUMNS = [
    ("date", 56),
    ("source", 116),
    ("description", 241),
    ("reference", 367),
    ("debit", 540),
    ("credit", 600),
    ("running_balance", 655),
    ("gross", 715),
    ("gst", 785),
]
NUMERIC_COLS = {"debit", "credit", "running_balance", "gross", "gst"}
COMPACT_DATE_RE = re.compile(r"^\d{1,2}(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\d{4}$", re.I)
SPACED_DATE_RE = DATE_RE  # alias for the original


def _expand_compact(token: str) -> str:
    """Reinsert spaces in tokens like '25Jan2026' -> '25 Jan 2026',
    'PayableCreditNote' -> 'Payable Credit Note', 'MelroseParking' -> 'Melrose Parking'."""
    # Date
    m = re.match(r"^(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{4})$", token, re.I)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    # CamelCase / boundary between lowercase->uppercase or letter->digit
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", s)
    return s


def _assign_to_column(x0: float) -> str:
    return min(TXN_COLUMNS, key=lambda c: abs(c[1] - x0))[0]


def parse_account_transactions(pdf_path: Path) -> list[dict]:
    """Parse by clustering pdfplumber.extract_words() into rows by y-coordinate,
    then assigning each word to the nearest column anchor."""
    txns: list[Txn] = []
    current_account: str | None = None

    SKIP_PREFIXES = ("Total ", "Closing Balance", "Opening Balance")
    PAGE_CHROME = ("Account Transactions", "AccountTransactions",
                   "Demo Company", "DemoCompany", "Page ", "DATE", "REFERENCE")

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1, use_text_flow=False)
            if not words:
                continue
            # Cluster into rows by y. Words on the same visual line have very close 'top'.
            rows: dict[int, list[dict]] = {}
            for w in words:
                key = round(w["top"] / 4) * 4  # 4pt bucket
                rows.setdefault(key, []).append(w)

            for y in sorted(rows.keys()):
                line_words = sorted(rows[y], key=lambda w: w["x0"])
                if not line_words:
                    continue
                texts = [w["text"] for w in line_words]
                joined = " ".join(texts)

                # Skip page chrome and report headers
                if any(joined.startswith(p) for p in PAGE_CHROME):
                    continue
                if joined.startswith(SKIP_PREFIXES):
                    continue
                # Standalone "BALANCE", "RUNNING" etc.
                if joined.upper() in ("BALANCE", "RUNNING"):
                    continue

                # Account heading: only one or two words clustered at the left margin (x<200),
                # and no numeric columns. e.g. "AccountsPayable", "Wages and Salaries".
                left_only = all(w["x0"] < 220 for w in line_words)
                has_number = any(re.match(r"^\(?-?[\d,]+\.\d{2}\)?$", w["text"]) for w in line_words)
                if left_only and not has_number and not COMPACT_DATE_RE.match(line_words[0]["text"]) \
                   and not SPACED_DATE_RE.match(joined):
                    expanded = _expand_compact(joined)
                    current_account = expanded.strip()
                    continue

                # Transaction row: first token must look like a date
                first = line_words[0]["text"]
                if not (COMPACT_DATE_RE.match(first) or SPACED_DATE_RE.match(joined)):
                    continue

                # Bucket each word into its column
                buckets: dict[str, list[str]] = {col: [] for col, _ in TXN_COLUMNS}
                for w in line_words:
                    col = _assign_to_column(w["x0"])
                    buckets[col].append(w["text"])

                def cell(col: str) -> str:
                    return " ".join(buckets[col]).strip()

                # Expand compact text in non-numeric cells
                date_text = _expand_compact(cell("date"))
                source_text = _expand_compact(cell("source"))
                desc_text = _expand_compact(cell("description"))
                ref_text = _expand_compact(cell("reference"))

                # Numeric cells: each may contain "-" or a number; if multiple tokens were
                # bucketed (e.g., due to anchor drift), prefer the numeric-looking one.
                def numeric_cell(col: str) -> Optional[Decimal]:
                    for tok in buckets[col]:
                        v = to_decimal(tok)
                        if v is not None:
                            return v
                    # explicit dash means zero/empty
                    if any(tok in ("-", "—", "–") for tok in buckets[col]):
                        return None
                    return None

                txns.append(Txn(
                    account=current_account or "",
                    date=date_text,
                    source=source_text,
                    description=desc_text,
                    reference=ref_text,
                    debit=d2f(numeric_cell("debit")),
                    credit=d2f(numeric_cell("credit")),
                    running_balance=d2f(numeric_cell("running_balance")),
                    gross=d2f(numeric_cell("gross")),
                    gst=d2f(numeric_cell("gst")),
                ))

    return [asdict(t) for t in txns]


def _parse_account_transactions_from_text(pdf_path: Path) -> list[Txn]:
    """Deprecated — kept as a placeholder; the word-based parser handles all cases."""
    return []


# ----- automatic checks ------------------------------------------------------

def _account_lookup(bs_or_pl: dict, name_substring: str) -> Optional[float]:
    name_low = name_substring.lower()
    for sec_data in bs_or_pl["sections"].values():
        for acc in sec_data["accounts"]:
            if name_low in acc["name"].lower():
                return acc["value"]
    return None


def _section_value(bs: dict, section: str) -> Optional[float]:
    sec = bs["sections"].get(section)
    return sec["total"] if sec else None


# Accounts in Australia where GST-free coding is suspicious (commercial supply expected)
GST_EXPECTED_ACCOUNTS = {
    "advertising", "consulting & accounting", "office expenses", "rent",
    "telephone & internet", "light, power, heating", "motor vehicle expenses",
    "general expenses", "cleaning", "printing & stationery", "travel - national",
    "entertainment", "subscriptions", "repairs and maintenance",
}
# Accounts that are typically GST-free (true negatives we don't flag)
GST_FREE_ACCOUNTS = {
    "bank fees", "wages and salaries", "superannuation", "interest expense",
    "interest income", "depreciation", "amortisation", "donations",
    "directors' fees", "payg withholdings payable", "gst",
}
# Suspense / clearing accounts that should not carry a balance
SUSPENSE_NAMES = (
    "historical adjustment", "suspense", "tracking transfers", "unidentified",
    "rounding", "clearing", "uncoded", "unallocated",
)


def run_checks(data: dict) -> dict:
    findings: list[dict] = []
    bs = data.get("balance_sheet")
    pl = data.get("profit_loss")
    ar = data.get("aged_receivables") or {}
    ap = data.get("aged_payables") or {}
    txns = data.get("transactions") or []

    # --- Tie-out: Aged AR vs B/S Accounts Receivable ---
    if bs and ar.get("total") is not None:
        bs_ar = _account_lookup(bs, "Accounts Receivable")
        if bs_ar is not None:
            diff = round(bs_ar - ar["total"], 2)
            findings.append({
                "check": "tie_out_accounts_receivable",
                "severity": "info" if abs(diff) < 0.01 else "high",
                "balance_sheet": bs_ar,
                "aged_report_total": ar["total"],
                "difference": diff,
                "passed": abs(diff) < 0.01,
            })

    # --- Tie-out: Aged AP vs B/S Accounts Payable ---
    if bs and ap.get("total") is not None:
        bs_ap = _account_lookup(bs, "Accounts Payable")
        if bs_ap is not None:
            diff = round(bs_ap - ap["total"], 2)
            findings.append({
                "check": "tie_out_accounts_payable",
                "severity": "info" if abs(diff) < 0.01 else "high",
                "balance_sheet": bs_ap,
                "aged_report_total": ap["total"],
                "difference": diff,
                "passed": abs(diff) < 0.01,
            })

    # --- Negative net fixed assets / sub-zero asset categories ---
    if bs:
        for sec_name, sec in bs["sections"].items():
            if sec_name in ("Fixed Assets", "Non-Current Assets") and sec.get("total") is not None:
                if sec["total"] < 0:
                    findings.append({
                        "check": "negative_fixed_assets",
                        "severity": "high",
                        "section": sec_name,
                        "total": sec["total"],
                        "note": "Net of cost less accumulated depreciation is negative — accumulated depreciation has exceeded asset cost.",
                    })

    # --- Suspense / clearing accounts with a non-zero balance ---
    if bs:
        for sec in bs["sections"].values():
            for acc in sec["accounts"]:
                low = acc["name"].lower()
                if any(s in low for s in SUSPENSE_NAMES):
                    val = acc["value"] or 0
                    if abs(val) >= 0.01:
                        sev = "high" if abs(val) >= 1000 else ("medium" if abs(val) >= 50 else "low")
                        findings.append({
                            "check": "suspense_or_clearing_balance",
                            "severity": sev,
                            "account": acc["name"],
                            "value": val,
                            "note": "Suspense, clearing, or conversion accounts should not carry a balance — should be reviewed and cleared.",
                        })

    # --- Bank account classified as a liability ---
    if bs:
        liab = bs["sections"].get("Current Liabilities")
        if liab:
            for acc in liab["accounts"]:
                low = acc["name"].lower()
                if "bank" in low and "fee" not in low:
                    findings.append({
                        "check": "bank_account_in_liabilities",
                        "severity": "high",
                        "account": acc["name"],
                        "value": acc["value"],
                        "note": "Bank account appears under Current Liabilities. Either overdrawn (Xero may auto-reclassify) or set up under the wrong account type.",
                    })

    # --- Negative net assets ---
    if bs:
        net_assets = bs["totals"].get("Net Assets")
        if net_assets is None:
            # Fallback: derive from totals or look for an account named "Net Assets"
            ta = bs["totals"].get("Total Assets")
            tl = bs["totals"].get("Total Liabilities")
            if ta is not None and tl is not None:
                net_assets = round(ta - tl, 2)
        if net_assets is not None and net_assets < 0:
            findings.append({
                "check": "negative_net_assets",
                "severity": "high",
                "value": net_assets,
                "note": "Liabilities exceed assets — technical insolvency indicator. Confirm with directors.",
            })

    # --- P&L: net loss + wages concentration ---
    if pl:
        revenue = pl["totals"].get("Total Trading Income") or pl["totals"].get("Total Income")
        net = pl["totals"].get("Net Profit") or pl["totals"].get("Net Loss")
        if net is not None and net < 0:
            findings.append({
                "check": "net_loss",
                "severity": "medium",
                "value": net,
                "note": "Operating loss for the period.",
            })
        if revenue and revenue > 0:
            wages = _account_lookup(pl, "Wages and Salaries") or 0
            ratio = wages / revenue
            if ratio > 0.5:
                findings.append({
                    "check": "high_wages_to_revenue",
                    "severity": "medium",
                    "wages": wages,
                    "revenue": revenue,
                    "ratio": round(ratio, 4),
                    "note": "Wages exceed 50% of revenue — labour-cost concentration.",
                })

        # Depreciation expense missing despite accumulated depreciation movement
        if bs:
            accum_dep_present = False
            for sec in bs["sections"].values():
                for acc in sec["accounts"]:
                    if "accumulated depreciation" in acc["name"].lower() and abs(acc["value"] or 0) > 0:
                        accum_dep_present = True
                        break
            dep_expense = _account_lookup(pl, "Depreciation")
            if accum_dep_present and (dep_expense is None or abs(dep_expense) < 0.01):
                findings.append({
                    "check": "depreciation_expense_missing",
                    "severity": "high",
                    "note": "Accumulated depreciation has a balance on the Balance Sheet but no Depreciation expense appears on the P&L. Depreciation journal likely posted incorrectly (wrong debit account).",
                })

    # --- GST math + GST-free coding checks on transactions ---
    gst_math_errors = []
    gst_free_suspects = []
    seen_dates_per_account: dict[str, set[str]] = {}

    for t in txns:
        account_low = (t.get("account") or "").lower()
        gross = t.get("gross")
        gst = t.get("gst")

        # Skip non-amount rows (subtotals, sub-headers)
        if gross is None and gst is None:
            continue

        # If GST is non-zero, gross / 11 should ≈ GST (within 5c)
        if gst not in (None, 0) and gross not in (None, 0):
            implied = abs(gross) / 11.0
            actual = abs(gst)
            if abs(implied - actual) > 0.05:
                gst_math_errors.append({
                    "account": t.get("account"),
                    "date": t.get("date"),
                    "description": t.get("description"),
                    "gross": gross, "gst": gst,
                    "implied_gst_at_10pct": round(implied, 2),
                    "delta": round(actual - implied, 2),
                })

        # Suspect GST-free coding for accounts that usually attract GST
        if account_low in GST_EXPECTED_ACCOUNTS:
            if (gst is None or abs(gst) < 0.005) and gross is not None and abs(gross) >= 5:
                # Skip credit notes that just reverse, where gross is negative (allocations etc.)
                source = (t.get("source") or "").lower()
                if "allocation" in source or "payment" in source:
                    continue
                gst_free_suspects.append({
                    "account": t.get("account"),
                    "date": t.get("date"),
                    "source": t.get("source"),
                    "description": t.get("description"),
                    "reference": t.get("reference"),
                    "gross": gross,
                })

    if gst_math_errors:
        findings.append({
            "check": "gst_math_inconsistent",
            "severity": "medium",
            "count": len(gst_math_errors),
            "examples": gst_math_errors[:10],
            "note": "Transactions where reported GST does not match gross/11 (10% GST). May indicate manual override or non-standard tax rate — verify rate code is correct.",
        })
    if gst_free_suspects:
        findings.append({
            "check": "gst_free_on_taxable_account",
            "severity": "medium",
            "count": len(gst_free_suspects),
            "examples": gst_free_suspects[:15],
            "note": "Transactions in accounts that typically attract GST but were coded GST-free. Review supplier ABN status and tax code.",
        })

    # --- Manual journals with GST (depreciation etc.) ---
    journal_with_gst = []
    for t in txns:
        if (t.get("source") or "").lower().startswith("manual journal"):
            if t.get("gst") not in (None, 0):
                journal_with_gst.append({
                    "account": t.get("account"),
                    "date": t.get("date"),
                    "description": t.get("description"),
                    "reference": t.get("reference"),
                    "gross": t.get("gross"), "gst": t.get("gst"),
                })
    if journal_with_gst:
        findings.append({
            "check": "manual_journal_with_gst",
            "severity": "medium",
            "count": len(journal_with_gst),
            "examples": journal_with_gst[:10],
            "note": "Manual journals usually shouldn't have GST applied (depreciation, accruals, reclasses are GST-excluded). Review tax-rate selection on the journal.",
        })

    return {"findings": findings}


# ----- entry point -----------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="PDFs or a folder containing the 5 reports")
    ap.add_argument("--out", default="findings.json", help="Where to write the JSON output")
    args = ap.parse_args()

    pdfs: list[Path] = []
    for p in args.inputs:
        path = Path(p)
        if path.is_dir():
            pdfs.extend(sorted(path.glob("*.pdf")))
        elif path.suffix.lower() == ".pdf":
            pdfs.append(path)
    if not pdfs:
        print("No PDFs found.", file=sys.stderr)
        return 2

    data: dict = {
        "balance_sheet": None,
        "profit_loss": None,
        "aged_receivables": None,
        "aged_payables": None,
        "transactions": [],
        "files_classified": {},
    }

    for pdf in pdfs:
        lines = extract_text_lines(pdf)
        kind = classify_report(lines)
        data["files_classified"][pdf.name] = kind
        if kind == "balance_sheet":
            data["balance_sheet"] = parse_two_column_report(lines)
        elif kind == "profit_loss":
            data["profit_loss"] = parse_two_column_report(lines)
        elif kind == "aged_receivables":
            data["aged_receivables"] = parse_aged_report(lines)
        elif kind == "aged_payables":
            data["aged_payables"] = parse_aged_report(lines)
        elif kind == "account_transactions":
            data["transactions"] = parse_account_transactions(pdf)

    data["automatic_checks"] = run_checks(data)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {out_path} — {len(data['transactions'])} transactions, "
          f"{len(data['automatic_checks']['findings'])} findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
