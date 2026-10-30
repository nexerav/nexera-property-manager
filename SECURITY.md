# Security

## Using it safely

Nexera Property Manager is a local application. One person signs in. The records sit in `data/rental_data.json` as plain text.

- Set `APP_PASSWORD` and `SECRET_KEY` in `.env` before the first start. The app exits if either value is missing or still a published placeholder. There is no default password.
- Do not forward port 5000 to the public internet.
- Keep the `data/` folder out of shared drives if other people should not read it.
- The file is not encrypted. A backup is a copy of that file. Protect the copy the same way.

## Reporting a vulnerability

Email security reports to [support@nexerav.com](mailto:support@nexerav.com). Please do not open a public GitHub issue for a security flaw, and do not send your data file.

Include the version or commit, what you observed, and how to reproduce it. You should hear back within 10 days. If you do not, send the email again. A fix for a confirmed flaw will be published in this repository when it is ready.

There is no bug-bounty programme.
