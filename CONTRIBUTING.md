# Contributing

Thanks for looking. This is a small project, and the maintainers read issues when they can. A reply is not guaranteed, and there is no support timetable.

## Bugs and ideas

Open a GitHub issue. Include:

- What you expected
- What happened
- The steps that show it
- Your operating system, and whether you used Docker

Do not include real tenant names, property addresses, phone numbers, bank details, identity numbers, or a copy of `data/rental_data.json`. If a screenshot would show that information, crop it or describe it instead.

## Changes

1. Fork the repository and create a branch.
2. Keep the free edition useful. Do not hide an existing free feature behind the premium message.
3. Paid features stay visible and locked, with the message `Premium feature – contact Nexera Ventures`.
4. Keep new sample data generic. Do not add real people, real properties, or client names.
5. Run `python3 -m unittest tests.test_app -v`.
6. Open a pull request that explains the change.

This program is licensed under the AGPL-3.0. A contribution is licensed the same way, and you confirm that you have the right to submit it.

## What we will not merge

- Code that sends email, WhatsApp messages, or other paid-network features from this edition
- A second user model, or a hosted database, presented as part of the free edition
- Dependencies that are not needed to run the Docker app
- Generated or copied private records
