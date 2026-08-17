# Profit and Loss anomaly checks

## Deterministic checks the script runs

| Check | What it flags | Severity |
|---|---|---|
| `net_loss` | Net result < $0 | Medium |
| `high_wages_to_revenue` | Wages and Salaries > 50% of revenue | Medium |
| `depreciation_expense_missing` | Accumulated dep has a balance on B/S but no Dep expense on P&L | High (cross-statement check, see balance-sheet-checks.md) |

## Qualitative checks to do on top

### Composition red flags

**Wages without Superannuation / PAYG.** Australian payroll always involves super (currently 12%) and PAYG withholding. If Wages and Salaries shows but neither shows, the payroll posting is incomplete. Super may sit under a separate "Superannuation" expense account or on the Balance Sheet as Super Payable — check both.

**Trading income but no Cost of Sales.** OK for service businesses, suspicious for retailers, manufacturers, hospitality, etc. Use the entity's industry context (if known) to judge.

**Depreciation missing despite fixed assets present.** If the Balance Sheet shows Fixed Assets at cost but no accumulated depreciation, no depreciation has ever been booked — flag for the YE adjustment.

**No interest expense despite a loan account.** If the Balance Sheet has a loan or borrowing account but the P&L has no interest expense, interest accruals are missing.

**Single-entry expense categories.** If a category like "General Expenses" is materially larger than usual, drill into Account Transactions for that account — vague catch-all coding hides specific issues.

### Ratio analysis

Run these mentally for the period:

- **Wages / Revenue** — script flags >50%. Service businesses run 40–70%; over 80% suggests revenue under-recognition or labour bloat.
- **Rent / Revenue** — sustainable typically <10% for most businesses.
- **Total opex / Revenue** — over 100% is the operating loss the script catches separately.
- **Marketing/advertising / Revenue** — varies wildly by industry; inconsistency between periods matters more than absolute level.

### Period comparison (only if comparative figures are present)

Xero's "Compare with previous period" option produces P&Ls with two columns. If those are present, flag any line item that:
- Moves >25% and >$1k in absolute terms
- Goes from $0 to a material balance (new account this period)
- Goes from a material balance to $0 (account dropped — the spend may have moved or stopped)
- Reverses sign (an expense that became a credit, or a revenue that became a debit)

If only single-period figures are available, say so in your output:
> "Period comparison not available — comparative columns weren't included in the P&L export. Trend analysis would require a comparative report."

### Concentration

- A single revenue line >70% of total revenue = customer/product concentration risk.
- A single expense line >50% of total opex = cost concentration; usually wages, sometimes rent or COGS.

### Categorisation issues to watch for

- Entertainment that should be split between deductible client entertainment and non-deductible internal staff entertainment (ATO treats these differently for income-tax and FBT purposes).
- Capital expenditure miscoded as expense (look for large one-off amounts in Office Expenses, Repairs & Maintenance, IT — these may belong on the Balance Sheet).
- Personal expenses for sole traders / closely held companies — usually need to be reclassified to Drawings or Director Loan.
- Insurance accruals — annual premiums paid upfront should be apportioned monthly via prepayments, not expensed in the month paid.

### Net profit reconciliation
The B/S shows "Current Year Earnings" — confirm this equals the P&L net profit. If they differ, journals have been posted directly to retained earnings or current year earnings, bypassing the P&L. Note these for review.
