#!/usr/bin/env python3
# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Nexera Property Manager
Self-hosted property books for landlords. Powered by Nexera Ventures.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape
import os
import json
import sys
import threading
import uuid
from dotenv import load_dotenv

import auth
import demo_data
import exports
import labels

load_dotenv()

# Published placeholders are rejected so a fresh checkout cannot sign in
# until the operator chooses both values.
INSECURE_SECRET_KEYS = frozenset({
    "dev-secret-change-me",
    "change-me-in-production-please",
    "your-secret-key-change-this",
    "secret",
    "changeme",
})
INSECURE_PASSWORDS = frozenset({
    "admin123",
    "password",
    "changeme",
})


def require_setting(name, value, blocked):
    cleaned = (value or "").strip()
    if not cleaned or cleaned.casefold() in blocked:
        raise SystemExit(
            f"Refusing to start: set a unique {name} in the environment or .env file. "
            "This application has no default password or secret key."
        )
    return cleaned


def debug_requested():
    return os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def waitlist_url():
    raw = (os.environ.get("WAITLIST_URL") or "https://www.nexerav.com").strip()
    if raw.startswith("https://") or raw.startswith("http://"):
        return raw
    return "https://www.nexerav.com"


def brand_context():
    return {
        "premium_message": PREMIUM_DESCRIPTION,
        "premium_description": PREMIUM_DESCRIPTION,
        "waitlist_url": waitlist_url(),
        "demo_mode": auth.demo_mode(),
        "expense_choices": labels.EXPENSE_CHOICES,
        "category_aliases": labels.LEGACY_CATEGORIES,
    }


app = Flask(__name__)
app.jinja_env.filters["zar"] = labels.format_zar
app.jinja_env.filters["qty"] = labels.format_qty
app.secret_key = require_setting("SECRET_KEY", os.environ.get("SECRET_KEY"), INSECURE_SECRET_KEYS)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DATA_FILE = os.environ.get("DATA_FILE", os.path.join("data", "rental_data.json"))

VALID_USERNAME = (os.environ.get("APP_USERNAME") or "admin").strip() or "admin"
VALID_PASSWORD = require_setting("APP_PASSWORD", os.environ.get("APP_PASSWORD"), INSECURE_PASSWORDS)

PREMIUM_DESCRIPTION = (
    "Premium adds instant invoicing, invoices emailed straight from the platform, "
    "a property deal pipeline, and AI agents that handle the admin."
)
PREMIUM_FEATURES = [
    "Instant invoicing",
    "Invoices emailed from the platform",
    "Property deal pipeline",
    "AI agents for the admin",
]
PREMIUM_MESSAGE = PREMIUM_DESCRIPTION

PROPERTY_KINDS = ["Residential", "Commercial", "Overhead"]
INCOME_TYPES = ["Rent", "Recovery", "Other"]
RECOVERY_CATEGORIES = [
    "Water",
    "Sewerage",
    "Electricity",
    "Common Property Electricity",
    "Refuse",
    "Municipal Utility Charge",
    "Carport",
    "Other Utility",
]
EXPENSE_CATEGORIES = [name for name, _help in labels.EXPENSE_CHOICES]
INVOICE_STATUSES = ["Draft", "Issued", "Outstanding", "Overdue", "Paid"]
LOGO_NAMES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.gif", "logo.webp")
TEXT_SETTINGS = {
    "organisation_name": 160,
    "contact_name": 120,
    "address": 500,
    "phone": 40,
    "email": 120,
    "registration_number": 80,
    "payment_details": 1000,
}
ISSUE_TYPES = [
    "Plumbing",
    "Electrical",
    "Appliance",
    "Structural",
    "Heating/Cooling",
    "Security",
    "Pest control",
    "Garden/Exterior",
    "Other",
]
MAINT_STATUSES = ["Open", "In progress", "Done"]
URGENCIES = ["Low", "Medium", "High", "Emergency"]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api") or request.path == "/premium":
                return jsonify({"error": "Sign in required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# One worker, several threads. This lock keeps a slow disk read from piling up
# writes, and lets the page answer instead of waiting forever.
_data_lock = threading.Lock()


def uses_data(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _data_lock.acquire(timeout=8):
            return jsonify({
                "error": "The data file is busy. Wait a moment and refresh.",
            }), 503
        try:
            return f(*args, **kwargs)
        finally:
            _data_lock.release()
    return decorated


def new_id():
    return uuid.uuid4().hex[:12]


def clean(value, limit):
    text = "" if value is None else str(value).strip()
    return text[:limit]


def valid_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def money(value):
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    if amount < 0 or amount > 1_000_000_000_000:
        return None
    return amount


def optional_money(value):
    if value is None or value == "":
        return None
    return money(value)


def payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def empty_settings():
    settings = {"logo": ""}
    for key in TEXT_SETTINGS:
        settings[key] = ""
    return settings


def seed_data():
    return {
        "properties": [
            {
                "id": "1",
                "name": "Unit A - 123 Main Street",
                "address": "123 Main Street, City",
                "kind": "Residential",
                "monthly_rent": None,
                "notes": "",
            },
            {
                "id": "2",
                "name": "Unit B - 456 Oak Avenue",
                "address": "456 Oak Avenue, City",
                "kind": "Residential",
                "monthly_rent": None,
                "notes": "",
            },
            {
                "id": "3",
                "name": "Company Expenses",
                "address": "Portfolio overhead",
                "kind": "Overhead",
                "monthly_rent": None,
                "notes": "Use this property for costs that are not tied to one unit.",
            },
        ],
        "income": [],
        "expenses": [],
        "maintenance": [],
        "invoices": [],
        "settings": empty_settings(),
    }


def normalize(data):
    if not isinstance(data, dict):
        data = {}
    data.setdefault("properties", [])
    data.setdefault("income", [])
    data.setdefault("expenses", [])
    data.setdefault("maintenance", [])
    data.setdefault("invoices", [])
    if not isinstance(data.get("settings"), dict):
        data["settings"] = {}
    for key in empty_settings():
        data["settings"].setdefault(key, "")

    for prop in data["properties"]:
        prop.setdefault("address", "")
        prop.setdefault("notes", "")
        if prop.get("kind") not in PROPERTY_KINDS:
            prop["kind"] = "Overhead" if prop.get("name") == "Company Expenses" else "Residential"
        rent = prop.get("monthly_rent")
        prop["monthly_rent"] = None if rent in (None, "") else rent

    for entry in data["income"]:
        entry.setdefault("description", "")
        entry.setdefault("tenant", "")
        entry.setdefault("date", "")
        if entry.get("income_type") not in INCOME_TYPES:
            entry["income_type"] = "Rent"
        entry.setdefault("recovery_category", "")

    for entry in data["expenses"]:
        entry.setdefault("description", "")
        entry.setdefault("vendor", "")
        entry.setdefault("date", "")
        entry.setdefault("category", "Other")

    for entry in data["maintenance"]:
        entry.setdefault("description", "")
        entry.setdefault("date", "")
        entry.setdefault("tenant_name", "")
        entry.setdefault("contact_phone", "")
        entry.setdefault("vendor", "")
        entry.setdefault("notes", "")
        entry.setdefault("cost", None)
        entry.setdefault("expense_id", None)
        if entry.get("issue_type") not in ISSUE_TYPES:
            entry["issue_type"] = "Other"
        if entry.get("urgency") not in URGENCIES:
            entry["urgency"] = "Medium"
        if entry.get("status") not in MAINT_STATUSES:
            entry["status"] = "Open"

    for invoice in data["invoices"]:
        invoice.setdefault("number", "")
        invoice.setdefault("tenant", "")
        invoice.setdefault("date", "")
        invoice.setdefault("due_date", "")
        invoice.setdefault("notes", "")
        invoice.setdefault("line_items", [])
        if invoice.get("status") not in INVOICE_STATUSES:
            invoice["status"] = "Draft"
    return data


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as handle:
            return normalize(json.load(handle))
    return normalize(seed_data())


def save_data(data):
    folder = os.path.dirname(DATA_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = DATA_FILE + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(normalize(data), handle, indent=2)
        handle.write("\n")
    os.replace(temporary, DATA_FILE)


def data_dir():
    folder = os.path.dirname(DATA_FILE) or "."
    os.makedirs(folder, exist_ok=True)
    return folder


def find_logo():
    folder = os.path.dirname(DATA_FILE) or "."
    for name in LOGO_NAMES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def public_settings(data):
    settings = data.get("settings") or {}
    visible = {key: settings.get(key) or "" for key in TEXT_SETTINGS}
    visible["logo"] = bool(find_logo())
    return visible


def page_brand():
    try:
        data = load_data()
    except (OSError, json.JSONDecodeError, TypeError):
        data = {"settings": empty_settings()}
    brand = public_settings(data)
    return brand


def read_settings(body, existing):
    updated = dict(existing or empty_settings())
    for key, limit in TEXT_SETTINGS.items():
        if key in body:
            updated[key] = clean(body.get(key), limit)
    updated["logo"] = (existing or {}).get("logo") or ""
    return updated


def pdf_money(value):
    return labels.format_zar(value)


def pdf_qty(value):
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.2f}"


def pdf_paragraph(text, style):
    from reportlab.platypus import Paragraph
    safe = escape(text or "").replace("\n", "<br/>")
    return Paragraph(safe or " ", style)


def logo_flowable():
    path = find_logo()
    if not path:
        return None
    try:
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image
        reader = ImageReader(path)
        width, height = reader.getSize()
        if not width or not height:
            return None
        scale = min((42 * mm) / float(width), (18 * mm) / float(height))
        return Image(path, width=float(width) * scale, height=float(height) * scale)
    except Exception:
        return None


def build_invoice_pdf(invoice, prop, org):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=invoice.get("number") or "Invoice",
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("org", parent=styles["Heading2"], textColor=colors.HexColor("#1a365d"), spaceAfter=2)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=13, textColor=colors.HexColor("#1a202c"))
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#4a5568"), fontSize=9)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    right_title = ParagraphStyle("right-title", parent=name_style, alignment=TA_RIGHT)
    small = ParagraphStyle("small", parent=muted, fontSize=8, leading=11)

    left = []
    mark = logo_flowable()
    if mark:
        left.append(mark)
        left.append(Spacer(1, 2 * mm))
    title = org.get("organisation_name") or "Nexera Property Manager"
    left.append(pdf_paragraph(title, name_style))
    details = []
    if org.get("contact_name"):
        details.append(org["contact_name"])
    if org.get("address"):
        details.append(org["address"])
    contact = " · ".join(part for part in (org.get("phone"), org.get("email")) if part)
    if contact:
        details.append(contact)
    if org.get("registration_number"):
        details.append(org["registration_number"])
    if details:
        left.append(pdf_paragraph("\n".join(details), body))

    meta = [pdf_paragraph(invoice.get("number") or "Invoice", right_title)]
    meta.append(pdf_paragraph(invoice.get("status") or "", right))
    meta.append(pdf_paragraph("Date " + (invoice.get("date") or ""), right))
    if invoice.get("due_date"):
        meta.append(pdf_paragraph("Due " + invoice["due_date"], right))
    header = Table([[left, meta]], colWidths=[110 * mm, 64 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    bill = [pdf_paragraph("Bill to", muted)]
    bill.append(pdf_paragraph(invoice.get("tenant") or "", name_style))
    if prop:
        place = prop.get("name") or ""
        if prop.get("address"):
            place = place + "\n" + prop["address"]
        if place:
            bill.append(pdf_paragraph(place, body))

    rows = [[
        pdf_paragraph("Description", ParagraphStyle("head", parent=body, textColor=colors.white, fontName="Helvetica-Bold")),
        pdf_paragraph("Qty", ParagraphStyle("head-r", parent=right, textColor=colors.white, fontName="Helvetica-Bold")),
        pdf_paragraph("Unit price", ParagraphStyle("head-r2", parent=right, textColor=colors.white, fontName="Helvetica-Bold")),
        pdf_paragraph("Amount", ParagraphStyle("head-r3", parent=right, textColor=colors.white, fontName="Helvetica-Bold")),
    ]]
    for item in invoice.get("line_items") or []:
        rows.append([
            pdf_paragraph(item.get("description") or "", body),
            pdf_paragraph(pdf_qty(item.get("quantity") or 0), right),
            pdf_paragraph(pdf_money(item.get("unit_price") or 0), right),
            pdf_paragraph(pdf_money(item.get("amount") or 0), right),
        ])
    rows.append([
        "",
        "",
        pdf_paragraph("Total", ParagraphStyle("total", parent=right, fontName="Helvetica-Bold")),
        pdf_paragraph(pdf_money(invoice.get("total") or 0), ParagraphStyle("total-amt", parent=right, fontName="Helvetica-Bold")),
    ])
    table = Table(rows, colWidths=[90 * mm, 22 * mm, 31 * mm, 31 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f7fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#1a365d")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    story = [header, Spacer(1, 8 * mm), *bill, Spacer(1, 6 * mm), table]
    if invoice.get("notes"):
        story.extend([Spacer(1, 6 * mm), pdf_paragraph("Notes", muted), pdf_paragraph(invoice["notes"], body)])
    if org.get("payment_details"):
        story.extend([Spacer(1, 6 * mm), pdf_paragraph("Payment details", muted), pdf_paragraph(org["payment_details"], body)])
    story.extend([Spacer(1, 10 * mm), pdf_paragraph("Nexera Property Manager", small)])
    document.build(story)
    buffer.seek(0)
    return buffer


def image_kind(blob):
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if blob.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(blob) >= 12 and blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return "webp"
    return None


def find_item(items, item_id):
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def property_exists(data, property_id):
    return find_item(data["properties"], property_id) is not None


def request_period():
    """Return (start, end) inclusive dates, or (None, None) for all time.

    A bad custom range returns the string "invalid".
    """
    period = request.args.get("period", "all")
    today = datetime.now().date()
    if period == "month":
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(days=1)
        return start.isoformat(), end.isoformat()
    if period == "year":
        return f"{today.year}-01-01", f"{today.year}-12-31"
    if period == "last12":
        end = today
        start = end - timedelta(days=365)
        return start.isoformat(), end.isoformat()
    if period == "custom":
        start = request.args.get("start", "")
        end = request.args.get("end", "")
        if not valid_date(start) or not valid_date(end) or start > end:
            return "invalid"
        return start, end
    return None, None


def in_period(date_value, start, end):
    if start is None and end is None:
        return True
    if not isinstance(date_value, str):
        return False
    if start and date_value < start:
        return False
    if end and date_value > end:
        return False
    return True


def selected_property():
    property_id = request.args.get("property_id", "").strip()
    return property_id or None


def filtered_rows(rows, start, end, property_id):
    chosen = []
    for row in rows:
        if property_id and row.get("property_id") != property_id:
            continue
        if not in_period(row.get("date"), start, end):
            continue
        chosen.append(row)
    chosen.sort(key=lambda row: (row.get("date") or "", row.get("id") or ""), reverse=True)
    return chosen


@app.route("/favicon.ico")
def favicon():
    return send_file(
        os.path.join(app.root_path, "static", "favicon.ico"),
        mimetype="image/x-icon",
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok", "version": "oss-1.1"})


def login_page(error=None):
    brand = page_brand()
    return render_template(
        "login.html",
        error=error,
        logo=brand["logo"],
        organisation_name=brand["organisation_name"],
        show_reset=not auth.web_reset_blocked(VALID_USERNAME),
    )


def reset_allowed():
    if auth.web_reset_blocked(VALID_USERNAME):
        return False
    return True


def public_base():
    configured = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    return request.url_root.rstrip("/")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not _data_lock.acquire(timeout=8):
            return login_page("The data file is busy. Wait a moment and try again.")
        try:
            data = load_data()
            ok, error, changed = auth.attempt_sign_in(
                data,
                username,
                password,
                VALID_USERNAME,
                VALID_PASSWORD,
                auth.utc_now(),
            )
            if changed:
                save_data(data)
        finally:
            _data_lock.release()
        if ok:
            session.clear()
            session["logged_in"] = True
            session["username"] = VALID_USERNAME
            return redirect(url_for("dashboard"))
        return login_page(error)
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return login_page()


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if not reset_allowed():
        return auth.DEMO_RESET_MESSAGE, 403
    brand = page_brand()
    message = None
    mail_ready = auth.smtp_settings() is not None
    if request.method == "POST" and mail_ready:
        if not _data_lock.acquire(timeout=8):
            message = "The data file is busy. Wait a moment and try again."
        else:
            try:
                data = load_data()
                message = auth.request_reset(
                    data,
                    request.form.get("username", ""),
                    VALID_USERNAME,
                    auth.utc_now(),
                    lambda token: public_base() + "/reset/" + token,
                )
                save_data(data)
            finally:
                _data_lock.release()
    return render_template(
        "forgot.html",
        logo=brand["logo"],
        organisation_name=brand["organisation_name"],
        mail_ready=mail_ready,
        message=message,
    )


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_with_token(token):
    if not reset_allowed():
        return auth.DEMO_RESET_MESSAGE, 403
    if not isinstance(token, str) or len(token) > 200:
        token = ""
    brand = page_brand()
    now = auth.utc_now()
    error = None
    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if new_password != confirm:
            error = "Those passwords do not match."
        elif not _data_lock.acquire(timeout=8):
            error = "The data file is busy. Wait a moment and try again."
        else:
            try:
                data = load_data()
                status = auth.token_status(data, token, now)
                if status != "ok":
                    error = "This reset link is not valid. Ask for a new one, or reset the password from the server."
                    token = ""
                else:
                    problem = auth.apply_new_password(data, new_password, INSECURE_PASSWORDS)
                    if problem:
                        error = problem
                    else:
                        save_data(data)
                        session.clear()
                        session["logged_in"] = True
                        session["username"] = VALID_USERNAME
                        return redirect(url_for("dashboard"))
            finally:
                _data_lock.release()
    else:
        if not _data_lock.acquire(timeout=8):
            error = "The data file is busy. Wait a moment and try again."
        else:
            try:
                data = load_data()
                if auth.token_status(data, token, now) != "ok":
                    error = "This reset link is not valid. Ask for a new one, or reset the password from the server."
                    token = ""
            finally:
                _data_lock.release()
    response = render_template(
        "reset.html",
        logo=brand["logo"],
        organisation_name=brand["organisation_name"],
        error=error,
        token=token,
    )
    # The token is in the address. Don't let the browser send it onward.
    rendered = app.make_response(response)
    rendered.headers["Referrer-Policy"] = "no-referrer"
    rendered.headers["Cache-Control"] = "no-store"
    return rendered


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    brand = page_brand()
    return render_template(
        "dashboard.html",
        logo=brand["logo"],
        organisation_name=brand["organisation_name"],
        allow_password_change=reset_allowed(),
        **brand_context(),
    )


@app.route("/api/options")
@login_required
def api_options():
    return jsonify({
        "property_kinds": PROPERTY_KINDS,
        "income_types": INCOME_TYPES,
        "recovery_categories": RECOVERY_CATEGORIES,
        "expense_categories": EXPENSE_CATEGORIES,
        "issue_types": ISSUE_TYPES,
        "maintenance_statuses": MAINT_STATUSES,
        "urgencies": URGENCIES,
    })


@app.route("/api/summary")
@login_required
@uses_data
def api_summary():
    bounds = request_period()
    if bounds == "invalid":
        return jsonify({"error": "Choose a start date and an end date"}), 400
    start, end = bounds
    property_id = selected_property()
    data = load_data()
    properties = data["properties"]
    if property_id:
        properties = [prop for prop in properties if prop["id"] == property_id]

    income_rows = filtered_rows(data["income"], start, end, property_id)
    expense_rows = filtered_rows(data["expenses"], start, end, property_id)
    total_income = round(sum(row["amount"] for row in income_rows), 2)
    total_expenses = round(sum(row["amount"] for row in expense_rows), 2)
    rent = round(sum(row["amount"] for row in income_rows if row.get("income_type") == "Rent"), 2)
    other_income = round(total_income - rent, 2)

    by_property = []
    for prop in data["properties"]:
        if property_id and prop["id"] != property_id:
            continue
        prop_income = round(sum(
            row["amount"] for row in income_rows if row.get("property_id") == prop["id"]
        ), 2)
        prop_expenses = round(sum(
            row["amount"] for row in expense_rows if row.get("property_id") == prop["id"]
        ), 2)
        by_property.append({
            "id": prop["id"],
            "name": prop["name"],
            "income": prop_income,
            "expenses": prop_expenses,
            "net": round(prop_income - prop_expenses, 2),
        })

    categories = {}
    for row in expense_rows:
        label = labels.category_label(row.get("category") or "Other")
        categories[label] = round(categories.get(label, 0) + row["amount"], 2)
    by_category = [
        {"category": label, "amount": amount}
        for label, amount in sorted(categories.items(), key=lambda item: item[1], reverse=True)
    ]

    open_jobs = [
        row for row in data["maintenance"]
        if row.get("status") != "Done" and (not property_id or row.get("property_id") == property_id)
    ]
    return jsonify({
        "income": total_income,
        "rent": rent,
        "other_income": other_income,
        "expenses": total_expenses,
        "net": round(total_income - total_expenses, 2),
        "properties": len(properties),
        "open_maintenance": len(open_jobs),
        "by_property": by_property,
        "by_category": by_category,
        "period": {"start": start, "end": end},
    })


@app.route("/api/properties", methods=["GET", "POST"])
@login_required
@uses_data
def api_properties():
    data = load_data()
    if request.method == "GET":
        return jsonify(data["properties"])

    body = payload()
    name = clean(body.get("name"), 120)
    if not name:
        return jsonify({"error": "Name is required"}), 400
    kind = body.get("kind") or "Residential"
    if kind not in PROPERTY_KINDS:
        return jsonify({"error": "Choose a property type"}), 400
    rent = optional_money(body.get("monthly_rent"))
    if body.get("monthly_rent") not in (None, "") and rent is None:
        return jsonify({"error": "Monthly rent must be a positive number"}), 400
    prop = {
        "id": new_id(),
        "name": name,
        "address": clean(body.get("address"), 200),
        "kind": kind,
        "monthly_rent": rent,
        "notes": clean(body.get("notes"), 2000),
    }
    data["properties"].append(prop)
    save_data(data)
    return jsonify(prop), 201


@app.route("/api/properties/<property_id>", methods=["PUT", "DELETE"])
@login_required
@uses_data
def api_property(property_id):
    data = load_data()
    prop = find_item(data["properties"], property_id)
    if prop is None:
        return jsonify({"error": "Property not found"}), 404

    if request.method == "DELETE":
        data["properties"] = [item for item in data["properties"] if item["id"] != property_id]
        data["income"] = [item for item in data["income"] if item.get("property_id") != property_id]
        data["expenses"] = [item for item in data["expenses"] if item.get("property_id") != property_id]
        data["maintenance"] = [item for item in data["maintenance"] if item.get("property_id") != property_id]
        data["invoices"] = [item for item in data["invoices"] if item.get("property_id") != property_id]
        save_data(data)
        return jsonify({"message": "Property deleted"})

    body = payload()
    if "name" in body:
        name = clean(body.get("name"), 120)
        if not name:
            return jsonify({"error": "Name is required"}), 400
        prop["name"] = name
    if "address" in body:
        prop["address"] = clean(body.get("address"), 200)
    if "kind" in body:
        if body.get("kind") not in PROPERTY_KINDS:
            return jsonify({"error": "Choose a property type"}), 400
        prop["kind"] = body["kind"]
    if "monthly_rent" in body:
        rent = optional_money(body.get("monthly_rent"))
        if body.get("monthly_rent") not in (None, "") and rent is None:
            return jsonify({"error": "Monthly rent must be a positive number"}), 400
        prop["monthly_rent"] = rent
    if "notes" in body:
        prop["notes"] = clean(body.get("notes"), 2000)
    save_data(data)
    return jsonify(prop)


def read_recovery(body, income_type):
    if income_type != "Recovery":
        return "", None
    category = clean(body.get("recovery_category"), 80)
    if category not in RECOVERY_CATEGORIES:
        return None, "Choose a recovery type"
    return category, None


def read_transaction(body, existing=None):
    amount = money(body.get("amount", existing.get("amount") if existing else None))
    if amount is None:
        return None, "Amount must be zero or more"
    date_value = body.get("date", existing.get("date") if existing else None)
    if not date_value:
        date_value = datetime.now().strftime("%Y-%m-%d")
    if not valid_date(date_value):
        return None, "Use a real date"
    property_id = body.get("property_id", existing.get("property_id") if existing else None)
    if not property_id:
        return None, "Choose a property"
    return {
        "amount": amount,
        "date": date_value,
        "property_id": property_id,
        "description": clean(body.get("description", existing.get("description") if existing else ""), 500),
    }, None


@app.route("/api/income", methods=["GET", "POST"])
@login_required
@uses_data
def api_income():
    data = load_data()
    if request.method == "GET":
        bounds = request_period()
        if bounds == "invalid":
            return jsonify({"error": "Choose a start date and an end date"}), 400
        start, end = bounds
        return jsonify(filtered_rows(data["income"], start, end, selected_property()))

    body = payload()
    fields, error = read_transaction(body)
    if error:
        return jsonify({"error": error}), 400
    if not property_exists(data, fields["property_id"]):
        return jsonify({"error": "Property not found"}), 400
    income_type = body.get("income_type") or "Rent"
    if income_type not in INCOME_TYPES:
        return jsonify({"error": "Choose an income type"}), 400
    recovery, recovery_error = read_recovery(body, income_type)
    if recovery_error:
        return jsonify({"error": recovery_error}), 400
    entry = {
        "id": new_id(),
        **fields,
        "tenant": clean(body.get("tenant"), 120),
        "income_type": income_type,
        "recovery_category": recovery,
    }
    data["income"].append(entry)
    save_data(data)
    return jsonify(entry), 201


@app.route("/api/income/<entry_id>", methods=["PUT", "DELETE"])
@login_required
@uses_data
def api_income_item(entry_id):
    data = load_data()
    entry = find_item(data["income"], entry_id)
    if entry is None:
        return jsonify({"error": "Income record not found"}), 404
    if request.method == "DELETE":
        data["income"] = [item for item in data["income"] if item["id"] != entry_id]
        save_data(data)
        return jsonify({"message": "Income deleted"})

    body = payload()
    fields, error = read_transaction(body, entry)
    if error:
        return jsonify({"error": error}), 400
    if not property_exists(data, fields["property_id"]):
        return jsonify({"error": "Property not found"}), 400
    income_type = body.get("income_type", entry.get("income_type"))
    if income_type not in INCOME_TYPES:
        return jsonify({"error": "Choose an income type"}), 400
    recovery, recovery_error = read_recovery(body, income_type)
    if recovery_error:
        return jsonify({"error": recovery_error}), 400
    entry.update(fields)
    entry["tenant"] = clean(body.get("tenant", entry.get("tenant")), 120)
    entry["income_type"] = income_type
    entry["recovery_category"] = recovery
    save_data(data)
    return jsonify(entry)


@app.route("/api/expenses", methods=["GET", "POST"])
@login_required
@uses_data
def api_expenses():
    data = load_data()
    if request.method == "GET":
        bounds = request_period()
        if bounds == "invalid":
            return jsonify({"error": "Choose a start date and an end date"}), 400
        start, end = bounds
        rows = []
        for row in filtered_rows(data["expenses"], start, end, selected_property()):
            shown = dict(row)
            shown["category"] = labels.category_label(shown.get("category"))
            rows.append(shown)
        return jsonify(rows)

    body = payload()
    fields, error = read_transaction(body)
    if error:
        return jsonify({"error": error}), 400
    if not property_exists(data, fields["property_id"]):
        return jsonify({"error": "Property not found"}), 400
    category = clean(body.get("category") or "Other", 80)
    if not category:
        return jsonify({"error": "Choose a category"}), 400
    entry = {
        "id": new_id(),
        **fields,
        "category": category,
        "vendor": clean(body.get("vendor"), 120),
    }
    data["expenses"].append(entry)
    save_data(data)
    return jsonify(entry), 201


@app.route("/api/expenses/<entry_id>", methods=["PUT", "DELETE"])
@login_required
@uses_data
def api_expense_item(entry_id):
    data = load_data()
    entry = find_item(data["expenses"], entry_id)
    if entry is None:
        return jsonify({"error": "Expense record not found"}), 404
    if request.method == "DELETE":
        data["expenses"] = [item for item in data["expenses"] if item["id"] != entry_id]
        for job in data["maintenance"]:
            if job.get("expense_id") == entry_id:
                job["expense_id"] = None
        save_data(data)
        return jsonify({"message": "Expense deleted"})

    body = payload()
    fields, error = read_transaction(body, entry)
    if error:
        return jsonify({"error": error}), 400
    if not property_exists(data, fields["property_id"]):
        return jsonify({"error": "Property not found"}), 400
    category = clean(body.get("category", entry.get("category")), 80)
    if not category:
        return jsonify({"error": "Choose a category"}), 400
    entry.update(fields)
    entry["category"] = category
    entry["vendor"] = clean(body.get("vendor", entry.get("vendor")), 120)
    save_data(data)
    return jsonify(entry)


def read_maintenance(body, existing=None):
    description = clean(
        body.get("description", existing.get("description") if existing else ""),
        2000,
    )
    if not description:
        return None, "Describe the issue"
    property_id = body.get("property_id", existing.get("property_id") if existing else None)
    if not property_id:
        return None, "Choose a property"
    date_value = body.get("date", existing.get("date") if existing else None)
    if not date_value:
        date_value = datetime.now().strftime("%Y-%m-%d")
    if not valid_date(date_value):
        return None, "Use a real date"
    issue_type = body.get("issue_type", existing.get("issue_type") if existing else "Other")
    if issue_type not in ISSUE_TYPES:
        return None, "Choose an issue type"
    urgency = body.get("urgency", existing.get("urgency") if existing else "Medium")
    if urgency not in URGENCIES:
        return None, "Choose an urgency"
    status = body.get("status", existing.get("status") if existing else "Open")
    if status not in MAINT_STATUSES:
        return None, "Choose a status"
    cost = optional_money(body.get("cost", existing.get("cost") if existing else None))
    if body.get("cost") not in (None, "") and cost is None and "cost" in body:
        return None, "Cost must be zero or more"
    if "cost" not in body and existing is not None:
        cost = existing.get("cost")
    return {
        "property_id": property_id,
        "description": description,
        "date": date_value,
        "issue_type": issue_type,
        "urgency": urgency,
        "status": status,
        "tenant_name": clean(body.get("tenant_name", existing.get("tenant_name") if existing else ""), 120),
        "contact_phone": clean(body.get("contact_phone", existing.get("contact_phone") if existing else ""), 40),
        "vendor": clean(body.get("vendor", existing.get("vendor") if existing else ""), 120),
        "notes": clean(body.get("notes", existing.get("notes") if existing else ""), 2000),
        "cost": cost,
    }, None


@app.route("/api/maintenance", methods=["GET", "POST"])
@login_required
@uses_data
def api_maintenance():
    data = load_data()
    if request.method == "GET":
        property_id = selected_property()
        status = request.args.get("status", "").strip()
        rows = []
        for row in data["maintenance"]:
            if property_id and row.get("property_id") != property_id:
                continue
            if status and row.get("status") != status:
                continue
            rows.append(row)
        rows.sort(key=lambda row: (row.get("date") or "", row.get("id") or ""), reverse=True)
        return jsonify(rows)

    body = payload()
    fields, error = read_maintenance(body)
    if error:
        return jsonify({"error": error}), 400
    if not property_exists(data, fields["property_id"]):
        return jsonify({"error": "Property not found"}), 400
    entry = {"id": new_id(), "expense_id": None, **fields}
    data["maintenance"].append(entry)
    save_data(data)
    return jsonify(entry), 201


@app.route("/api/maintenance/<entry_id>", methods=["PUT", "DELETE"])
@login_required
@uses_data
def api_maintenance_item(entry_id):
    data = load_data()
    entry = find_item(data["maintenance"], entry_id)
    if entry is None:
        return jsonify({"error": "Maintenance request not found"}), 404
    if request.method == "DELETE":
        data["maintenance"] = [item for item in data["maintenance"] if item["id"] != entry_id]
        save_data(data)
        return jsonify({"message": "Maintenance request deleted"})

    body = payload()
    # A status change from the table sends only the new status.
    if set(body.keys()) == {"status"}:
        if body.get("status") not in MAINT_STATUSES:
            return jsonify({"error": "Choose a status"}), 400
        entry["status"] = body["status"]
        save_data(data)
        return jsonify(entry)

    fields, error = read_maintenance(body, entry)
    if error:
        return jsonify({"error": error}), 400
    if not property_exists(data, fields["property_id"]):
        return jsonify({"error": "Property not found"}), 400
    entry.update(fields)
    save_data(data)
    return jsonify(entry)


@app.route("/api/maintenance/<entry_id>/expense", methods=["POST"])
@login_required
@uses_data
def api_maintenance_expense(entry_id):
    data = load_data()
    entry = find_item(data["maintenance"], entry_id)
    if entry is None:
        return jsonify({"error": "Maintenance request not found"}), 404
    if entry.get("expense_id") and find_item(data["expenses"], entry["expense_id"]):
        return jsonify({"error": "This request is already in expenses"}), 400
    cost = entry.get("cost")
    if cost is None:
        return jsonify({"error": "Enter a cost before copying to expenses"}), 400
    expense = {
        "id": new_id(),
        "property_id": entry["property_id"],
        "amount": cost,
        "date": entry.get("date") or datetime.now().strftime("%Y-%m-%d"),
        "category": "Repairs",
        "description": clean(entry.get("description") or "Maintenance", 500),
        "vendor": entry.get("vendor") or "",
    }
    data["expenses"].append(expense)
    entry["expense_id"] = expense["id"]
    save_data(data)
    return jsonify(expense), 201


def read_line_items(body):
    raw = body.get("line_items")
    if not isinstance(raw, list) or not raw:
        return None, "Add at least one line"
    items = []
    for row in raw[:40]:
        if not isinstance(row, dict):
            continue
        description = clean(row.get("description"), 200)
        if not description:
            continue
        quantity = money(row.get("quantity", 1))
        price = money(row.get("unit_price", 0))
        if quantity is None or quantity <= 0:
            return None, "Quantity must be more than zero"
        if price is None:
            return None, "Price must be zero or more"
        items.append({
            "description": description,
            "quantity": quantity,
            "unit_price": price,
            "amount": round(quantity * price, 2),
        })
    if not items:
        return None, "Add at least one line with a description"
    return items, None


def read_invoice(body, data, existing=None):
    property_id = body.get("property_id") or (existing or {}).get("property_id")
    if not property_id or not property_exists(data, property_id):
        return None, "Choose a property"
    tenant = clean(body.get("tenant", (existing or {}).get("tenant", "")), 120)
    if not tenant:
        return None, "Enter the tenant name"
    date_value = body.get("date") or (existing or {}).get("date") or datetime.now().strftime("%Y-%m-%d")
    if not valid_date(date_value):
        return None, "Use a real invoice date"
    due = body.get("due_date", (existing or {}).get("due_date", "")) or ""
    if due and not valid_date(due):
        return None, "Use a real due date"
    status = body.get("status") or (existing or {}).get("status") or "Draft"
    if status not in INVOICE_STATUSES:
        return None, "Choose a status"
    items, error = read_line_items(body)
    if error:
        return None, error
    return {
        "property_id": property_id,
        "tenant": tenant,
        "date": date_value,
        "due_date": due,
        "status": status,
        "notes": clean(body.get("notes", (existing or {}).get("notes", "")), 2000),
        "line_items": items,
        "total": round(sum(item["amount"] for item in items), 2),
    }, None


def next_invoice_number(data):
    stamp = datetime.now().strftime("%Y%m%d")
    taken = {item.get("number") for item in data["invoices"]}
    count = 1
    while True:
        number = f"INV-{stamp}-{count:03d}"
        if number not in taken:
            return number
        count += 1


@app.route("/api/invoices", methods=["GET", "POST"])
@login_required
@uses_data
def api_invoices():
    data = load_data()
    if request.method == "GET":
        property_id = selected_property()
        rows = data["invoices"]
        if property_id:
            rows = [row for row in rows if row.get("property_id") == property_id]
        rows = sorted(rows, key=lambda row: (row.get("date") or "", row.get("number") or ""), reverse=True)
        return jsonify(rows)

    fields, error = read_invoice(payload(), data)
    if error:
        return jsonify({"error": error}), 400
    entry = {"id": new_id(), "number": next_invoice_number(data), **fields}
    data["invoices"].append(entry)
    save_data(data)
    return jsonify(entry), 201


@app.route("/api/invoices/<invoice_id>", methods=["PUT", "DELETE"])
@login_required
@uses_data
def api_invoice_item(invoice_id):
    data = load_data()
    entry = find_item(data["invoices"], invoice_id)
    if entry is None:
        return jsonify({"error": "Invoice not found"}), 404
    if request.method == "DELETE":
        data["invoices"] = [item for item in data["invoices"] if item["id"] != invoice_id]
        save_data(data)
        return jsonify({"message": "Invoice deleted"})
    fields, error = read_invoice(payload(), data, entry)
    if error:
        return jsonify({"error": error}), 400
    number = entry.get("number")
    entry.clear()
    entry.update({"id": invoice_id, "number": number, **fields})
    save_data(data)
    return jsonify(entry)


@app.route("/invoices/<invoice_id>")
@login_required
@uses_data
def invoice_page(invoice_id):
    data = load_data()
    invoice = find_item(data["invoices"], invoice_id)
    if invoice is None:
        return "Invoice not found", 404
    prop = find_item(data["properties"], invoice.get("property_id"))
    return render_template(
        "invoice.html",
        invoice=invoice,
        prop=prop,
        logo=bool(find_logo()),
        org=public_settings(data),
        **brand_context(),
    )


@app.route("/invoices/<invoice_id>/pdf")
@login_required
@uses_data
def invoice_pdf(invoice_id):
    data = load_data()
    invoice = find_item(data["invoices"], invoice_id)
    if invoice is None:
        return "Invoice not found", 404
    prop = find_item(data["properties"], invoice.get("property_id"))
    filename = (invoice.get("number") or "invoice").replace("/", "-") + ".pdf"
    return send_download(
        build_invoice_pdf(invoice, prop, public_settings(data)),
        filename,
        "application/pdf",
    )


EXPORT_BUILDERS = {
    ("profit-and-loss", "pdf"): exports.build_profit_and_loss_pdf,
    ("profit-and-loss", "xlsx"): exports.build_profit_and_loss_xlsx,
    ("rent-roll", "pdf"): exports.build_rent_roll_pdf,
    ("rent-roll", "xlsx"): exports.build_rent_roll_xlsx,
    ("transactions", "pdf"): exports.build_transactions_pdf,
    ("transactions", "xlsx"): exports.build_transactions_xlsx,
    ("invoices", "pdf"): exports.build_invoices_pdf,
    ("invoices", "xlsx"): exports.build_invoices_xlsx,
    ("tenant-statement", "pdf"): exports.build_tenant_statement_pdf,
    ("tenant-statement", "xlsx"): exports.build_tenant_statement_xlsx,
}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def send_download(buffer, filename, mimetype):
    buffer.seek(0)
    response = send_file(
        buffer,
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def export_bundle():
    """Books for the period and property currently selected on the dashboard."""
    bounds = request_period()
    if bounds == "invalid":
        return None
    start, end = bounds
    property_id = selected_property()
    data = load_data()
    names = {prop["id"]: prop.get("name") or "Property" for prop in data["properties"]}
    chosen = data["properties"]
    if property_id:
        chosen = [prop for prop in chosen if prop["id"] == property_id]
        match = find_item(data["properties"], property_id)
        label = match["name"] if match else "Selected property"
    else:
        label = "All properties"
    return {
        "properties": chosen,
        "income": filtered_rows(data["income"], start, end, property_id),
        "expenses": filtered_rows(data["expenses"], start, end, property_id),
        "invoices": filtered_rows(data["invoices"], start, end, property_id),
        "all_income": list(data["income"]),
        "all_invoices": list(data["invoices"]),
        "names": names,
        "start": start,
        "end": end,
        "property_label": label,
        "org": public_settings(data),
        "logo": find_logo(),
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "tenant": clean(request.args.get("tenant", ""), 120),
    }


@app.route("/export/<slug>")
@login_required
@uses_data
def export_report(slug):
    # Free edition, including the public demo. Sign-in is the only gate.
    if "." not in slug:
        return jsonify({"error": "Choose PDF or Excel"}), 404
    name, ext = slug.rsplit(".", 1)
    ext = ext.lower()
    builder = EXPORT_BUILDERS.get((name, ext))
    if builder is None:
        return jsonify({"error": "That export is not available"}), 404
    bundle = export_bundle()
    if bundle is None:
        return jsonify({"error": "Choose a start date and an end date"}), 400
    filename = exports.export_filename(name, ext, bundle)
    mimetype = "application/pdf" if ext == "pdf" else XLSX_MIME
    return send_download(builder(bundle), filename, mimetype)


@app.route("/invoices/<invoice_id>/xlsx")
@login_required
@uses_data
def invoice_xlsx(invoice_id):
    data = load_data()
    invoice = find_item(data["invoices"], invoice_id)
    if invoice is None:
        return "Invoice not found", 404
    prop = find_item(data["properties"], invoice.get("property_id"))
    filename = (invoice.get("number") or "invoice").replace("/", "-") + ".xlsx"
    return send_download(
        exports.build_invoice_xlsx(
            invoice,
            prop,
            public_settings(data),
            datetime.now().strftime("%Y-%m-%d"),
        ),
        filename,
        XLSX_MIME,
    )


@app.route("/logo")
def logo():
    path = find_logo()
    if not path:
        return "", 404
    return send_file(path)


@app.route("/api/logo", methods=["POST"])
@login_required
@uses_data
def upload_logo():
    upload = request.files.get("logo")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose an image"}), 400
    blob = upload.read(2_000_001)
    if len(blob) > 2_000_000:
        return jsonify({"error": "Logo must be under 2 MB"}), 400
    kind = image_kind(blob)
    if not kind:
        return jsonify({"error": "Use a PNG, JPEG, GIF, or WebP image"}), 400
    folder = data_dir()
    for name in LOGO_NAMES:
        old = os.path.join(folder, name)
        if os.path.isfile(old):
            os.remove(old)
    filename = "logo." + kind
    with open(os.path.join(folder, filename), "wb") as handle:
        handle.write(blob)
    data = load_data()
    data["settings"]["logo"] = filename
    save_data(data)
    return jsonify({"logo": filename})


@app.route("/api/logo", methods=["DELETE"])
@login_required
@uses_data
def remove_logo():
    folder = data_dir()
    for name in LOGO_NAMES:
        old = os.path.join(folder, name)
        if os.path.isfile(old):
            os.remove(old)
    data = load_data()
    data["settings"]["logo"] = ""
    save_data(data)
    return jsonify({"logo": False})


@app.route("/api/settings", methods=["GET", "PUT"])
@login_required
@uses_data
def api_settings():
    data = load_data()
    if request.method == "GET":
        return jsonify(public_settings(data))
    data["settings"] = read_settings(payload(), data.get("settings"))
    save_data(data)
    return jsonify(public_settings(data))


@app.route("/api/password", methods=["POST"])
@login_required
@uses_data
def api_password():
    if not reset_allowed():
        return jsonify({"error": auth.DEMO_RESET_MESSAGE}), 403
    body = payload()
    current = body.get("current_password", "")
    new_password = body.get("new_password", "")
    confirm = body.get("confirm_password", "")
    if not isinstance(current, str) or not isinstance(new_password, str) or not isinstance(confirm, str):
        return jsonify({"error": auth.PASSWORD_RULE}), 400
    if new_password != confirm:
        return jsonify({"error": "Those passwords do not match."}), 400
    data = load_data()
    record = auth.ensure_auth(data)
    if not auth.password_is_current(current, record, VALID_PASSWORD):
        return jsonify({"error": "Current password is not right."}), 400
    problem = auth.apply_new_password(data, new_password, INSECURE_PASSWORDS)
    if problem:
        return jsonify({"error": problem}), 400
    save_data(data)
    return jsonify({"ok": True})


@app.route("/premium")
@login_required
def premium_info():
    return jsonify({
        "message": PREMIUM_DESCRIPTION,
        "description": PREMIUM_DESCRIPTION,
        "features": PREMIUM_FEATURES,
        "waitlist_url": waitlist_url(),
    })


def load_books_or_seed():
    if os.path.exists(DATA_FILE):
        try:
            return load_data()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return seed_data()
    return seed_data()


def install_demo_story(existing):
    """Write the current sample. Settings and the password hash are kept."""
    story = demo_data.build_demo_story(datetime.now().date())
    story["settings"] = existing.get("settings") if isinstance(existing.get("settings"), dict) else empty_settings()
    story["auth"] = existing.get("auth") if isinstance(existing.get("auth"), dict) else {}
    story["demo_seed"] = demo_data.DEMO_SEED_VERSION
    save_data(story)
    return story


def ensure_demo_story():
    """Fill or refresh the public demo sample.

    A file with rent and no demo_seed marker is left alone. An older demo_seed
    is replaced with the current sample. Settings and the password hash are kept.
    """
    if not auth.demo_mode():
        return
    data = load_books_or_seed()
    if data.get("demo_seed") == demo_data.DEMO_SEED_VERSION:
        return
    rents = [
        row for row in data.get("income") or []
        if (row.get("income_type") or "Rent") == "Rent" and row.get("amount")
    ]
    # An older copy of our own sample (demo_seed set, but not this version) is
    # refreshed. A file with rent and no demo_seed marker is someone's own books.
    if rents and not data.get("demo_seed"):
        return
    install_demo_story(data)


def cli_reset_demo():
    """Nightly demo reset. Always the same sample as the running app."""
    if not auth.demo_mode():
        print("reset-demo only runs when DEMO_MODE is set.", file=sys.stderr)
        return 1
    story = install_demo_story(load_books_or_seed())
    folder = os.path.dirname(DATA_FILE) or "."
    for name in LOGO_NAMES:
        old = os.path.join(folder, name)
        if os.path.isfile(old):
            os.remove(old)
    print(f"Demo books reset from the current sample. {len(story['invoices'])} invoices.")
    return 0


ensure_demo_story()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "reset-demo":
        sys.exit(cli_reset_demo())
    if len(sys.argv) > 1 and sys.argv[1] == "reset-password":
        try:
            auth.cli_reset(
                sys.argv[2:],
                load_data,
                save_data,
                VALID_USERNAME,
                INSECURE_PASSWORDS,
            )
        except auth.ResetError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        return
    if not os.path.exists(DATA_FILE):
        save_data(load_data())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=debug_requested())


if __name__ == "__main__":
    main()
