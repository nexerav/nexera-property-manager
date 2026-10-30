# Nexera Property Manager

**Free, self-hosted rental books for small landlords. Rent, expenses, invoices and maintenance on your own computer, with no account and no monthly fee.**

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Tests](https://github.com/nexerav/nexera-property-manager/actions/workflows/test.yml/badge.svg)](https://github.com/nexerav/nexera-property-manager/actions/workflows/test.yml)

[Live demo](https://demo.nexerav.com) · [Website](https://www.nexerav.com) · [Report a bug](https://github.com/nexerav/nexera-property-manager/issues)

<!-- PLACEHOLDER: 20–30 s GIF, docs/screenshots/tour.gif: sign in → add rent → create invoice → download PDF. Sample data only. -->
<!-- ![Tour](docs/screenshots/tour.gif) -->

## Why this exists

Most rental software is built for agencies and charges per unit per month. If you own one to ten units, you usually end up with a spreadsheet, a folder of PDFs and a WhatsApp thread. This is the tool we wanted for that: one login, one data file, proper invoices and a clear picture of what each unit earns. It was built for South African landlords (rand, recoveries for water and electricity, body-corporate costs) but works anywhere.

## Quick start (Docker, about 2 minutes)

```bash
git clone https://github.com/nexerav/nexera-property-manager.git
cd nexera-property-manager
cp .env.example .env
# set SECRET_KEY and APP_PASSWORD in .env; generate a key with:
python3 -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d --build
```

Open http://127.0.0.1:5000 and sign in as `admin` (or your `APP_USERNAME`) with the password you set. The app will not start with a missing or placeholder `SECRET_KEY` / `APP_PASSWORD`. Your data lives in `./data/rental_data.json` and survives `docker compose down`.

## Screenshots

| Overview | Money | Invoices | Settings |
|---|---|---|---|
| ![](docs/screenshots/overview.png) | ![](docs/screenshots/money.png) | ![](docs/screenshots/invoices.png) | ![](docs/screenshots/settings.png) |

## Free vs Premium

| | Free (this repo) | Premium / hosted (Nexera Ventures) |
|---|---|---|
| Properties, income, expenses, recoveries | ✅ | ✅ |
| Invoices with PDF download and your logo | ✅ | ✅ |
| Dashboard (month, year, all time, custom) | ✅ | ✅ |
| Maintenance requests → expenses | ✅ | ✅ |
| Email invoices, WhatsApp, automated reminders | – | ✅ |
| OCR bill scanning, advanced charts, property pipeline | – | ✅ |
| Multiple users and roles, automated backups | – | ✅ |
| We host it for you | – | ✅ |

The free edition does not phone home and never needs a paid account. Interested in Premium? Join the waitlist at [nexerav.com](https://www.nexerav.com) or email info@nexerav.com.

## Security

Built for a computer you control. Do not expose port 5000 to the internet; the JSON file is not encrypted. Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## Run the tests

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest tests.test_app -v
```

CI runs the tests plus a gitleaks secrets scan on every push and PR.

## Tech

Python 3.11 · Flask · gunicorn (1 worker) · JSON file storage · ReportLab PDFs · Chart.js (bundled, MIT) · Docker.

## Contributing

Issues and PRs are welcome; look for `good first issue`. See [CONTRIBUTING.md](CONTRIBUTING.md). Never post real tenant data in an issue. Contributions are licensed under AGPL-3.0.

## Licence

Copyright (C) 2026 Nexera Ventures. GNU AGPL-3.0-or-later; see [LICENSE](LICENSE). If you run a modified version as a network service, you must offer its source to its users. Commercial licences are available on request.
