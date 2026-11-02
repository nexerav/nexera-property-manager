# Security

## Using it safely

Nexera Property Manager is a local application. One person signs in. The records sit in `data/rental_data.json` as plain text.

- Set `APP_PASSWORD` and `SECRET_KEY` in `.env` before the first start. The app exits if either value is missing or still a published placeholder. There is no default password.
- Five wrong sign-ins lock the account for 15 minutes. Reset the password from the computer that runs the app with `python3 app.py reset-password`, or from Settings while you are still signed in. The command never takes the password as an argument. A reset stores a hash in the data file and clears the lockout. If `SMTP_HOST`, `SMTP_FROM`, and `PASSWORD_RESET_EMAIL` are set, the sign-in page can email a one-time link that expires after 30 minutes.
- Set `DEMO_MODE=1` on a public demo. That turns off password changes in the browser and in the reset command. A username of `demo` also refuses a browser reset unless `ALLOW_PASSWORD_RESET=1`.
- Do not forward port 5000 to the public internet.
- Keep the `data/` folder out of shared drives if other people should not read it.
- The file is not encrypted. A backup is a copy of that file. Protect the copy the same way.

## Reporting a vulnerability

Email security reports to [support@nexerav.com](mailto:support@nexerav.com). Please do not open a public GitHub issue for a security flaw, and do not send your data file.

Include the version or commit, what you observed, and how to reproduce it. You should hear back within 10 days. If you do not, send the email again. A fix for a confirmed flaw will be published in this repository when it is ready.

There is no bug-bounty programme.
