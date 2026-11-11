# Nexera Property Manager

**Free, self-hosted rental books for small landlords. Rent, expenses, invoices and maintenance on your own computer, with no account and no monthly fee.**

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Tests](https://github.com/nexerav/nexera-property-manager/actions/workflows/test.yml/badge.svg)](https://github.com/nexerav/nexera-property-manager/actions/workflows/test.yml)

[Live demo](https://demo.nexerav.com) · [Website](https://www.nexerav.com) · [Report a bug](https://github.com/nexerav/nexera-property-manager/issues)

<!-- PLACEHOLDER: 20–30 s GIF, docs/screenshots/tour.gif: sign in → add rent → create invoice → download PDF. Sample data only. -->
<!-- ![Tour](docs/screenshots/tour.gif) -->

## Why this exists

Most rental software is built for agencies and charges per unit per month. If you own one to ten units, you usually end up with a spreadsheet, a folder of PDFs and a WhatsApp thread. This is the tool we wanted for that: one login, one data file, proper invoices, PDF and Excel exports, and a clear picture of what each unit earns. It was built for South African landlords (rand, recoveries for water and electricity, body-corporate costs) but works anywhere.

## Install on your computer

Download the latest version. There is no terminal and no settings file.

- [Download for Mac](https://github.com/nexerav/nexera-property-manager/releases/latest/download/Nexera-Property-Manager-mac.zip)
- [Download for Windows](https://github.com/nexerav/nexera-property-manager/releases/latest/download/Nexera-Property-Manager-windows.zip)

The version number is on the [releases page](https://github.com/nexerav/nexera-property-manager/releases) and on the sign-in screen. What changed is in [CHANGELOG.md](CHANGELOG.md) and on that same releases page.

1. Unzip the download.
2. On a Mac, the first time, right-click **Nexera Property Manager** and choose **Open**, then **Open**. On Windows, double-click **Nexera Property Manager**. If Windows says it protected your PC, choose **More info**, then **Run anyway**.
3. Your browser opens. Choose a password. The username is `admin`.
4. Your books are saved in **Documents / Nexera Property Manager**. Copy that folder when you want a backup.

Open the same app the next time. Closing the browser does not delete your books. Forgot the password? Choose **Forgot password?** on the sign-in page and set a new one. That stays on this computer.

To move to a newer download, choose **Quit Nexera** on the sign-in page, then open the new copy. The books stay in the same folder.

## Run it on a server

This path is for someone who already runs Docker. The download above is the install for everyone else.

```bash
git clone https://github.com/nexerav/nexera-property-manager.git
cd nexera-property-manager
cp .env.example .env
# set SECRET_KEY and APP_PASSWORD in .env; generate a key with:
python3 -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d --build
```

Open http://127.0.0.1:5000 and sign in as `admin` (or your `APP_USERNAME`) with the password you set. The app will not start with a missing or placeholder `SECRET_KEY` / `APP_PASSWORD`. Your data lives in `./data/rental_data.json` and survives `docker compose down`. A server install does not show the first-run password page.

## If you are locked out

Five wrong passwords lock sign-in for 15 minutes. You can clear that, and choose a new password, from the machine that runs the app. The command asks for the password so it does not end up in your shell history:

```bash
python3 app.py reset-password
```

With Docker, from the project directory:

```bash
docker compose exec -it property-manager python app.py reset-password
```

The new password is stored as a hash in `data/rental_data.json` and is what signs in after that, including after a restart. `APP_PASSWORD` in `.env` is only the bootstrap password until the first reset.

A script can set `APP_PASSWORD_RESET` for that one run instead of typing at the prompt. The password is still not accepted as a command argument. On Windows this is also what to use when the command is not attached to a console window.

While you are signed in, Settings has the same change. It asks for the current password, then clears a lockout.

If you set `SMTP_HOST`, `SMTP_FROM`, and `PASSWORD_RESET_EMAIL`, the sign-in page can email you a link. The link works once and expires after 30 minutes. Without those settings, no reset email is sent.

The public demo must not be reset by a visitor. Set `DEMO_MODE=1` on that host. A username of `demo` also refuses a browser reset unless you set `ALLOW_PASSWORD_RESET=1` on a private install that really uses that username.

With `DEMO_MODE=1`, a data file that has no rent is filled with fictional sample books for the last year, so the dashboard is not an empty month. A file that already has rent is left as it is. Settings and the password hash are kept. To show the sample story again, remove `demo_seed` from the data file (or replace the file) and start the app. The dashboard opens on the last 12 months.

## Screenshots

| Overview | Money | Invoices | Settings |
|---|---|---|---|
| ![](docs/screenshots/overview.png) | ![](docs/screenshots/money.png) | ![](docs/screenshots/invoices.png) | ![](docs/screenshots/settings.png) |

## Free vs Premium

| | Free (this repo) | Premium / hosted (Nexera Ventures) |
|---|---|---|
| Properties, income, expenses, recoveries | ✅ | ✅ |
| Invoices with PDF download and your logo | ✅ | ✅ |
| PDF and Excel exports (profit and loss, rent roll, tenant statements, invoices, transactions) | ✅ | ✅ |
| Dashboard (month, year, all time, custom) | ✅ | ✅ |
| Maintenance requests → expenses | ✅ | ✅ |
| Premium | The free edition is complete for keeping your own books | Premium adds instant invoicing, invoices emailed straight from the platform, a property deal pipeline, and AI agents that handle the admin. |
| We host it for you | – | ✅ |

The free edition does not phone home and never needs a paid account. Premium adds instant invoicing, invoices emailed straight from the platform, a property deal pipeline, and AI agents that handle the admin. Join the waitlist at [nexerav.com](https://www.nexerav.com). The link is `WAITLIST_URL` (default `https://www.nexerav.com`). There is no third-party tracking in this app.

## Exports

Signed-in users can download the books they would hand to an accountant, to SARS, or to a tenant. The buttons are on the page the report belongs to, and they follow the period and property selected in the toolbar. Amounts are in rand. PDFs use the organisation name, contact details, and logo from Settings. Excel files use the same headings and a rand number format, so a total still calculates.

| Report | Page | What it contains |
|---|---|---|
| Profit and loss | Overview | Income split into rent, recoveries, and other; expenses by the category you entered (bond interest stays separate from bond capital); per-property totals; the transactions behind them |
| Rent roll | Properties | Each unit, the current tenant, expected monthly rent, and income, expenses, and net for the period |
| Transactions | Money | Income and expenses for the period, with a signed amount in Excel |
| Invoices | Invoices | Register and line items for the period. Each invoice also has its own PDF and Excel file |
| Tenant statement | Invoices | Invoices as charges, recorded income as payments, and a running balance. One tenant, or every tenant in the period |

These exports are part of the free edition. There is no feature flag and no premium lock. The public demo at [demo.nexerav.com](https://demo.nexerav.com) includes them after you sign in with the demo login.

To update a server that is already running, including the demo, pull this version and rebuild. The data folder is left as it is:

```bash
git pull
docker compose up -d --build
```

## Security

Built for a computer you control. Do not expose port 5000 to the internet; the JSON file is not encrypted. Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## Run the tests

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest tests.test_app -v
```

CI runs the tests plus a gitleaks secrets scan on every push and PR.

## Tech

Python 3.11 · Flask · gunicorn (1 worker) · JSON file storage · ReportLab PDFs · openpyxl Excel · Chart.js (bundled, MIT) · Docker.

## Contributing

Issues and PRs are welcome; look for `good first issue`. See [CONTRIBUTING.md](CONTRIBUTING.md). Never post real tenant data in an issue. Contributions are licensed under AGPL-3.0.

## Licence

Copyright (C) 2026 Nexera Ventures. GNU AGPL-3.0-or-later; see [LICENSE](LICENSE). If you run a modified version as a network service, you must offer its source to its users. Commercial licences are available on request.
