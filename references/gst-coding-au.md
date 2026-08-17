# GST coding checks (Australia)

Australia's GST rate is 10%. For a GST-inclusive amount, the GST component is the gross divided by 11.

## Deterministic checks the script runs

| Check | What it flags | Severity |
|---|---|---|
| `gst_math_inconsistent` | Transactions where reported GST differs from gross/11 by more than $0.05 | Medium |
| `gst_free_on_taxable_account` | Transactions in expense accounts that usually attract GST but were coded GST-free | Medium |
| `manual_journal_with_gst` | Manual Journal source transactions with non-zero GST | Medium |

The script's `GST_EXPECTED_ACCOUNTS` list (commercial expense accounts that typically have GST) is in `extract_reports.py`. Update it if a client uses non-standard account names.

## Tax codes you should expect to see

| Xero code | Meaning | When it's right |
|---|---|---|
| GST on Income (10%) | Sale to GST-registered customer in AU | Most domestic sales |
| GST Free Income | Sale that's GST-free (basic food, exports, medical, education, etc.) | When the supply itself is GST-free under GST Act |
| GST on Expenses (10%) | Purchase from GST-registered AU supplier | Most domestic expenses |
| GST Free Expenses | Bank fees, wages, super, government charges, GST-free supplies, supplier without ABN | When the supply is genuinely GST-free |
| Input Taxed | Residential rent income, financial supplies | Specific industries |
| BAS Excluded | Internal transfers, payroll-related items, asset purchases not claiming GST | Movements not part of taxable supplies |

## Common miscoding patterns

### Entertainment
**The trap:** entertainment is often booked GST-free out of confusion with the income-tax non-deductibility rules. They're separate.

- Client entertainment from a GST-registered supplier (restaurants, party hire, venues, catering) **does** attract GST. The supplier charged GST on the invoice; you can claim it.
- Income-tax deductibility is a separate question. The expense may be non-deductible for income tax even though GST is claimable. This is handled at year-end via FBT and tax adjustments — the BAS coding itself is "GST on Expenses".
- The exception: when the supplier isn't GST-registered or the supply is GST-free (e.g. some takeaway food).

In the Demo Company (AU) example, "Party Hire" was booked GST-free for $450 — almost certainly an error since commercial party hire suppliers are GST-registered.

### Manual journals with GST
Manual journals are typically used for non-cash adjustments: depreciation, accruals, prepayments, reclassifications. None of these create or reverse a taxable supply, so they should be GST-excluded (BAS Excluded code).

If a manual journal has GST applied, two things go wrong:
1. The BAS picks up GST that doesn't correspond to a real supply, distorting GST payable
2. The amount excluding GST is wrong, distorting the expense

Demo Company example: journal #455 "Being depreciation on office equipment" applied $75 GST. Both the asset balance and the GST account are now wrong.

### Bank fees
Always GST Free in Australia. If you see bank fees with GST applied, the tax rate is wrong. The exception is merchant fees — some payment-processor fees include GST (Stripe, Square, PayPal), but a direct bank fee from your bank doesn't.

### Wages, superannuation, PAYG
All BAS Excluded. If GST shows on a wage spend-money or a super contribution, the tax code is wrong.

### Sales without GST that should have GST
Look at the Sales account in transactions. Any line booked GST Free for an Australian customer should have a reason — typically the customer is overseas (export, GST-free) or the supply is genuinely GST-free. Ask why if it's not obvious.

### GST math inconsistencies
The script flags any transaction where `|GST - gross/11| > $0.05`. Common causes:
- Tax rate manually overridden (e.g. set to 0% on a transaction that should be 10%)
- Rounding errors on multi-line invoices (sometimes legitimate to a few cents — only flag if material)
- Foreign-currency transaction where the AUD-equivalent GST was calculated differently from the AUD-equivalent gross
- A "GST on Income (10%)" rate applied to the wrong account (e.g. on Wages — GST shows but the line should be BAS Excluded)

### Expense claims and small purchases
Employee expense claims often come through GST-free even when they shouldn't. The receipt has GST but the claim was entered without it. For immaterial amounts (<$5 GST) this is usually let through; for larger amounts the user needs to claim the GST properly.

## What to write in the report

For GST findings, group similar items rather than listing every transaction. Example:

> **Entertainment expenses booked GST-free (Medium)** — 6 transactions totalling $704.20. Includes "Party Hire" invoices on 26 Feb totalling $450 from a commercial supplier; these likely should have GST. Smaller expense-claim items (Berry Brew $11.50, two staff entertainment claims under $10) may be legitimately GST-free if from non-registered suppliers — review supplier invoices to confirm.

Don't list every single one if there are dozens — give the count, the total, the pattern, and the one or two largest examples.
