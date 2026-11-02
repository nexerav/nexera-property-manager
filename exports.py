# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF and Excel exports for the free edition.

These reports are the pack a landlord hands to an accountant, to SARS, or to
a tenant: profit and loss for the selected period, the rent roll, tenant
statements, invoices, and the transaction list. Nothing in this module is
paid or flagged off. The public demo uses the same routes after sign-in.
"""

from io import BytesIO
from xml.sax.saxutils import escape
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

from labels import category_label, format_qty


NAVY = "1A365D"
INK = "1A202C"
MUTED = "4A5568"
LINE = "E2E8F0"
ZEBRA = "F7FAFC"
TOTAL = "EBF8FF"
GREEN = "276749"
RED = "C53030"
MONEY_FORMAT = '"R "#,##0.00;"R -"#,##0.00'
QTY_FORMAT = "#,##0.##"

# Helvetica covers Latin-1. Map the punctuation the books already store.
_PDF_REPLACEMENTS = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2022": "-",
    "\u2026": "...",
    "\u00a0": " ",
}

_FORMULA_PREFIXES = ("=", "+", "-", "@")
_INVALID_SHEET = re.compile(r"[\[\]\:\*\?\/\\]")

LANDSCAPE = landscape(A4)
PORTRAIT = A4
_MARGIN = 14 * mm


def safe_slug(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "")
    cleaned = re.sub(r"[-_.]{2,}", "-", cleaned).strip("-._")
    return cleaned or "export"


def export_filename(name, ext, bundle):
    parts = [name]
    tenant = (bundle.get("tenant") or "").strip()
    if tenant and name == "tenant-statement":
        parts.append(safe_slug(tenant)[:40])
    start, end = bundle.get("start"), bundle.get("end")
    if start and end:
        parts.append(f"{start}_to_{end}")
    else:
        parts.append("all-time")
    return "_".join(parts) + "." + ext


def period_text(bundle):
    start, end = bundle.get("start"), bundle.get("end")
    if start and end:
        when = f"{start} to {end}"
    else:
        when = "All time"
    return f"Period {when} · {bundle.get('property_label') or 'All properties'} · Generated {bundle.get('generated') or ''}"


def org_title(org):
    return (org or {}).get("organisation_name") or "Nexera Property Manager"


def org_contact(org):
    parts = []
    for key in ("contact_name", "address", "phone", "email", "registration_number"):
        value = ((org or {}).get(key) or "").strip()
        if value:
            parts.append(value.replace("\n", ", "))
    return " · ".join(parts)


def pdf_text(value):
    text = "" if value is None else str(value)
    for source, target in _PDF_REPLACEMENTS.items():
        text = text.replace(source, target)
    kept = []
    for character in text:
        try:
            character.encode("latin-1")
        except UnicodeEncodeError:
            kept.append("?")
        else:
            kept.append(character)
    return "".join(kept)


def pdf_paragraph(text, style):
    safe = escape(pdf_text(text)).replace("\n", "<br/>")
    return Paragraph(safe or " ", style)


def pdf_money(value):
    return "R " + f"{float(value or 0):,.2f}"


def format_quantity(value):
    return format_qty(value)


def property_name(bundle, property_id):
    return bundle["names"].get(property_id) or "Unknown property"


def income_label(row):
    label = row.get("income_type") or "Rent"
    recovery = (row.get("recovery_category") or "").strip()
    if recovery:
        return f"{label} - {recovery}"
    return label


def _round(value):
    return round(float(value or 0), 2)


def summarise(bundle):
    income = bundle["income"]
    expenses = bundle["expenses"]
    properties = sorted(bundle["properties"], key=lambda prop: (prop.get("name") or "").casefold())

    def total(rows):
        return round(sum(_round(row.get("amount")) for row in rows), 2)

    rent = total(row for row in income if (row.get("income_type") or "Rent") == "Rent")
    other = total(row for row in income if row.get("income_type") == "Other")
    recoveries = {}
    for row in income:
        if row.get("income_type") != "Recovery":
            continue
        label = (row.get("recovery_category") or "").strip() or "Recovery"
        recoveries[label] = round(recoveries.get(label, 0) + _round(row.get("amount")), 2)
    categories = {}
    for row in expenses:
        label = category_label(row.get("category") or "Other")
        categories[label] = round(categories.get(label, 0) + _round(row.get("amount")), 2)

    by_property = []
    for prop in properties:
        prop_income = total(row for row in income if row.get("property_id") == prop["id"])
        prop_expenses = total(row for row in expenses if row.get("property_id") == prop["id"])
        by_property.append({
            "id": prop["id"],
            "name": prop.get("name") or "Property",
            "income": prop_income,
            "expenses": prop_expenses,
            "net": round(prop_income - prop_expenses, 2),
        })

    income_total = total(income)
    expense_total = total(expenses)
    return {
        "properties": properties,
        "rent": rent,
        "other": other,
        "recoveries": sorted(recoveries.items(), key=lambda item: (-item[1], item[0].casefold())),
        "recovery_total": round(sum(recoveries.values()), 2),
        "categories": sorted(categories.items(), key=lambda item: (-item[1], item[0].casefold())),
        "income": income_total,
        "expenses": expense_total,
        "net": round(income_total - expense_total, 2),
        "by_property": by_property,
    }


def transaction_rows(bundle):
    rows = []
    for row in bundle["income"]:
        amount = _round(row.get("amount"))
        rows.append({
            "date": row.get("date") or "",
            "property": property_name(bundle, row.get("property_id")),
            "direction": "Income",
            "type": income_label(row),
            "party": (row.get("tenant") or "").strip(),
            "description": (row.get("description") or "").strip(),
            "amount": amount,
            "signed": amount,
            "id": row.get("id") or "",
        })
    for row in bundle["expenses"]:
        amount = _round(row.get("amount"))
        rows.append({
            "date": row.get("date") or "",
            "property": property_name(bundle, row.get("property_id")),
            "direction": "Expense",
            "type": category_label(row.get("category") or "Other"),
            "party": (row.get("vendor") or "").strip(),
            "description": (row.get("description") or "").strip(),
            "amount": amount,
            "signed": round(-amount, 2),
            "id": row.get("id") or "",
        })
    rows.sort(key=lambda row: (row["date"], row["direction"], row["id"]))
    return rows


def _latest(property_id, rows):
    best = None
    for row in rows:
        if row.get("property_id") != property_id:
            continue
        name = (row.get("tenant") or "").strip()
        if not name:
            continue
        stamp = (row.get("date") or "", row.get("id") or "")
        if best is None or stamp >= best[0]:
            best = (stamp, name)
    return best


def current_tenant(property_id, income, invoices):
    found = _latest(property_id, list(income) + list(invoices))
    return found[1] if found else ""


def occupancy(prop, tenant):
    if prop.get("kind") == "Overhead":
        return "Overhead"
    return "Occupied" if tenant else "Vacant"


def rent_roll_rows(bundle):
    summary = summarise(bundle)
    totals = {row["id"]: row for row in summary["by_property"]}
    rows = []
    for prop in summary["properties"]:
        tenant = current_tenant(prop["id"], bundle["all_income"], bundle["all_invoices"])
        figures = totals.get(prop["id"], {"income": 0, "expenses": 0, "net": 0})
        rent = prop.get("monthly_rent")
        rows.append({
            "name": prop.get("name") or "Property",
            "address": (prop.get("address") or "").strip(),
            "notes": (prop.get("notes") or "").strip(),
            "kind": prop.get("kind") or "",
            "status": occupancy(prop, tenant),
            "tenant": tenant,
            "monthly_rent": None if rent in (None, "") else _round(rent),
            "income": figures["income"],
            "expenses": figures["expenses"],
            "net": figures["net"],
        })
    return rows


def tenant_directory(bundle):
    """One row per property and tenant seen in the whole book, not only this period."""
    allowed = {prop["id"] for prop in bundle["properties"]}
    found = {}
    for row in bundle["all_income"]:
        if row.get("property_id") not in allowed:
            continue
        name = (row.get("tenant") or "").strip()
        if not name:
            continue
        key = (row.get("property_id"), name.casefold())
        slot = found.setdefault(key, {
            "property": property_name(bundle, row.get("property_id")),
            "tenant": name,
            "last_payment_date": "",
            "last_payment": None,
            "last_invoice_date": "",
            "last_invoice": "",
            "last_invoice_total": None,
        })
        stamp = row.get("date") or ""
        if stamp >= slot["last_payment_date"]:
            slot["last_payment_date"] = stamp
            slot["last_payment"] = _round(row.get("amount"))
            slot["tenant"] = name
    for invoice in bundle["all_invoices"]:
        if invoice.get("property_id") not in allowed:
            continue
        name = (invoice.get("tenant") or "").strip()
        if not name:
            continue
        key = (invoice.get("property_id"), name.casefold())
        slot = found.setdefault(key, {
            "property": property_name(bundle, invoice.get("property_id")),
            "tenant": name,
            "last_payment_date": "",
            "last_payment": None,
            "last_invoice_date": "",
            "last_invoice": "",
            "last_invoice_total": None,
        })
        stamp = invoice.get("date") or ""
        if stamp >= slot["last_invoice_date"]:
            slot["last_invoice_date"] = stamp
            slot["last_invoice"] = invoice.get("number") or ""
            slot["last_invoice_total"] = _round(invoice.get("total"))
            slot["tenant"] = name
    return sorted(found.values(), key=lambda row: (row["property"].casefold(), row["tenant"].casefold()))


def tenant_statements(bundle):
    """Charges are invoices. Payments are income recorded against the tenant.

    Balance due is charges minus payments. A negative balance is a credit.
    Names match ignoring case. An explicit tenant with no rows still gets a statement.
    """
    wanted = (bundle.get("tenant") or "").strip()
    groups = {}

    def group_for(name):
        key = name.casefold()
        if key not in groups:
            groups[key] = {"name": name, "events": []}
        return groups[key]

    for invoice in bundle["invoices"]:
        name = (invoice.get("tenant") or "").strip()
        if not name:
            continue
        if wanted and name.casefold() != wanted.casefold():
            continue
        descriptions = [
            (item.get("description") or "").strip()
            for item in (invoice.get("line_items") or [])
            if (item.get("description") or "").strip()
        ]
        detail = invoice.get("number") or "Invoice"
        if invoice.get("status"):
            detail += f" ({invoice['status']})"
        if descriptions:
            detail += " - " + ", ".join(descriptions)
        group_for(name)["events"].append({
            "date": invoice.get("date") or "",
            "property": property_name(bundle, invoice.get("property_id")),
            "description": detail,
            "charge": _round(invoice.get("total")),
            "payment": 0.0,
            "order": 0,
            "id": invoice.get("id") or "",
        })

    for row in bundle["income"]:
        name = (row.get("tenant") or "").strip()
        if not name:
            continue
        if wanted and name.casefold() != wanted.casefold():
            continue
        detail = income_label(row)
        if (row.get("description") or "").strip():
            detail += " - " + row["description"].strip()
        group_for(name)["events"].append({
            "date": row.get("date") or "",
            "property": property_name(bundle, row.get("property_id")),
            "description": detail,
            "charge": 0.0,
            "payment": _round(row.get("amount")),
            "order": 1,
            "id": row.get("id") or "",
        })

    if wanted and wanted.casefold() not in groups:
        groups[wanted.casefold()] = {"name": wanted, "events": []}

    result = []
    for group in groups.values():
        events = sorted(group["events"], key=lambda item: (item["date"], item["order"], item["id"]))
        balance = 0.0
        for event in events:
            balance = round(balance + event["charge"] - event["payment"], 2)
            event["balance"] = balance
        group["events"] = events
        group["charges"] = round(sum(event["charge"] for event in events), 2)
        group["payments"] = round(sum(event["payment"] for event in events), 2)
        group["balance"] = round(group["charges"] - group["payments"], 2)
        result.append(group)
    result.sort(key=lambda group: group["name"].casefold())
    return result


def pl_lines(summary):
    """Rows of (label, amount, kind) where kind is body, total, or net."""
    lines = [
        ("Rent", summary["rent"], "body"),
        ("Recoveries", summary["recovery_total"], "body"),
    ]
    for label, amount in summary["recoveries"]:
        lines.append((f"Recovery: {label}", amount, "body"))
    lines.append(("Other income", summary["other"], "body"))
    lines.append(("Total income", summary["income"], "total"))
    if summary["categories"]:
        for label, amount in summary["categories"]:
            lines.append((label, amount, "body"))
    else:
        lines.append(("No expenses in this period", 0, "body"))
    lines.append(("Total expenses", summary["expenses"], "total"))
    lines.append(("Net income", summary["net"], "net"))
    return lines


PL_NOTE = (
    "Cash record for the selected period, in South African rand. "
    "Expense categories are the ones stored on each record, so bond interest "
    "(tax deductible) stays separate from bond capital (not deductible). "
    "This is not a tax return."
)
STATEMENT_NOTE = (
    "Charges are invoices. Payments are income recorded against this tenant. "
    "Balance due is charges minus payments. A negative balance is a credit."
)


# --- PDF -----------------------------------------------------------------


def pdf_styles():
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "nexera-body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#" + INK),
    )
    return {
        "body": body,
        "right": ParagraphStyle("nexera-right", parent=body, alignment=TA_RIGHT),
        "small": ParagraphStyle(
            "nexera-small",
            parent=body,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#" + MUTED),
        ),
        "right_small": ParagraphStyle(
            "nexera-right-small",
            parent=body,
            alignment=TA_RIGHT,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#" + MUTED),
        ),
        "org": ParagraphStyle(
            "nexera-org",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=colors.HexColor("#" + NAVY),
            spaceAfter=1,
        ),
        "title_right": ParagraphStyle(
            "nexera-title-right",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#" + NAVY),
            spaceAfter=1,
        ),
        "heading": ParagraphStyle(
            "nexera-heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#" + NAVY),
            spaceBefore=6,
            spaceAfter=3,
        ),
        "header": ParagraphStyle(
            "nexera-header",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
        ),
        "header_right": ParagraphStyle(
            "nexera-header-right",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            alignment=TA_RIGHT,
            textColor=colors.white,
        ),
        "total": ParagraphStyle("nexera-total", parent=body, fontName="Helvetica-Bold"),
        "total_right": ParagraphStyle(
            "nexera-total-right",
            parent=body,
            fontName="Helvetica-Bold",
            alignment=TA_RIGHT,
        ),
    }


def logo_flowable(path):
    if not path:
        return None
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image
        reader = ImageReader(path)
        width, height = reader.getSize()
        if not width or not height:
            return None
        scale = min((42 * mm) / float(width), (16 * mm) / float(height))
        return Image(path, width=float(width) * scale, height=float(height) * scale)
    except Exception:
        return None


def draw_footer(canvas, doc):
    canvas.saveState()
    width, _height = canvas._pagesize
    canvas.setStrokeColor(colors.HexColor("#" + LINE))
    canvas.setLineWidth(0.4)
    canvas.line(_MARGIN, 11 * mm, width - _MARGIN, 11 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#" + MUTED))
    canvas.drawString(_MARGIN, 7 * mm, "Nexera Property Manager")
    canvas.drawRightString(width - _MARGIN, 7 * mm, f"Page {doc.page}")
    canvas.restoreState()


def render_pdf(title, story, pagesize):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=12 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="Nexera Property Manager",
        pageCompression=0,
    )
    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buffer.seek(0)
    return buffer


def content_width(pagesize):
    return pagesize[0] - (2 * _MARGIN)


def report_banner(bundle, title, styles, pagesize):
    org = bundle.get("org") or {}
    left = []
    mark = logo_flowable(bundle.get("logo"))
    if mark:
        left.append(mark)
        left.append(Spacer(1, 1.5 * mm))
    left.append(pdf_paragraph(org_title(org), styles["org"]))
    contact = org_contact(org)
    if contact:
        left.append(pdf_paragraph(contact, styles["small"]))
    right = [
        pdf_paragraph(title, styles["title_right"]),
        pdf_paragraph(period_text(bundle), styles["right_small"]),
    ]
    width = content_width(pagesize)
    table = Table([[left, right]], colWidths=[width * 0.58, width * 0.42])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 1.25, colors.HexColor("#" + NAVY)),
    ]))
    return table


def flow_table(headers, records, widths, styles, numeric_columns, total_rows=()):
    numeric_columns = set(numeric_columns)
    total_rows = set(total_rows)
    header_cells = []
    for index, label in enumerate(headers):
        style = styles["header_right"] if index in numeric_columns else styles["header"]
        header_cells.append(pdf_paragraph(label, style))
    built = [header_cells]
    for row_index, record in enumerate(records, start=1):
        is_total = row_index in total_rows
        cells = []
        for index, value in enumerate(record):
            if hasattr(value, "wrap"):
                cells.append(value)
                continue
            if is_total:
                style = styles["total_right"] if index in numeric_columns else styles["total"]
            else:
                style = styles["right"] if index in numeric_columns else styles["body"]
            cells.append(pdf_paragraph("" if value is None else value, style))
        built.append(cells)
    table = Table(built, colWidths=list(widths), repeatRows=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#" + LINE)),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for index in range(1, len(built)):
        if index in total_rows:
            commands.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#" + TOTAL)))
        elif index % 2 == 0:
            commands.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#" + ZEBRA)))
    table.setStyle(TableStyle(commands))
    return table


def _property_paragraph(row, styles):
    extra = " · ".join(part for part in (row["address"], row["notes"]) if part)
    if not extra:
        return pdf_paragraph(row["name"], styles["body"])
    markup = escape(pdf_text(row["name"]))
    markup += f'<br/><font color="#{MUTED}" size="7">{escape(pdf_text(extra))}</font>'
    return Paragraph(markup, styles["body"])


def _money_cell(value):
    if value is None:
        return ""
    return pdf_money(value)


def build_profit_and_loss_pdf(bundle):
    styles = pdf_styles()
    summary = summarise(bundle)
    story = [report_banner(bundle, "Profit and loss", styles, LANDSCAPE), Spacer(1, 4 * mm)]
    story.append(pdf_paragraph("Income and expenses", styles["heading"]))
    records = []
    total_rows = []
    for label, amount, kind in pl_lines(summary):
        records.append([label, pdf_money(amount)])
        if kind in {"total", "net"}:
            total_rows.append(len(records))
    story.append(flow_table(
        ["Line", "Amount"],
        records,
        [120 * mm, 36 * mm],
        styles,
        {1},
        total_rows,
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(pdf_paragraph(PL_NOTE, styles["small"]))
    story.append(pdf_paragraph("By property", styles["heading"]))
    property_records = [
        [row["name"], pdf_money(row["income"]), pdf_money(row["expenses"]), pdf_money(row["net"])]
        for row in summary["by_property"]
    ]
    property_totals = set()
    if property_records:
        property_records.append([
            "Total",
            pdf_money(summary["income"]),
            pdf_money(summary["expenses"]),
            pdf_money(summary["net"]),
        ])
        property_totals.add(len(property_records))
    else:
        property_records.append(["No properties in this selection", "", "", ""])
    story.append(flow_table(
        ["Property", "Income", "Expenses", "Net"],
        property_records,
        [90 * mm, 36 * mm, 36 * mm, 36 * mm],
        styles,
        {1, 2, 3},
        property_totals,
    ))
    story.extend(_transaction_story(bundle, styles))
    return render_pdf("Profit and loss", story, LANDSCAPE)


def _transaction_story(bundle, styles):
    rows = transaction_rows(bundle)
    summary = summarise(bundle)
    width = content_width(LANDSCAPE)
    # 24+46+22+48+36+55+28 = 259, leave the rest on description.
    fixed = (24 + 42 + 22 + 44 + 34 + 28) * mm
    description = max(40 * mm, width - fixed - 2 * mm)
    widths = [24 * mm, 42 * mm, 22 * mm, 44 * mm, 34 * mm, description, 28 * mm]
    records = [
        [row["date"], row["property"], row["direction"], row["type"], row["party"], row["description"], pdf_money(row["amount"])]
        for row in rows
    ]
    total_rows = set()
    if records:
        records.append(["", "", "", "", "", "Total income", pdf_money(summary["income"])])
        records.append(["", "", "", "", "", "Total expenses", pdf_money(summary["expenses"])])
        records.append(["", "", "", "", "", "Net income", pdf_money(summary["net"])])
        total_rows.update({len(records) - 2, len(records) - 1, len(records)})
    else:
        records.append(["No income or expenses in this period", "", "", "", "", "", ""])
    return [
        pdf_paragraph("Transactions", styles["heading"]),
        flow_table(
            ["Date", "Property", "Direction", "Type", "Party", "Description", "Amount"],
            records,
            widths,
            styles,
            {6},
            total_rows,
        ),
    ]


def build_transactions_pdf(bundle):
    styles = pdf_styles()
    story = [
        report_banner(bundle, "Transactions", styles, LANDSCAPE),
        Spacer(1, 4 * mm),
        pdf_paragraph("Income and expenses recorded in this period.", styles["small"]),
    ]
    story.extend(_transaction_story(bundle, styles))
    return render_pdf("Transactions", story, LANDSCAPE)


def build_rent_roll_pdf(bundle):
    styles = pdf_styles()
    rows = rent_roll_rows(bundle)
    story = [
        report_banner(bundle, "Rent roll", styles, LANDSCAPE),
        Spacer(1, 4 * mm),
        pdf_paragraph(
            "Units and the current tenant. Income, expenses, and net follow the selected period. "
            "The tenant is the latest name on income or an invoice for that unit.",
            styles["small"],
        ),
        Spacer(1, 2 * mm),
    ]
    records = []
    for row in rows:
        records.append([
            _property_paragraph(row, styles),
            row["kind"],
            row["status"],
            row["tenant"],
            _money_cell(row["monthly_rent"]),
            pdf_money(row["income"]),
            pdf_money(row["expenses"]),
            pdf_money(row["net"]),
        ])
    if not records:
        records.append(["No properties yet", "", "", "", "", "", "", ""])
    width = content_width(LANDSCAPE)
    widths = [52 * mm, 24 * mm, 22 * mm, 36 * mm, 28 * mm, 28 * mm, 30 * mm, 28 * mm]
    # Stretch the property column if the page is wider than the fixed columns.
    widths[0] = max(40 * mm, width - sum(widths[1:]) - 2 * mm)
    story.append(flow_table(
        ["Property", "Type", "Status", "Tenant", "Monthly rent", "Income", "Expenses", "Net"],
        records,
        widths,
        styles,
        {4, 5, 6, 7},
    ))
    directory = tenant_directory(bundle)
    story.append(pdf_paragraph("Tenants", styles["heading"]))
    tenant_records = [
        [
            row["property"],
            row["tenant"],
            row["last_payment_date"],
            _money_cell(row["last_payment"]),
            row["last_invoice"],
            _money_cell(row["last_invoice_total"]),
        ]
        for row in directory
    ]
    if not tenant_records:
        tenant_records.append(["No tenants recorded yet", "", "", "", "", ""])
    story.append(flow_table(
        ["Property", "Tenant", "Last payment", "Amount", "Last invoice", "Invoice total"],
        tenant_records,
        [52 * mm, 40 * mm, 32 * mm, 32 * mm, 40 * mm, 36 * mm],
        styles,
        {3, 5},
    ))
    return render_pdf("Rent roll", story, LANDSCAPE)


def _invoice_records(bundle):
    rows = sorted(
        bundle["invoices"],
        key=lambda row: (row.get("date") or "", row.get("number") or "", row.get("id") or ""),
    )
    return rows


def build_invoices_pdf(bundle):
    styles = pdf_styles()
    invoices = _invoice_records(bundle)
    story = [
        report_banner(bundle, "Invoices", styles, LANDSCAPE),
        Spacer(1, 4 * mm),
        pdf_paragraph("Invoices dated in the selected period.", styles["small"]),
        Spacer(1, 2 * mm),
    ]
    records = []
    total = 0.0
    line_records = []
    for invoice in invoices:
        amount = _round(invoice.get("total"))
        total = round(total + amount, 2)
        records.append([
            invoice.get("number") or "",
            invoice.get("date") or "",
            invoice.get("due_date") or "",
            property_name(bundle, invoice.get("property_id")),
            invoice.get("tenant") or "",
            invoice.get("status") or "",
            pdf_money(amount),
        ])
        for item in invoice.get("line_items") or []:
            line_records.append([
                invoice.get("number") or "",
                invoice.get("date") or "",
                invoice.get("tenant") or "",
                item.get("description") or "",
                item.get("quantity"),
                pdf_money(item.get("unit_price")),
                pdf_money(item.get("amount")),
            ])
    total_rows = set()
    if records:
        records.append(["", "", "", "", "", "Total", pdf_money(total)])
        total_rows.add(len(records))
    else:
        records.append(["No invoices in this period", "", "", "", "", "", ""])
    story.append(flow_table(
        ["Number", "Date", "Due", "Property", "Tenant", "Status", "Total"],
        records,
        [32 * mm, 24 * mm, 24 * mm, 48 * mm, 40 * mm, 22 * mm, 30 * mm],
        styles,
        {6},
        total_rows,
    ))
    story.append(pdf_paragraph("Line items", styles["heading"]))
    if not line_records:
        line_records.append(["No line items in this period", "", "", "", "", "", ""])
    formatted_lines = []
    for row in line_records:
        quantity = row[4]
        formatted_lines.append([
            row[0],
            row[1],
            row[2],
            row[3],
            format_quantity(quantity),
            row[5],
            row[6],
        ])
    story.append(flow_table(
        ["Number", "Date", "Tenant", "Description", "Qty", "Unit price", "Amount"],
        formatted_lines,
        [32 * mm, 24 * mm, 36 * mm, 78 * mm, 16 * mm, 30 * mm, 30 * mm],
        styles,
        {4, 5, 6},
    ))
    return render_pdf("Invoices", story, LANDSCAPE)


def _statement_table(group, styles):
    records = [
        [
            event["date"],
            event["property"],
            event["description"],
            pdf_money(event["charge"]) if event["charge"] else "",
            pdf_money(event["payment"]) if event["payment"] else "",
            pdf_money(event["balance"]),
        ]
        for event in group["events"]
    ]
    if not records:
        records.append(["No invoices or income for this tenant in the period", "", "", "", "", ""])
    records.append([
        "",
        "",
        "Balance due",
        pdf_money(group["charges"]),
        pdf_money(group["payments"]),
        pdf_money(group["balance"]),
    ])
    return flow_table(
        ["Date", "Property", "Description", "Charge", "Payment", "Balance"],
        records,
        [24 * mm, 40 * mm, 78 * mm, 28 * mm, 28 * mm, 30 * mm],
        styles,
        {3, 4, 5},
        {len(records)},
    )


def build_tenant_statement_pdf(bundle):
    styles = pdf_styles()
    groups = tenant_statements(bundle)
    org = bundle.get("org") or {}
    if not groups:
        story = [
            report_banner(bundle, "Tenant statement", styles, LANDSCAPE),
            Spacer(1, 4 * mm),
            pdf_paragraph("No tenants with invoices or income in this period.", styles["body"]),
            Spacer(1, 2 * mm),
            pdf_paragraph(STATEMENT_NOTE, styles["small"]),
        ]
        return render_pdf("Tenant statement", story, LANDSCAPE)

    story = []
    for index, group in enumerate(groups):
        if index:
            story.append(PageBreak())
        story.append(report_banner(bundle, "Tenant statement", styles, LANDSCAPE))
        story.append(Spacer(1, 4 * mm))
        story.append(pdf_paragraph(group["name"], styles["heading"]))
        story.append(pdf_paragraph(STATEMENT_NOTE, styles["small"]))
        story.append(Spacer(1, 2 * mm))
        story.append(_statement_table(group, styles))
        if (org.get("payment_details") or "").strip():
            story.append(Spacer(1, 3 * mm))
            story.append(pdf_paragraph("Payment details", styles["heading"]))
            story.append(pdf_paragraph(org["payment_details"], styles["body"]))
    return render_pdf("Tenant statement", story, LANDSCAPE)


# --- Excel ---------------------------------------------------------------


def excel_text(value):
    """Keep tenant names and notes as text, including values Excel would treat as formulas."""
    if value is None:
        return ""
    return str(value)


def write_text(cell, value):
    text = excel_text(value)
    cell.value = text
    if text.startswith(_FORMULA_PREFIXES):
        cell.data_type = "s"
    cell.alignment = Alignment(vertical="top", wrap_text=True)


def write_money(cell, value, bold=False, colour=None):
    if value is None:
        write_text(cell, "")
        return
    cell.value = _round(value)
    cell.number_format = MONEY_FORMAT
    cell.alignment = Alignment(horizontal="right", vertical="top")
    if bold or colour:
        cell.font = Font(bold=bold, color=colour or INK, name="Calibri")


def _thin_border():
    side = Side(style="thin", color=LINE)
    return Border(left=side, right=side, top=side, bottom=side)


def apply_header_row(ws, row, columns):
    fill = PatternFill("solid", fgColor=NAVY)
    font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    for column in range(1, columns + 1):
        cell = ws.cell(row, column)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = _thin_border()


def finish_sheet(ws, header_row, last_row, last_col, widths):
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = f"A{header_row + 1}"
    if last_row > header_row:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{last_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.horizontalCentered = True
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.7
    ws.page_margins.bottom = 0.6
    ws.page_margins.header = 0.25
    ws.page_margins.footer = 0.25
    ws.oddFooter.left.text = "Nexera Property Manager"
    ws.oddFooter.left.font = "Calibri"
    ws.oddFooter.left.size = 8
    ws.oddFooter.right.text = "Page &P of &N"
    ws.oddFooter.right.font = "Calibri"
    ws.oddFooter.right.size = 8
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = NAVY


def write_banner(ws, bundle, title, columns, subtitle=None):
    org = bundle.get("org") or {}
    width = max(columns, 2)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    ws["A1"] = org_title(org)
    ws["A1"].font = Font(bold=True, color=NAVY, size=16, name="Calibri")
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    ws["A2"] = title
    ws["A2"].font = Font(bold=True, color=NAVY, size=13, name="Calibri")
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=width)
    ws["A3"] = subtitle or period_text(bundle)
    ws["A3"].font = Font(size=10, color=MUTED, name="Calibri")
    contact = org_contact(org)
    if contact:
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=width)
        ws["A4"] = contact
        ws["A4"].font = Font(size=9, color=MUTED, name="Calibri")
        ws["A4"].alignment = Alignment(wrap_text=True, vertical="top")
        return 6
    return 5


def paint_data_cell(cell, row_index, total=False):
    cell.border = _thin_border()
    if total:
        cell.fill = PatternFill("solid", fgColor=TOTAL)
    elif row_index % 2 == 0:
        cell.fill = PatternFill("solid", fgColor=ZEBRA)


def new_workbook(title):
    book = Workbook()
    book.properties.title = title
    book.properties.creator = "Nexera Property Manager"
    book.properties.subject = "Nexera Property Manager export"
    return book


def workbook_bytes(book):
    buffer = BytesIO()
    book.save(buffer)
    buffer.seek(0)
    return buffer


def _note(ws, row, text, columns):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(columns, 2))
    cell = ws.cell(row, 1, text)
    cell.font = Font(size=9, italic=True, color=MUTED, name="Calibri")
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[row].height = 36


def _write_label_amount(ws, row, label, amount, kind):
    label_cell = ws.cell(row, 1)
    write_text(label_cell, label)
    amount_cell = ws.cell(row, 2)
    write_money(amount_cell, amount, bold=kind in {"total", "net"})
    bold = kind in {"total", "net"}
    colour = None
    if kind == "net":
        colour = RED if amount < 0 else GREEN
        amount_cell.font = Font(bold=True, color=colour, name="Calibri")
        label_cell.font = Font(bold=True, color=colour, name="Calibri")
    elif bold:
        label_cell.font = Font(bold=True, name="Calibri")
    for column in (1, 2):
        paint_data_cell(ws.cell(row, column), row, total=bold)
    return row + 1


def build_profit_and_loss_xlsx(bundle):
    summary = summarise(bundle)
    book = new_workbook("Profit and loss")
    sheet = book.active
    sheet.title = "Profit and loss"
    header = write_banner(sheet, bundle, "Profit and loss", 2)
    write_text(sheet.cell(header, 1), "Line")
    write_text(sheet.cell(header, 2), "Amount")
    apply_header_row(sheet, header, 2)
    row = header + 1
    for label, amount, kind in pl_lines(summary):
        row = _write_label_amount(sheet, row, label, amount, kind)
    last_data = row - 1
    _note(sheet, row + 1, PL_NOTE, 2)
    finish_sheet(sheet, header, last_data, 2, [46, 18])

    by_property = book.create_sheet("By property")
    header = write_banner(by_property, bundle, "Profit and loss by property", 4)
    for column, label in enumerate(["Property", "Income", "Expenses", "Net"], start=1):
        write_text(by_property.cell(header, column), label)
    apply_header_row(by_property, header, 4)
    row = header + 1
    for item in summary["by_property"]:
        write_text(by_property.cell(row, 1), item["name"])
        write_money(by_property.cell(row, 2), item["income"])
        write_money(by_property.cell(row, 3), item["expenses"])
        write_money(by_property.cell(row, 4), item["net"], bold=True, colour=RED if item["net"] < 0 else GREEN)
        for column in range(1, 5):
            paint_data_cell(by_property.cell(row, column), row)
        row += 1
    if summary["by_property"]:
        write_text(by_property.cell(row, 1), "Total")
        by_property.cell(row, 1).font = Font(bold=True, name="Calibri")
        write_money(by_property.cell(row, 2), summary["income"], bold=True)
        write_money(by_property.cell(row, 3), summary["expenses"], bold=True)
        write_money(by_property.cell(row, 4), summary["net"], bold=True, colour=RED if summary["net"] < 0 else GREEN)
        for column in range(1, 5):
            paint_data_cell(by_property.cell(row, column), row, total=True)
        last = row
    else:
        write_text(by_property.cell(row, 1), "No properties in this selection")
        last = row
    finish_sheet(by_property, header, last, 4, [36, 16, 16, 16])
    _add_transaction_sheet(book, bundle, "Transactions")
    return workbook_bytes(book)


TRANSACTION_HEADERS = ["Date", "Property", "Direction", "Type", "Party", "Description", "Amount", "Signed"]


def _add_transaction_sheet(book, bundle, title):
    sheet = book.create_sheet(title)
    summary = summarise(bundle)
    header = write_banner(sheet, bundle, "Transactions", len(TRANSACTION_HEADERS))
    for column, label in enumerate(TRANSACTION_HEADERS, start=1):
        write_text(sheet.cell(header, column), label)
    apply_header_row(sheet, header, len(TRANSACTION_HEADERS))
    row = header + 1
    rows = transaction_rows(bundle)
    if not rows:
        write_text(sheet.cell(row, 1), "No income or expenses in this period")
        for column in range(1, len(TRANSACTION_HEADERS) + 1):
            paint_data_cell(sheet.cell(row, column), row)
        row += 1
    for item in rows:
        values = [
            item["date"], item["property"], item["direction"], item["type"],
            item["party"], item["description"],
        ]
        for column, value in enumerate(values, start=1):
            write_text(sheet.cell(row, column), value)
        write_money(sheet.cell(row, 7), item["amount"])
        write_money(
            sheet.cell(row, 8),
            item["signed"],
            colour=RED if item["signed"] < 0 else GREEN,
        )
        for column in range(1, len(TRANSACTION_HEADERS) + 1):
            paint_data_cell(sheet.cell(row, column), row)
        row += 1
    totals = [
        ("Total income", summary["income"], GREEN),
        ("Total expenses", summary["expenses"], RED),
        ("Net income", summary["net"], RED if summary["net"] < 0 else GREEN),
    ]
    for label, amount, colour in totals:
        write_text(sheet.cell(row, 6), label)
        sheet.cell(row, 6).font = Font(bold=True, name="Calibri", color=colour)
        write_money(sheet.cell(row, 7), amount, bold=True, colour=colour)
        for column in range(1, len(TRANSACTION_HEADERS) + 1):
            paint_data_cell(sheet.cell(row, column), row, total=True)
        row += 1
    finish_sheet(sheet, header, row - 1, len(TRANSACTION_HEADERS), [14, 28, 12, 32, 22, 36, 16, 16])


def build_transactions_xlsx(bundle):
    book = new_workbook("Transactions")
    placeholder = book.active
    placeholder.title = "Sheet"
    _add_transaction_sheet(book, bundle, "Transactions")
    book.remove(placeholder)
    book.active = 0
    return workbook_bytes(book)


def build_rent_roll_xlsx(bundle):
    book = new_workbook("Rent roll")
    sheet = book.active
    sheet.title = "Rent roll"
    headers = [
        "Property", "Address", "Type", "Status", "Tenant",
        "Monthly rent", "Income", "Expenses", "Net", "Notes",
    ]
    header = write_banner(sheet, bundle, "Rent roll", len(headers))
    for column, label in enumerate(headers, start=1):
        write_text(sheet.cell(header, column), label)
    apply_header_row(sheet, header, len(headers))
    row = header + 1
    rows = rent_roll_rows(bundle)
    if not rows:
        write_text(sheet.cell(row, 1), "No properties yet")
        for column in range(1, len(headers) + 1):
            paint_data_cell(sheet.cell(row, column), row)
        last = row
    else:
        for item in rows:
            write_text(sheet.cell(row, 1), item["name"])
            write_text(sheet.cell(row, 2), item["address"])
            write_text(sheet.cell(row, 3), item["kind"])
            write_text(sheet.cell(row, 4), item["status"])
            write_text(sheet.cell(row, 5), item["tenant"])
            write_money(sheet.cell(row, 6), item["monthly_rent"])
            write_money(sheet.cell(row, 7), item["income"])
            write_money(sheet.cell(row, 8), item["expenses"])
            write_money(sheet.cell(row, 9), item["net"], bold=True, colour=RED if item["net"] < 0 else GREEN)
            write_text(sheet.cell(row, 10), item["notes"])
            for column in range(1, len(headers) + 1):
                paint_data_cell(sheet.cell(row, column), row)
            row += 1
        last = row - 1
    finish_sheet(sheet, header, last, len(headers), [28, 32, 14, 12, 22, 16, 16, 16, 16, 36])

    tenants = book.create_sheet("Tenants")
    headers = ["Property", "Tenant", "Last payment", "Amount", "Last invoice", "Invoice total"]
    header = write_banner(tenants, bundle, "Tenants", len(headers))
    for column, label in enumerate(headers, start=1):
        write_text(tenants.cell(header, column), label)
    apply_header_row(tenants, header, len(headers))
    row = header + 1
    directory = tenant_directory(bundle)
    if not directory:
        write_text(tenants.cell(row, 1), "No tenants recorded yet")
        for column in range(1, len(headers) + 1):
            paint_data_cell(tenants.cell(row, column), row)
        last = row
    else:
        for item in directory:
            write_text(tenants.cell(row, 1), item["property"])
            write_text(tenants.cell(row, 2), item["tenant"])
            write_text(tenants.cell(row, 3), item["last_payment_date"])
            write_money(tenants.cell(row, 4), item["last_payment"])
            write_text(tenants.cell(row, 5), item["last_invoice"])
            write_money(tenants.cell(row, 6), item["last_invoice_total"])
            for column in range(1, len(headers) + 1):
                paint_data_cell(tenants.cell(row, column), row)
            row += 1
        last = row - 1
    finish_sheet(tenants, header, last, len(headers), [28, 22, 16, 16, 22, 16])
    return workbook_bytes(book)


def build_invoices_xlsx(bundle):
    book = new_workbook("Invoices")
    sheet = book.active
    sheet.title = "Invoices"
    headers = ["Number", "Date", "Due", "Property", "Tenant", "Status", "Total"]
    header = write_banner(sheet, bundle, "Invoices", len(headers))
    for column, label in enumerate(headers, start=1):
        write_text(sheet.cell(header, column), label)
    apply_header_row(sheet, header, len(headers))
    invoices = _invoice_records(bundle)
    row = header + 1
    total = 0.0
    if not invoices:
        write_text(sheet.cell(row, 1), "No invoices in this period")
        for column in range(1, len(headers) + 1):
            paint_data_cell(sheet.cell(row, column), row)
        last = row
    else:
        for invoice in invoices:
            amount = _round(invoice.get("total"))
            total = round(total + amount, 2)
            values = [
                invoice.get("number") or "",
                invoice.get("date") or "",
                invoice.get("due_date") or "",
                property_name(bundle, invoice.get("property_id")),
                invoice.get("tenant") or "",
                invoice.get("status") or "",
            ]
            for column, value in enumerate(values, start=1):
                write_text(sheet.cell(row, column), value)
            write_money(sheet.cell(row, 7), amount)
            for column in range(1, len(headers) + 1):
                paint_data_cell(sheet.cell(row, column), row)
            row += 1
        write_text(sheet.cell(row, 6), "Total")
        sheet.cell(row, 6).font = Font(bold=True, name="Calibri")
        write_money(sheet.cell(row, 7), total, bold=True)
        for column in range(1, len(headers) + 1):
            paint_data_cell(sheet.cell(row, column), row, total=True)
        last = row
    finish_sheet(sheet, header, last, len(headers), [20, 14, 14, 28, 22, 12, 16])

    lines = book.create_sheet("Line items")
    headers = ["Number", "Date", "Tenant", "Description", "Quantity", "Unit price", "Amount"]
    header = write_banner(lines, bundle, "Invoice line items", len(headers))
    for column, label in enumerate(headers, start=1):
        write_text(lines.cell(header, column), label)
    apply_header_row(lines, header, len(headers))
    row = header + 1
    any_lines = False
    for invoice in invoices:
        for item in invoice.get("line_items") or []:
            any_lines = True
            write_text(lines.cell(row, 1), invoice.get("number") or "")
            write_text(lines.cell(row, 2), invoice.get("date") or "")
            write_text(lines.cell(row, 3), invoice.get("tenant") or "")
            write_text(lines.cell(row, 4), item.get("description") or "")
            quantity = lines.cell(row, 5, _round(item.get("quantity")))
            quantity.number_format = QTY_FORMAT
            quantity.alignment = Alignment(horizontal="right")
            write_money(lines.cell(row, 6), item.get("unit_price"))
            write_money(lines.cell(row, 7), item.get("amount"))
            for column in range(1, len(headers) + 1):
                paint_data_cell(lines.cell(row, column), row)
            row += 1
    if not any_lines:
        write_text(lines.cell(row, 1), "No line items in this period")
        for column in range(1, len(headers) + 1):
            paint_data_cell(lines.cell(row, column), row)
        last = row
    else:
        last = row - 1
    finish_sheet(lines, header, last, len(headers), [20, 14, 22, 36, 12, 16, 16])
    return workbook_bytes(book)


def _sheet_title(name, used):
    cleaned = _INVALID_SHEET.sub(" ", name or "").strip() or "Tenant"
    base = cleaned[:31]
    candidate = base
    count = 2
    while candidate.casefold() in used:
        suffix = f" {count}"
        candidate = (base[:31 - len(suffix)] + suffix).strip()
        count += 1
    used.add(candidate.casefold())
    return candidate


def _write_statement_sheet(sheet, bundle, group):
    headers = ["Date", "Property", "Description", "Charge", "Payment", "Balance"]
    header = write_banner(sheet, bundle, "Tenant statement - " + group["name"], len(headers))
    for column, label in enumerate(headers, start=1):
        write_text(sheet.cell(header, column), label)
    apply_header_row(sheet, header, len(headers))
    row = header + 1
    if not group["events"]:
        write_text(sheet.cell(row, 1), "No invoices or income for this tenant in the period")
        for column in range(1, len(headers) + 1):
            paint_data_cell(sheet.cell(row, column), row)
        row += 1
    for event in group["events"]:
        write_text(sheet.cell(row, 1), event["date"])
        write_text(sheet.cell(row, 2), event["property"])
        write_text(sheet.cell(row, 3), event["description"])
        write_money(sheet.cell(row, 4), event["charge"] or None)
        write_money(sheet.cell(row, 5), event["payment"] or None)
        write_money(sheet.cell(row, 6), event["balance"])
        for column in range(1, len(headers) + 1):
            paint_data_cell(sheet.cell(row, column), row)
        row += 1
    write_text(sheet.cell(row, 3), "Balance due")
    sheet.cell(row, 3).font = Font(bold=True, name="Calibri")
    write_money(sheet.cell(row, 4), group["charges"], bold=True)
    write_money(sheet.cell(row, 5), group["payments"], bold=True)
    colour = RED if group["balance"] < 0 else GREEN
    write_money(sheet.cell(row, 6), group["balance"], bold=True, colour=colour)
    for column in range(1, len(headers) + 1):
        paint_data_cell(sheet.cell(row, column), row, total=True)
    last = row
    _note(sheet, row + 2, STATEMENT_NOTE, len(headers))
    payment = ((bundle.get("org") or {}).get("payment_details") or "").strip()
    if payment:
        _note(sheet, row + 3, "Payment details: " + payment, len(headers))
    finish_sheet(sheet, header, last, len(headers), [14, 28, 42, 16, 16, 16])


def build_tenant_statement_xlsx(bundle):
    book = new_workbook("Tenant statement")
    groups = tenant_statements(bundle)
    summary = book.active
    summary.title = "Summary"
    headers = ["Tenant", "Charges", "Payments", "Balance due"]
    header = write_banner(summary, bundle, "Tenant statements", len(headers))
    for column, label in enumerate(headers, start=1):
        write_text(summary.cell(header, column), label)
    apply_header_row(summary, header, len(headers))
    row = header + 1
    if not groups:
        write_text(summary.cell(row, 1), "No tenants with invoices or income in this period")
        for column in range(1, len(headers) + 1):
            paint_data_cell(summary.cell(row, column), row)
        last = row
    else:
        for group in groups:
            write_text(summary.cell(row, 1), group["name"])
            write_money(summary.cell(row, 2), group["charges"])
            write_money(summary.cell(row, 3), group["payments"])
            colour = RED if group["balance"] < 0 else GREEN
            write_money(summary.cell(row, 4), group["balance"], bold=True, colour=colour)
            for column in range(1, len(headers) + 1):
                paint_data_cell(summary.cell(row, column), row)
            row += 1
        last = row - 1
    _note(summary, last + 2, STATEMENT_NOTE, len(headers))
    finish_sheet(summary, header, last, len(headers), [28, 16, 16, 16])
    used = {"summary"}
    for group in groups:
        sheet = book.create_sheet(_sheet_title(group["name"], used))
        _write_statement_sheet(sheet, bundle, group)
    return workbook_bytes(book)


def build_invoice_xlsx(invoice, prop, org, generated):
    """One invoice, matching the PDF a tenant already receives."""
    number = invoice.get("number") or "Invoice"
    property_name_text = (prop or {}).get("name") or ""
    bundle = {
        "org": org,
        "start": None,
        "end": None,
        "property_label": property_name_text or "Invoice",
        "generated": generated,
        "names": {},
        "properties": [],
        "income": [],
        "expenses": [],
        "invoices": [],
        "all_income": [],
        "all_invoices": [],
        "logo": None,
        "tenant": invoice.get("tenant") or "",
    }
    subtitle = " · ".join(part for part in (
        property_name_text,
        invoice.get("tenant") or "",
        f"Generated {generated}" if generated else "",
    ) if part)
    book = new_workbook(number)
    sheet = book.active
    sheet.title = "Invoice"
    header_row = write_banner(sheet, bundle, number, 4, subtitle=subtitle)
    meta = [
        ("Status", invoice.get("status") or ""),
        ("Invoice date", invoice.get("date") or ""),
        ("Due date", invoice.get("due_date") or ""),
        ("Tenant", invoice.get("tenant") or ""),
        ("Property", (prop or {}).get("name") or ""),
        ("Address", (prop or {}).get("address") or ""),
    ]
    row = header_row
    for label, value in meta:
        write_text(sheet.cell(row, 1), label)
        sheet.cell(row, 1).font = Font(bold=True, color=MUTED, name="Calibri", size=9)
        write_text(sheet.cell(row, 2), value)
        row += 1
    row += 1
    for column, label in enumerate(["Description", "Quantity", "Unit price", "Amount"], start=1):
        write_text(sheet.cell(row, column), label)
    apply_header_row(sheet, row, 4)
    header = row
    row += 1
    for item in invoice.get("line_items") or []:
        write_text(sheet.cell(row, 1), item.get("description") or "")
        quantity = sheet.cell(row, 2, _round(item.get("quantity")))
        quantity.number_format = QTY_FORMAT
        quantity.alignment = Alignment(horizontal="right")
        write_money(sheet.cell(row, 3), item.get("unit_price"))
        write_money(sheet.cell(row, 4), item.get("amount"))
        for column in range(1, 5):
            paint_data_cell(sheet.cell(row, column), row)
        row += 1
    write_text(sheet.cell(row, 3), "Total")
    sheet.cell(row, 3).font = Font(bold=True, name="Calibri")
    write_money(sheet.cell(row, 4), invoice.get("total"), bold=True, colour=NAVY)
    for column in range(1, 5):
        paint_data_cell(sheet.cell(row, column), row, total=True)
    last = row
    notes = (invoice.get("notes") or "").strip()
    if notes:
        _note(sheet, row + 2, "Notes: " + notes, 4)
    payment = (org.get("payment_details") or "").strip()
    if payment:
        _note(sheet, row + (4 if notes else 2), "Payment details: " + payment, 4)
    finish_sheet(sheet, header, last, 4, [42, 14, 16, 16])
    return workbook_bytes(book)
