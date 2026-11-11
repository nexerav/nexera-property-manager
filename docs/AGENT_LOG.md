# Agent log

## 2026-11-11

What changed: Version 1.5.0 adds a double-click Mac and Windows app. The first page asks for a password, the app creates its own secret key, and the books stay in Documents/Nexera Property Manager. Server installs still require SECRET_KEY and APP_PASSWORD. GitHub release workflow builds the zips and publishes the changelog.

Why: Landlords should not have to use a terminal.

Files: desktop.py, app.py, auth.py, version.py, templates/setup.html, templates/desktop_reset.html, templates/quit.html, templates/login.html, templates/dashboard.html, scripts/build_desktop.py, scripts/release_notes.py, .github/workflows/release.yml, README.md, CHANGELOG.md, SECURITY.md, tests/test_app.py.

Verification: `python3 -m unittest tests.test_app -v` passed, including a live desktop process that served the password page on 127.0.0.1.

Open items: Mac and Windows will warn on first open until the downloads are signed with a paid developer certificate. The desktop server binds on 127.0.0.1 without a DNS lookup, and a headless run does not wait on a dialog. On Windows, a password reset with no console exits instead of waiting for a key.

Version 1.5.1 zips the Mac app with ditto so the shortcuts inside the app survive. The 1.5.0 Mac zip stored copies instead, and macOS called the app damaged. On current macOS the first open is System Settings, Privacy & Security, Open Anyway. Right-click Open remains the path on older Macs.
