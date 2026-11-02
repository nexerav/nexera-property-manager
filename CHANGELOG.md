# Changelog

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
