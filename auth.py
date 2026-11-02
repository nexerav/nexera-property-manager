# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password checks, sign-in lockout, and reset tokens.

APP_PASSWORD in the environment is the bootstrap password. A reset stores a
hash in the data file, and that hash is what signs in afterwards, including
after a restart. The raw password and the email token are never written down.

Web reset is refused for the public demo. DEMO_MODE turns it off entirely.
A username of "demo" is also refused unless the operator sets
ALLOW_PASSWORD_RESET, so the demo account cannot be taken over from the browser.
"""

import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage


PBKDF2_ROUNDS = 200_000
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
MAX_FAILURES = 5
LOCK_MINUTES = 15
TOKEN_MINUTES = 30
MAX_RESET_REQUESTS = 3
RESET_WINDOW_MINUTES = 60

LOGGER = logging.getLogger("nexera.auth")


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

DEMO_RESET_MESSAGE = "Password reset is turned off for this demo."
LOCK_MESSAGE = (
    "Too many sign-in attempts. Try again in 15 minutes, or reset the password."
)
GENERIC_RESET_MESSAGE = (
    "If this install can send mail for that username, a reset link is on its way. "
    "The link expires in 30 minutes."
)
PASSWORD_RULE = "Choose a password of at least 10 characters that is not a common placeholder."


class ResetError(Exception):
    """A reset command or form that should stop without changing the password."""


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def demo_mode():
    return env_flag("DEMO_MODE")


def web_reset_blocked(username):
    """True when the browser must not change this install's password."""
    if demo_mode():
        return True
    if (username or "").strip().casefold() == "demo" and not env_flag("ALLOW_PASSWORD_RESET"):
        return True
    return False


def same_secret(left, right):
    return hmac.compare_digest(
        hashlib.sha256(str(left).encode("utf-8")).digest(),
        hashlib.sha256(str(right).encode("utf-8")).digest(),
    )


def password_problem(password, blocked):
    if not isinstance(password, str):
        return PASSWORD_RULE
    if password != password.strip() or any(char in password for char in "\r\n\x00"):
        return PASSWORD_RULE
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        return PASSWORD_RULE
    if password.casefold() in {item.casefold() for item in blocked}:
        return PASSWORD_RULE
    return None


def hash_password(password, salt_hex):
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ROUNDS,
    )
    return digest.hex()


def verify_password(password, salt_hex, expected_hex):
    if not salt_hex or not expected_hex or not isinstance(password, str):
        return False
    try:
        actual = hash_password(password, salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected_hex)


def ensure_auth(data):
    auth = data.get("auth")
    if not isinstance(auth, dict):
        auth = {}
        data["auth"] = auth
    auth.setdefault("password_hash", "")
    auth.setdefault("password_salt", "")
    auth.setdefault("failed_attempts", 0)
    auth.setdefault("locked_until", "")
    auth.setdefault("reset_token_hash", "")
    auth.setdefault("reset_token_expires", "")
    if not isinstance(auth.get("reset_requests"), list):
        auth["reset_requests"] = []
    return auth


def password_is_current(password, auth, env_password):
    if not isinstance(password, str) or len(password) > 1000:
        return False
    if auth.get("password_hash") and auth.get("password_salt"):
        return verify_password(password, auth["password_salt"], auth["password_hash"])
    return same_secret(password, env_password)


def _parse_stamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_active(auth, now):
    deadline = _parse_stamp(auth.get("locked_until"))
    return deadline is not None and now < deadline


def attempt_sign_in(data, username, password, expected_username, env_password, now):
    """Return (ok, error, changed). A lockout rejects even the right password."""
    auth = ensure_auth(data)
    if lock_active(auth, now):
        return False, LOCK_MESSAGE, False
    changed = False
    if auth.get("locked_until"):
        auth["locked_until"] = ""
        auth["failed_attempts"] = 0
        changed = True
    user_ok = same_secret(username or "", expected_username)
    # Hash the offered password either way so a wrong username is not faster.
    pass_ok = password_is_current(password or "", auth, env_password)
    if user_ok and pass_ok:
        if auth.get("failed_attempts") or auth.get("locked_until"):
            auth["failed_attempts"] = 0
            auth["locked_until"] = ""
            changed = True
        return True, "", changed
    auth["failed_attempts"] = int(auth.get("failed_attempts") or 0) + 1
    changed = True
    if auth["failed_attempts"] >= MAX_FAILURES:
        auth["locked_until"] = _stamp(now + timedelta(minutes=LOCK_MINUTES))
        auth["failed_attempts"] = 0
        return False, LOCK_MESSAGE, True
    return False, "Invalid credentials", changed


def apply_new_password(data, password, blocked):
    """Store a new hash and clear lockout plus any outstanding reset link."""
    problem = password_problem(password, blocked)
    if problem:
        return problem
    auth = ensure_auth(data)
    salt = secrets.token_hex(16)
    auth["password_salt"] = salt
    auth["password_hash"] = hash_password(password, salt)
    auth["failed_attempts"] = 0
    auth["locked_until"] = ""
    auth["reset_token_hash"] = ""
    auth["reset_token_expires"] = ""
    return None


def issue_reset_token(data, now):
    raw = secrets.token_urlsafe(32)
    auth = ensure_auth(data)
    auth["reset_token_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    auth["reset_token_expires"] = _stamp(now + timedelta(minutes=TOKEN_MINUTES))
    return raw


def token_status(data, raw, now):
    auth = ensure_auth(data)
    expected = auth.get("reset_token_hash") or ""
    if not expected or not isinstance(raw, str) or not raw:
        return "invalid"
    actual = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual, expected):
        return "invalid"
    expires = _parse_stamp(auth.get("reset_token_expires"))
    if expires is None or now >= expires:
        return "expired"
    return "ok"


def _note_reset_request(auth, now):
    window_start = now - timedelta(minutes=RESET_WINDOW_MINUTES)
    kept = []
    for stamp in auth.get("reset_requests") or []:
        moment = _parse_stamp(stamp)
        if moment is not None and moment >= window_start:
            kept.append(stamp)
    if len(kept) >= MAX_RESET_REQUESTS:
        auth["reset_requests"] = kept
        return False
    kept.append(_stamp(now))
    auth["reset_requests"] = kept
    return True


def smtp_settings():
    host = (os.environ.get("SMTP_HOST") or "").strip()
    sender = (os.environ.get("SMTP_FROM") or "").strip()
    recipient = (os.environ.get("PASSWORD_RESET_EMAIL") or "").strip()
    if not host or not sender or not recipient:
        return None
    try:
        port = int((os.environ.get("SMTP_PORT") or "587").strip())
    except ValueError:
        return None
    if port < 1 or port > 65535:
        return None
    tls_raw = (os.environ.get("SMTP_TLS") or "").strip().lower()
    if tls_raw in {"0", "false", "no", "off"}:
        use_tls = False
    elif tls_raw in {"1", "true", "yes", "on"}:
        use_tls = True
    else:
        use_tls = port != 465
    return {
        "host": host,
        "port": port,
        "sender": sender,
        "recipient": recipient,
        "username": (os.environ.get("SMTP_USERNAME") or "").strip(),
        "password": os.environ.get("SMTP_PASSWORD") or "",
        "ssl": port == 465,
        "tls": use_tls and port != 465,
    }


def deliver_email(settings, subject, body):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["sender"]
    message["To"] = settings["recipient"]
    message.set_content(body)
    if settings["ssl"]:
        client_cm = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=20)
    else:
        client_cm = smtplib.SMTP(settings["host"], settings["port"], timeout=20)
    with client_cm as client:
        client.ehlo()
        if settings["tls"]:
            client.starttls()
            client.ehlo()
        if settings["username"]:
            client.login(settings["username"], settings["password"])
        client.send_message(message)


def email_body(link):
    return (
        "A password reset was requested for Nexera Property Manager.\n\n"
        "Open this link within 30 minutes and choose a new password:\n"
        f"{link}\n\n"
        "If you did not ask for this, ignore this email. "
        "The link can be used once.\n"
    )


def request_reset(data, username, expected_username, now, build_link):
    """Start an email reset. The HTTP response never includes the token."""
    auth = ensure_auth(data)
    if not _note_reset_request(auth, now):
        return GENERIC_RESET_MESSAGE
    if not same_secret((username or "").strip(), expected_username):
        return GENERIC_RESET_MESSAGE
    settings = smtp_settings()
    if settings is None:
        return GENERIC_RESET_MESSAGE
    raw = issue_reset_token(data, now)
    link = build_link(raw)
    try:
        deliver_email(
            settings,
            "Reset your Nexera Property Manager password",
            email_body(link),
        )
    except Exception:
        auth["reset_token_hash"] = ""
        auth["reset_token_expires"] = ""
        LOGGER.warning("Password reset email could not be sent")
    return GENERIC_RESET_MESSAGE


def read_new_password():
    """Read a new password from the environment or an interactive prompt.

    The password is never taken from the command arguments, so it does not
    sit in the shell history.
    """
    if "APP_PASSWORD_RESET" in os.environ:
        supplied = os.environ.get("APP_PASSWORD_RESET") or ""
        if not supplied:
            raise ResetError("APP_PASSWORD_RESET is empty.")
        return supplied
    if not sys.stdin.isatty():
        raise ResetError(
            "Set APP_PASSWORD_RESET for a non-interactive reset, or run this "
            "command in a terminal so it can ask for the password."
        )
    import getpass
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Repeat new password: ")
    if first != second:
        raise ResetError("Those passwords did not match.")
    return first


def cli_reset(argv, load_data, save_data, username, blocked):
    if argv:
        raise ResetError(
            "This command does not take arguments. It asks for the new password, "
            "or reads APP_PASSWORD_RESET from the environment."
        )
    if demo_mode():
        raise ResetError(
            "Password reset is turned off while DEMO_MODE is set. "
            "The demo password cannot be changed this way."
        )
    password = read_new_password()
    data = load_data()
    problem = apply_new_password(data, password, blocked)
    if problem:
        raise ResetError(problem)
    save_data(data)
    print(f"Password updated for {username}. Any sign-in lockout and reset links were cleared.")
    print("The new password is stored in the data file and is used instead of APP_PASSWORD.")
