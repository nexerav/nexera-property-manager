# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Nexera on this computer.

Double-click the app. It keeps the books in Documents, creates its own secret
key, and opens a browser. Nothing here is meant to be typed into a terminal.
A second double-click opens the browser again instead of starting a second copy.
The server listens on this computer only.
"""

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser


APP_FOLDER_NAME = "Nexera Property Manager"
HEALTH_TIMEOUT_SECONDS = 30


def headless():
    """True when nobody is sitting in front of a window, such as a test run."""
    if os.environ.get("NEXERA_NO_BROWSER") == "1":
        return True
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def tell_user(message):
    """Show a short message without a terminal window."""
    logging.error("%s", message)
    if headless():
        sys.stderr.write(message + "\n")
        return
    try:
        if sys.platform == "darwin":
            safe = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'display dialog "%s" buttons {"OK"} default button 1 '
                    'with title "Nexera Property Manager" giving up after 20' % safe,
                ],
                check=False,
            )
            return
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Nexera Property Manager", 0x40)
            return
    except Exception:
        logging.exception("Could not show a message")
    sys.stderr.write(message + "\n")


def choose_data_dir():
    override = (os.environ.get("NEXERA_DATA_DIR") or "").strip()
    if override:
        return os.path.abspath(override)
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        home = os.environ.get("USERPROFILE") or home
    documents = os.path.join(home, "Documents")
    if not os.path.isdir(documents):
        documents = home
    return os.path.join(documents, APP_FOLDER_NAME)


def load_or_create_secret(folder):
    path = os.path.join(folder, "secret_key")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError:
        value = ""
    if len(value) >= 32:
        return value
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
    return value


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def claim_lock(folder):
    """True when this process owns the single running copy."""
    path = os.path.join(folder, "nexera.lock")
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            holder = read_pid(path)
            if process_alive(holder):
                return False
            try:
                os.remove(path)
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    return False


def release_lock(folder):
    path = os.path.join(folder, "nexera.lock")
    if read_pid(path) != os.getpid():
        return
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        os.remove(os.path.join(folder, "port"))
    except OSError:
        pass


def health_ok(base_url):
    try:
        with urllib.request.urlopen(base_url + "health", timeout=1) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TimeoutError):
        return False
    return body.get("status") == "ok"


def running_url(folder):
    path = os.path.join(folder, "port")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            port = int(handle.read().strip())
    except (OSError, ValueError):
        return None
    if port <= 0 or port > 65535:
        return None
    base = "http://127.0.0.1:%s/" % port
    if health_ok(base):
        return base
    return None


def wait_for_url(folder, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = running_url(folder)
        if url:
            return url
        time.sleep(0.2)
    return None


def note(folder, text):
    path = os.path.join(folder, "startup.txt")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def write_port(folder, port):
    path = os.path.join(folder, "port")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(port))


def prepare_environment(folder):
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.environ["NEXERA_DESKTOP"] = "1"
    os.environ["NEXERA_DATA_DIR"] = folder
    os.environ["DATA_FILE"] = os.path.join(folder, "rental_data.json")
    os.environ["SECRET_KEY"] = load_or_create_secret(folder)
    os.environ.pop("APP_PASSWORD", None)
    os.environ.pop("FLASK_DEBUG", None)
    os.environ.pop("DEMO_MODE", None)
    # A copied environment must not make Werkzeug treat this as its reloader.
    os.environ.pop("WERKZEUG_RUN_MAIN", None)
    os.environ.pop("WERKZEUG_SERVER_FD", None)


def open_page(url):
    # Set by the test suite so a run does not open a browser window.
    if os.environ.get("NEXERA_NO_BROWSER") == "1":
        return
    webbrowser.open(url)


def open_browser_when_ready(folder, base_url):
    if wait_for_url(folder, HEALTH_TIMEOUT_SECONDS):
        open_page(base_url)
        return
    logging.error("The local page did not answer at %s", base_url)
    tell_user(
        "Nexera could not open. The details are in nexera.log inside the "
        "Nexera Property Manager folder in Documents."
    )


def serve(folder):
    """Listen on this computer and record the port after the socket is bound.

    The socket is bound with an address tuple. Looking the name up first can
    stall for a long time on some Macs, including GitHub's runners.
    """
    import socketserver
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

    # Imported after the environment is set, so the secret and data folder stick.
    import app as application

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, fmt, *args):
            return

    class ThreadedServer(socketserver.ThreadingMixIn, WSGIServer):
        daemon_threads = True
        allow_reuse_address = True

    note(folder, "import-ok")
    server = ThreadedServer(("127.0.0.1", 0), QuietHandler)
    server.set_app(application.app)
    port = server.server_address[1]
    write_port(folder, port)
    base_url = "http://127.0.0.1:%s/" % port
    note(folder, "listening %s" % port)
    logging.info("Opening %s", base_url)
    opener = threading.Thread(
        target=open_browser_when_ready,
        args=(folder, base_url),
        daemon=True,
    )
    opener.start()
    server.serve_forever()


def run():
    folder = choose_data_dir()
    os.makedirs(folder, mode=0o700, exist_ok=True)
    note(folder, "start")
    logging.basicConfig(
        filename=os.path.join(folder, "nexera.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    already = running_url(folder)
    if already:
        open_page(already)
        return
    if not claim_lock(folder):
        url = wait_for_url(folder, HEALTH_TIMEOUT_SECONDS)
        if url:
            open_page(url)
            return
        tell_user(
            "Nexera is already opening. If the page does not appear, quit "
            "Nexera from the sign-in page and open it again."
        )
        return
    try:
        prepare_environment(folder)
        note(folder, "env-ready")
        serve(folder)
    finally:
        release_lock(folder)


def main():
    try:
        run()
    except Exception:
        logging.exception("Nexera stopped")
        sys.stderr.write(traceback.format_exc())
        tell_user(
            "Nexera could not start. The details are in nexera.log inside the "
            "Nexera Property Manager folder in Documents."
        )
        sys.exit(1)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
