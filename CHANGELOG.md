# Changelog

## 1.6.0

- The nightly demo reset is `python app.py reset-demo` (or `scripts/reset-demo.sh`). It writes the same sample the app serves, including six invoices across months and statuses. A separate shorter seed is not used. It runs only when `DEMO_MODE=1`.

## 1.4.0

### QA fixes

- Every amount uses one format, `R 8,500.00`: the screen, the invoice, the chart, the PDF, and Excel. The browser and the server share that pattern (comma thousands, dot cents), including a South African browser that would otherwise show `R 8 500,00`.
- The demo sample now has six invoices across several months: draft, issued, outstanding, overdue, and paid. An older demo sample (marked `demo_seed` 1) is refreshed on startup. A file with rent and no `demo_seed` marker is still left alone.
- Invoice numbers stay on one line.
- The app serves a navy N favicon at `/favicon.ico`, and the chart file no longer asks for a missing source map.
- Helper text and the footer use `#2d3748`, which is about 12:1 on white and clears WCAG AA.

Redeploy the demo with the usual rebuild. `DEMO_MODE=1` refreshes the sample invoices if the file was the previous demo seed:

```bash
git pull
docker compose up -d --build
```

## 1.3.0

### Demo and screen polish

- A public demo (`DEMO_MODE=1`) with no rent recorded is filled with fictional sample books for the last year: rent, ordinary recoveries, and expenses across the sample units, plus overhead that is not a unit. A file that already has rent is not replaced. Settings and the password hash stay. Restart after pulling this version; if the demo still shows only the old electricity recovery, the file had no rent and will be replaced on startup.
- The dashboard opens on the last 12 months, so a new visitor is not looking at an empty current month.
- Delete asks you to confirm on the button itself, and the delete control sits apart from Edit.
- Money is `R 8,500.00` on screen, on invoices, and in PDF and Excel. Whole quantities show as `1`, not `1.0`.
- Invoice dates stay on one line.
- The invoice note says "this server" on the demo and "this computer" when you run it yourself.
- Expense categories use plain names. Older names such as "Bond Capital Payment (Equity - Not Deductible)" still load and are shown as "Bond capital payment", with the tax note as help text.
- Company Expenses is grouped as overhead, not a property.
- Premium controls are marked Premium and are not styled as ordinary buttons. The description is: "Premium adds instant invoicing, invoices emailed straight from the platform, a property deal pipeline, and AI agents that handle the admin." Join the waitlist uses `WAITLIST_URL`, which defaults to https://www.nexerav.com. The free edition is unchanged.

Redeploy the demo with `DEMO_MODE=1` already set:

```bash
git pull
docker compose up -d --build
```

No new secret is required. Set `WAITLIST_URL` only if the waitlist should open somewhere other than https://www.nexerav.com.

## 1.2.0

### PDF and Excel exports

You can download the reports a landlord actually sends on. This is part of the free edition. Nothing here is paid, locked, or hidden behind a flag, including on the public demo at demo.nexerav.com after the demo sign-in.

- **Profit and loss** for the period selected on the dashboard (this month, this year, all time, or custom dates), and for one property or the whole portfolio. Income is split into rent, recoveries, and other. Expenses stay under the category you entered, so bond interest (tax deductible) stays separate from bond capital (not deductible). The report includes a per-property split and the transactions behind the totals.
- **Rent roll** of units and tenants: expected monthly rent, who is in the unit, and income, expenses, and net for the period. A second tenants list shows the last payment and the last invoice.
- **Tenant statements** with invoices as charges, income recorded against that tenant as payments, and a running balance. A negative balance is a credit. Export one tenant or every tenant in the period. Payment details from Settings are printed on the PDF and included in the Excel file.
- **Invoices** as a register for the period, with a line-item sheet in Excel, plus the existing single-invoice PDF and a matching Excel file.
- **Transaction list** of income and expenses for the period. Excel adds a signed amount (income positive, expenses negative) so a column can be summed.

Each of those has **Export PDF** and **Export Excel** on the page it belongs to. PDFs use the organisation name, contact details, and logo from Settings, and amounts are formatted in rand (`R 1,234.00`). Excel workbooks use the same headings, a rand number format, a frozen header, and print to A4 landscape.

The public demo can download the same files. There is no new environment variable. Redeploy with `docker compose up -d --build` so the image picks up `openpyxl`. The `data` volume is not replaced.

## 1.1.0

### Password reset

You can get back in if you forget the password or the sign-in locks after too many tries.

- Five wrong passwords lock sign-in for 15 minutes. The right password does not get through until the lock ends or you reset it.
- From the computer that runs the app, `python3 app.py reset-password` asks for a new password. It does not take the password as an argument. With Docker, use `docker compose exec -it property-manager python app.py reset-password`.
- Settings has a password change for when you are already signed in. It asks for the current password.
- If `SMTP_HOST`, `SMTP_FROM`, and `PASSWORD_RESET_EMAIL` are set, Forgot password on the sign-in page emails a link. The link expires after 30 minutes and works once. The token is stored only as a hash. If mail is not set up, the page tells you to use the server command and does not invent a link.
- A reset clears the lockout and any older reset link. The new password is a hash in the data file, so it still works after a restart.

The public demo cannot be taken over with this. `DEMO_MODE=1` turns off the browser reset, the Settings change, and the reset command. A username of `demo` also refuses a browser reset unless that private install sets `ALLOW_PASSWORD_RESET=1`.

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
