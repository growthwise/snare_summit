---
name: xero-report-review
description: Anomaly review across a standard set of Xero PDF reports (Balance Sheet, Profit and Loss, Aged Receivables Summary, Aged Payables Summary, Account Transactions). Use whenever a user provides Xero exports, asks to "check this file", "review these reports", "find errors", "flag anomalies", "check coding", "tie out the receivables", "check the GST", or otherwise hands over a set of period-end accounting PDFs from Xero (or a similar Australian cloud accounting system). Produces a prioritised list of structural balance-sheet anomalies, P&L red flags, AR/AP tie-out checks, and per-transaction GST and coding errors. Designed for Australian (GST 10%) Xero files but the structural checks apply to any chart of accounts.
---

# Xero Report Review

A skill for reviewing a set of Xero PDF exports and flagging anomalies, coding errors, and reconciliation breaks. Targeted at Australian Xero files with 10% GST.

## What this skill takes as input

The user will provide some or all of the following five PDFs (filenames vary; the script identifies each one by content):

1. **Balance Sheet** — point-in-time
2. **Profit and Loss** — for a period
3. **Aged Receivables Summary** — at the same date as the Balance Sheet
4. **Aged Payables Summary** — at the same date as the Balance Sheet
5. **Account Transactions** — the GL transaction listing for the same period as the P&L

If any are missing, run with what's available and note in the report which checks couldn't be performed. Don't ask the user for the missing files unless they ask you to do something that strictly requires one (e.g. "tie out the receivables" with no AR report).

## Workflow

Step 1 — **Locate the PDFs.** The user may have uploaded them, dropped them into a folder, or referenced an existing path. Find them. Don't ask questions you can answer by looking.

Step 2 — **Run the extractor.** This is the only mandatory tool call. It parses every PDF, runs all the deterministic checks, and produces a single JSON file:

```bash
python scripts/extract_reports.py <folder-or-files...> --out findings.json
```

The script accepts either a folder containing the PDFs or any combination of individual file paths. It's tolerant of unrecognised files (silently ignored), missing files (skipped), and PDFs from any Xero AU file — it identifies each report from its title line, not its filename.

Step 3 — **Read the JSON.** Pay particular attention to:
- `automatic_checks.findings` — pre-computed anomalies with severity ratings
- `balance_sheet.sections` and `balance_sheet.totals` — for additional structural review
- `profit_loss` — for ratio/composition review
- `transactions` — full GL listing to scan for additional patterns

Step 4 — **Apply qualitative judgment.** The script catches the deterministic stuff. You bring the accountant's eye for:
- Account categorisation issues the script doesn't have rules for
- Customer/supplier concentration in AR/AP
- Period-comparison reasoning if comparative figures are present
- Whether "expected" GST-free items in flagged transactions are actually correct (e.g. food can legitimately be GST-free)
- Anything else that looks off

The reference files describe what to look for in detail. Read them as needed:
- `references/balance-sheet-checks.md` — structural anomalies, account-categorisation traps, suspense balances
- `references/profit-loss-checks.md` — ratio analysis, missing accruals, expense composition
- `references/gst-coding-au.md` — Australian GST rules, common miscoding patterns

Step 5 — **Write the summary.** Use the format in the next section. Be specific (account names, amounts, dates), tight (no padding), and ordered by severity. The user is an accountant — speak the language. No definitions of "what is GST", no apologies, no preamble about your method.

## Output format

ALWAYS use this exact structure as a Markdown file or in-chat response:

```
# Xero Report Review — [Entity Name] [Period]

## Summary
[2-4 sentences. The headline finding(s). Whether the file is in good shape, needs attention, or is materially broken.]

## Tie-outs
- AR (Aged Receivables → Balance Sheet): [tied / variance of $X]
- AP (Aged Payables → Balance Sheet): [tied / variance of $X]

## High severity
[Bulleted list. Each item: one-line description, then sub-bullets with account name, amount, what's likely wrong, and what to investigate.]

## Medium severity
[Same format.]

## Low severity / observations
[Same format.]

## GST and coding review
- Transactions reviewed: [N]
- Tax-rate inconsistencies (gross/11 ≠ GST): [count, with examples if any]
- GST-free coding on accounts that usually attract GST: [count, with examples]
- Manual journals with GST applied: [count, with examples]
- [Additional patterns you noticed manually]

## Files reviewed
[List the PDFs ingested + classification, e.g. "Balance Sheet ✓, P&L ✓, ..."]

## Files missing
[Only if any. List which checks couldn't be run as a result.]
```

Don't pad it. If a section has nothing worth saying, write "None identified" and move on. Don't invent middling-severity items to fill space.

## Severity guidelines

- **High** — material errors that affect the truth of the financial statements. Examples: tie-out break, negative net fixed assets, suspense balances >$1k, bank in liabilities, missing depreciation expense, technical insolvency, GST math errors involving large amounts.
- **Medium** — likely-but-not-definite errors, ratios that warrant explanation, GST coding that's probably wrong but might have a legitimate reason. Examples: GST-free entertainment from a commercial supplier, manual journals with GST, wage concentration, net loss for the period, suspense balances $50–$1k.
- **Low** — small balances, rounding, things worth noting on the way past. Examples: rounding account ±$10, single-cent variances, expense claims for trivial GST-free amounts.

Push items down a tier rather than up if you're not sure — false-positive high items burn the reviewer's attention.

## Things to be careful about

- **GST-free is sometimes correct.** Accounts on the `GST_EXPECTED_ACCOUNTS` list usually attract GST, but legitimate exceptions exist: food purchases under entertainment, overseas suppliers, suppliers without an ABN, GST-registered turnover thresholds. Note in the output that the items are "for review" not "errors".
- **Comparative figures matter.** The user mentioned wanting to spot "rapid increases or declines". A single-period report can't show trends. If only one period is available, say so and focus on absolute anomalies. If comparative columns are present (Xero's "Compare with previous period" option), do trend analysis on each line item that moves >25% or >$1k.
- **Tie-outs apply to a date.** The Aged AR/AP totals must be at the same date as the Balance Sheet. If the dates differ, flag it — a "tie-out" between mismatched dates isn't a tie-out.
- **The script's GST rule is 10% (Australia).** Wholly-owned offshore subsidiaries in NZ/UK/etc. won't satisfy the GST math check; if `country` looks non-AU, downgrade GST findings to "for review".
- **Watch for typos and account-name drift.** A new "Marketing Expenses" account this quarter when there used to be "Advertising" might be a re-code, not an error. Note these where you see them.

## Example

User: *"Hey, can you have a look at these reports for me? Anything weird?"* (with 5 PDFs uploaded)

Your move:
1. Run `python scripts/extract_reports.py /path/to/uploads --out findings.json`
2. Read findings.json
3. Skim transactions for anything the script flagged or anything else odd
4. Write the report in the format above

Don't ask "which entity?" or "what period?" or "what are you looking for?" — the answers are in the PDFs. Just go.
