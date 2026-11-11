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


def package(system):
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    PACKAGE.mkdir(parents=True)
    shutil.copy(ROOT / "packaging" / "Read me first.txt", PACKAGE / "Read me first.txt")
    if system == "Darwin":
        shutil.copytree(DIST / f"{NAME}.app", PACKAGE / f"{NAME}.app", symlinks=True)
        zip_name = "Nexera-Property-Manager-mac.zip"
    else:
        shutil.copy(DIST / f"{NAME}.exe", PACKAGE / f"{NAME}.exe")
        zip_name = "Nexera-Property-Manager-windows.zip"
    DIST.mkdir(exist_ok=True)
    archive = DIST / zip_name
    if archive.exists():
        archive.unlink()
    shutil.make_archive(str(archive.with_suffix("")), "zip", PACKAGE)
    print(archive)


def main():
    package(build())


if __name__ == "__main__":
    main()
