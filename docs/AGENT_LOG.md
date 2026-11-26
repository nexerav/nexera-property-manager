# Agent log

## 2026-11-26 later

What changed: The workbench is the home server `nexerav`, not the rented server. GitHub remains the sync. The rented server `156.155.253.123` is being cancelled.

Why: The owner is cancelling the Cloud VM. That name means the rented machine, not the computer at the house.

Files: AGENTS.md, progress.md, docs/AGENT_LOG.md.

Verification: Docs only. `nexerav` still has no GitHub SSH key, so the clone was not moved in this change.

## 2026-11-26

What changed: Recorded where this app is edited and where the demo, website, and waitlist run. Added `AGENTS.md` and `progress.md`.

Why: The next coding session needs one workbench directory, and the live folders are not that directory.

Files: AGENTS.md, progress.md, docs/AGENT_LOG.md.

Verification: The workbench clone is `~/work/nexera-property-manager` on the Cloud VM. No live directory was edited.

## 2026-11-11

What changed: Version 1.5.0 adds a double-click Mac and Windows app. The first page asks for a password, the app creates its own secret key, and the books stay in Documents/Nexera Property Manager. Server installs still require SECRET_KEY and APP_PASSWORD. GitHub release workflow builds the zips and publishes the changelog.

Why: Landlords should not have to use a terminal.

Files: desktop.py, app.py, auth.py, version.py, templates/setup.html, templates/desktop_reset.html, templates/quit.html, templates/login.html, templates/dashboard.html, scripts/build_desktop.py, scripts/release_notes.py, .github/workflows/release.yml, README.md, CHANGELOG.md, SECURITY.md, tests/test_app.py.

Verification: `python3 -m unittest tests.test_app -v` passed, including a live desktop process that served the password page on 127.0.0.1.

Open items: Mac and Windows will warn on first open until the downloads are signed with a paid developer certificate. The desktop server binds on 127.0.0.1 without a DNS lookup, and a headless run does not wait on a dialog. On Windows, a password reset with no console exits instead of waiting for a key.

Version 1.5.1 zips the Mac app with ditto so the shortcuts inside the app survive. The 1.5.0 Mac zip stored copies instead, and macOS called the app damaged. On current macOS the first open is System Settings, Privacy & Security, Open Anyway. Right-click Open remains the path on older Macs.
