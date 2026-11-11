#!/usr/bin/env python3
# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Print GitHub release notes from the newest changelog section."""

import pathlib
import sys


INSTALL = """\
## Install on your computer

Download the file for your computer from this release. You do not need a terminal.

- **Mac:** unzip the download and double-click **Nexera Property Manager**. When Mac says Apple could not verify the app, click **Done**. Do not click **Move to Bin**. Open the Apple menu, choose **System Settings**, then **Privacy & Security**. Scroll to **Security** and click **Open Anyway**. On an older Mac, right-click the app and choose **Open**, then **Open**.
- **Windows:** unzip the download and double-click **Nexera Property Manager**. If Windows says it protected your PC, click **More info**, then **Run anyway**.

Your browser opens. Choose a password. The username is `admin`. Your books are saved in Documents, in the folder **Nexera Property Manager**. Copy that folder when you want a backup.

The sign-in page shows this version number. Quit Nexera from that page before you open a newly downloaded copy. The books stay in that folder.
"""


def newest_section(text):
    parts = text.split("\n## ")
    if len(parts) < 2:
        raise SystemExit("CHANGELOG.md has no version section")
    return "## " + parts[1].strip() + "\n"


def main():
    changelog = pathlib.Path("CHANGELOG.md")
    if not changelog.is_file():
        changelog = pathlib.Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    print(INSTALL)
    print(newest_section(changelog.read_text(encoding="utf-8")))


if __name__ == "__main__":
    sys.exit(main())
