# Changelog

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
