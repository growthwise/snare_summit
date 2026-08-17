# Balance Sheet anomaly checks

The script in `scripts/extract_reports.py` runs the deterministic checks below automatically. This file is for the qualitative ones, and for explaining what the deterministic flags actually mean so you can write a useful report.

## Deterministic checks the script runs

| Check | What it flags | Severity |
|---|---|---|
| `tie_out_accounts_receivable` | Aged Receivables Total ≠ Balance Sheet Accounts Receivable | High if mismatch, Info if tied |
| `tie_out_accounts_payable` | Aged Payables Total ≠ Balance Sheet Accounts Payable | High if mismatch, Info if tied |
| `negative_fixed_assets` | A Fixed Assets / Non-Current Assets section with a negative total | High |
| `suspense_or_clearing_balance` | Non-zero balance in Historical Adjustment, Suspense, Tracking Transfers, Rounding, Unidentified, Clearing, Uncoded, or Unallocated accounts | High ≥$1k, Medium $50–$1k, Low <$50 |
| `bank_account_in_liabilities` | Any account with "bank" in its name appearing under Current Liabilities | High |
| `negative_net_assets` | Liabilities exceed assets (technical insolvency) | High |
| `depreciation_expense_missing` | Accumulated Depreciation has a balance but P&L shows no Depreciation expense — usually means the depreciation journal posted to the wrong account | High |

## What the deterministic flags actually mean

### Negative fixed assets net of accumulated depreciation
Cost minus accumulated depreciation must be ≥ 0. If it's negative, one of two things has happened:
1. Accumulated depreciation has been over-claimed (a depreciation journal was run twice, or for the wrong amount)
2. The asset cost was reversed but accumulated depreciation wasn't
Either way it's a journal entry error. The fix is to identify the bad journal in the GL listing and adjust.

### Historical Adjustment balance
This is Xero's conversion-balance contra account. When a Xero file is set up by importing balances, the "Historical Adjustment" account is used as the other side of every conversion entry. After setup, it should be cleared to retained earnings (or to the appropriate equity account) by a journal. A non-trivial balance sitting here months or years after conversion usually means setup was never finished — and any subsequent management accounts that include it are wrong.

### Bank account in Current Liabilities
If a bank account appears under liabilities, two scenarios:
- **Overdrawn**: Xero auto-classifies an overdrawn bank account as a liability when it's negative. The fix is to confirm that's actually what happened by checking the bank statement.
- **Wrong account type**: The account was set up as a Current Liability instead of a Bank account. Xero won't let it appear in bank reconciliation if so. Fix is to change the account type.

The Demo Company (AU) example shows this — a "Business Bank Account" sitting in Current Liabilities at $7,702.44, which means the account type was misconfigured at setup.

### Depreciation expense missing
Accumulated depreciation accumulates in a contra-asset on the Balance Sheet. The other side of every depreciation journal must be Depreciation expense on the P&L. If you see accumulated depreciation moving but no expense, the journal hit the wrong account on the debit side. Common culprit: someone debited the asset account itself instead of the expense.

In the Demo Company (AU) example, journal #455 debited Office Equipment $750 (asset) and credited Accumulated Depreciation $825 — wrong on both sides.

## Qualitative checks to do on top

These need an accountant's judgment. Look at the extracted Balance Sheet and consider:

### Account categorisation sanity
- Are bank accounts under Bank?
- Are loans under Non-Current Liabilities (or Current if due in <12 months)?
- Is GST under Current Liabilities (refundable position would be Current Asset)?
- Is PAYG / Superannuation Payable showing? If wages appear on P&L and no PAYG payable shows, super is probably also missing.
- Is there a Director Loan account? Movement should reconcile to actual director transactions.

### Suspense and clearing accounts
Beyond the named ones the script catches, watch for:
- Accounts with names like "1 - Asset" or "Asset 9999" — auto-created during data import
- Accounts with $0 names (just an account code with no description)
- "Customer Deposits", "Supplier Prepayments" with old balances
- Inter-company / inter-entity accounts with non-zero balances (should reconcile against the other entity)

### Equity composition
- Does Retained Earnings = prior year Net Profit cumulative? If a YE rollover hasn't run, Current Year Earnings will keep accumulating.
- Negative equity → check it's not just an accounting timing issue (e.g. unbilled revenue).

### Concentration
- One customer making up >50% of AR is a customer-concentration risk worth flagging.
- One supplier making up >50% of AP suggests supplier dependency.

### Stale balances
- AR or AP over 90 days suggests collection / payment issues. Check the Aged buckets.
- Old "Older" / 3+ months balances rarely improve; they're often write-off candidates.
