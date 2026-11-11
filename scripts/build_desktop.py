#!/usr/bin/env python3
# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the Mac or Windows download.

PyInstaller is only a build tool. The Docker app does not install it.
Run this on macOS to make the Mac zip, and on Windows to make the Windows zip.
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE = ROOT / "build" / "package"
NAME = "Nexera Property Manager"


def make_icns():
    png = ROOT / "static" / "favicon.png"
    if platform.system() != "Darwin" or not png.is_file():
        return None
    iconset = ROOT / "build" / "icon.iconset"
    destination = ROOT / "build" / "nexera.icns"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    for size in (16, 32, 128, 256, 512):
        subprocess.run(
            ["sips", "-z", str(size), str(size), str(png), "--out", str(iconset / f"icon_{size}x{size}.png")],
            check=True,
        )
        subprocess.run(
            [
                "sips", "-z", str(size * 2), str(size * 2), str(png),
                "--out", str(iconset / f"icon_{size}x{size}@2x.png"),
            ],
            check=True,
        )
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(destination)], check=True)
    return destination


def build():
    system = platform.system()
    if system not in {"Darwin", "Windows"}:
        sys.exit("Desktop downloads are built on macOS and Windows.")
    separator = ";" if system == "Windows" else ":"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", NAME,
        "--add-data", f"templates{separator}templates",
        "--add-data", f"static{separator}static",
        "--hidden-import", "app",
        "--hidden-import", "auth",
        "--hidden-import", "demo_data",
        "--hidden-import", "exports",
        "--hidden-import", "labels",
        "--hidden-import", "version",
        "--collect-all", "reportlab",
        "--collect-all", "openpyxl",
        "--collect-all", "PIL",
    ]
    if system == "Windows":
        command.append("--onefile")
        icon = ROOT / "static" / "favicon.ico"
        if icon.is_file():
            command.extend(["--icon", str(icon)])
    else:
        command.extend(["--osx-bundle-identifier", "com.nexerav.propertymanager"])
        icon = make_icns()
        if icon is not None:
            command.extend(["--icon", str(icon)])
    command.append(str(ROOT / "desktop.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    return system


def make_zip(folder, archive):
    """Zip a finished download.

    Python's zip follows a shortcut and stores a copy. A Mac app is full of
    shortcuts. After that zip is opened, macOS says the app is damaged.
    ditto keeps the shortcuts.
    """
    folder = Path(folder)
    archive = Path(archive)
    if archive.exists():
        archive.unlink()
    if platform.system() == "Darwin":
        subprocess.run(
            ["ditto", "-c", "-k", "--norsrc", str(folder), str(archive)],
            check=True,
        )
        return
    shutil.make_archive(str(archive.with_suffix("")), "zip", folder)


def mac_zip_keeps_shortcuts(archive):
    """True when the zip still contains at least one shortcut."""
    import zipfile
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                return True
    return False


def package(system):
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    PACKAGE.mkdir(parents=True)
    shutil.copy(ROOT / "packaging" / "Read me first.txt", PACKAGE / "Read me first.txt")
    if system == "Darwin":
        app_path = PACKAGE / f"{NAME}.app"
        shutil.copytree(DIST / f"{NAME}.app", app_path, symlinks=True)
        # Copying the app clears the signature PyInstaller just wrote.
        subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", str(app_path)],
            check=True,
        )
        zip_name = "Nexera-Property-Manager-mac.zip"
    else:
        shutil.copy(DIST / f"{NAME}.exe", PACKAGE / f"{NAME}.exe")
        zip_name = "Nexera-Property-Manager-windows.zip"
    DIST.mkdir(exist_ok=True)
    archive = DIST / zip_name
    make_zip(PACKAGE, archive)
    if system == "Darwin" and not mac_zip_keeps_shortcuts(archive):
        sys.exit("The Mac zip dropped the shortcuts inside the app. macOS would call it damaged.")
    print(archive)


def main():
    package(build())


if __name__ == "__main__":
    main()
