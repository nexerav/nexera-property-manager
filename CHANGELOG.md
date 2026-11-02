# Changelog

## 1.1.0

### PDF and Excel exports

You can download the reports a landlord actually sends on. This is part of the free edition. Nothing here is paid, locked, or hidden behind a flag, including on the public demo at demo.nexerav.com after the demo sign-in.

- **Profit and loss** for the period selected on the dashboard (this month, this year, all time, or custom dates), and for one property or the whole portfolio. Income is split into rent, recoveries, and other. Expenses stay under the category you entered, so bond interest (tax deductible) stays separate from bond capital (not deductible). The report includes a per-property split and the transactions behind the totals.
- **Rent roll** of units and tenants: expected monthly rent, who is in the unit, and income, expenses, and net for the period. A second tenants list shows the last payment and the last invoice.
- **Tenant statements** with invoices as charges, income recorded against that tenant as payments, and a running balance. A negative balance is a credit. Export one tenant or every tenant in the period. Payment details from Settings are printed on the PDF and included in the Excel file.
- **Invoices** as a register for the period, with a line-item sheet in Excel, plus the existing single-invoice PDF and a matching Excel file.
- **Transaction list** of income and expenses for the period. Excel adds a signed amount (income positive, expenses negative) so a column can be summed.

Each of those has **Export PDF** and **Export Excel** on the page it belongs to. PDFs use the organisation name, contact details, and logo from Settings, and amounts are formatted in rand (`R 1,234.00`). Excel workbooks use the same headings, a rand number format, a frozen header, and print to A4 landscape.

The public demo can download the same files. There is no new environment variable. Redeploy with `docker compose up -d --build` so the image picks up `openpyxl`. The `data` volume is not replaced.

## 1.0.1

- The app refuses to start until `SECRET_KEY` and `APP_PASSWORD` are set to your own values
- Debug mode stays off unless `FLASK_DEBUG` is set
- GitHub Actions runs gitleaks on every push and pull request

## 1.0.0

First public release.

- Properties, income, expenses, recoveries, invoices with PDF download, maintenance, and a single-user login
- Settings for organisation details and a logo
- Basic dashboard with one chart
- Email, WhatsApp, automated reminders, the Property Pipeline, advanced charts, OCR, multi-user roles, and automated backups are visible and locked
- Data stays in a local JSON file
- Licensed under the AGPL-3.0
