---
description: Summarise a folder of invoices (PDF, Word or Excel) into one Excel workbook with totals.
---
1. Ask which folder and period if the owner did not say. Default: `invoices/` for this month.
2. List the files with `files__list_files`. Read each one with `docs__read_document` (PDF, Word)
   or `excel__read_sheet` (Excel).
3. For each invoice take: number, date, client, amount before tax, tax, total, currency, due date.
   If a value is missing, leave the cell empty and note it. Never guess an amount.
4. Write `reports/invoice-summary-<YYYY-MM>.xlsx` with `excel__write_sheet`: one row per
   invoice, then a totals row per currency.
5. Reply with: invoice count, total per currency, overdue invoices (due date passed), and
   the files you could not read.
