# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fictional books for the public demo.

Several months of rent, a few recoveries, and ordinary expenses, so the
dashboard is not an empty month with one odd recovery.
"""

from datetime import date, timedelta

DEMO_SEED_VERSION = 2


def _shift_month(today, back):
    month = today.month - back
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return year, month


def _stamp(year, month, day):
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_demo_story(today):
    units = (
        ("demo-a", "Unit A - 123 Main Street", "123 Main Street, City", 8500, "A. Tenant"),
        ("demo-b", "Unit B - 456 Oak Avenue", "456 Oak Avenue, City", 7200, "B. Tenant"),
        ("demo-c", "Unit C - 78 Park Lane", "78 Park Lane, City", 6400, "C. Tenant"),
    )
    properties = []
    for prop_id, name, address, rent, _tenant in units:
        properties.append({
            "id": prop_id,
            "name": name,
            "address": address,
            "kind": "Residential",
            "monthly_rent": rent,
            "notes": "",
        })
    properties.append({
        "id": "demo-overhead",
        "name": "Company Expenses",
        "address": "Portfolio overhead",
        "kind": "Overhead",
        "monthly_rent": None,
        "notes": "Not a unit. Bond interest, agent fees, and other costs for the whole portfolio.",
    })

    income = []
    expenses = []
    for back in range(11, -1, -1):
        year, month = _shift_month(today, back)
        rent_day = _stamp(year, month, 1)
        for prop_id, _name, _address, rent, tenant in units:
            # Unit C missed rent two months ago, so the chart is not a flat line.
            if prop_id == "demo-c" and back == 2:
                continue
            income.append({
                "id": f"demo-rent-{prop_id}-{year}{month:02d}",
                "property_id": prop_id,
                "amount": rent,
                "date": rent_day,
                "description": "Rent",
                "tenant": tenant,
                "income_type": "Rent",
                "recovery_category": "",
            })
        if back % 2 == 0:
            income.append({
                "id": f"demo-water-a-{year}{month:02d}",
                "property_id": "demo-a",
                "amount": 380,
                "date": _stamp(year, month, 12),
                "description": "Water recovery",
                "tenant": "A. Tenant",
                "income_type": "Recovery",
                "recovery_category": "Water",
            })
        if back % 3 == 0:
            income.append({
                "id": f"demo-elec-b-{year}{month:02d}",
                "property_id": "demo-b",
                "amount": 540,
                "date": _stamp(year, month, 12),
                "description": "Electricity recovery",
                "tenant": "B. Tenant",
                "income_type": "Recovery",
                "recovery_category": "Electricity",
            })
        expenses.append({
            "id": f"demo-bond-{year}{month:02d}",
            "property_id": "demo-overhead",
            "amount": 4100,
            "date": _stamp(year, month, 2),
            "category": "Bond interest",
            "vendor": "Sample Bank",
            "description": "Bond interest",
        })
        expenses.append({
            "id": f"demo-agent-{year}{month:02d}",
            "property_id": "demo-overhead",
            "amount": 900,
            "date": _stamp(year, month, 2),
            "category": "Managing agent fees",
            "vendor": "Sample Agency",
            "description": "Monthly agent fee",
        })
        expenses.append({
            "id": f"demo-rates-a-{year}{month:02d}",
            "property_id": "demo-a",
            "amount": 980,
            "date": _stamp(year, month, 15),
            "category": "Rates",
            "vendor": "City",
            "description": "Rates",
        })
        expenses.append({
            "id": f"demo-ins-b-{year}{month:02d}",
            "property_id": "demo-b",
            "amount": 310,
            "date": _stamp(year, month, 15),
            "category": "Insurance",
            "vendor": "Sample Insurer",
            "description": "Building insurance",
        })
    year, month = _shift_month(today, 4)
    expenses.append({
        "id": "demo-repair-b",
        "property_id": "demo-b",
        "amount": 2600,
        "date": _stamp(year, month, 18),
        "category": "Repairs",
        "vendor": "Local plumber",
        "description": "Geyser repair",
    })

    # Six invoices across months: draft, sent, still owing, overdue, and paid.
    invoice_plan = (
        (0, 0, "Outstanding", 14, "Current rent, not due yet."),
        (1, 1, "Overdue", -20, "Due last month and still unpaid."),
        (2, 2, "Paid", 7, "Paid in that month."),
        (3, 0, "Draft", 7, "Not sent yet."),
        (5, 1, "Issued", 7, "Sent, and still open."),
        (7, 2, "Paid", 7, "Paid in that month."),
    )
    invoices = []
    for number, (back, unit_index, status, due_offset, note) in enumerate(invoice_plan, start=1):
        prop_id, _name, _address, rent, tenant = units[unit_index]
        year, month = _shift_month(today, back)
        invoice_date = date(year, month, min(8, 28))
        due = invoice_date + timedelta(days=due_offset)
        if status == "Overdue" and due >= today:
            due = today - timedelta(days=3)
        invoices.append({
            "id": f"demo-inv-{number:02d}",
            "number": f"INV-DEMO-{invoice_date.year}{invoice_date.month:02d}-{number:02d}",
            "property_id": prop_id,
            "tenant": tenant,
            "date": invoice_date.isoformat(),
            "due_date": due.isoformat(),
            "status": status,
            "notes": note,
            "line_items": [{
                "description": "Monthly rent",
                "quantity": 1,
                "unit_price": rent,
                "amount": rent,
            }],
            "total": rent,
        })

    maintenance = [{
        "id": "demo-job-b",
        "property_id": "demo-b",
        "description": "Kitchen tap drips",
        "date": today.isoformat(),
        "issue_type": "Plumbing",
        "urgency": "Low",
        "status": "Open",
        "tenant_name": "B. Tenant",
        "contact_phone": "",
        "vendor": "",
        "notes": "",
        "cost": None,
        "expense_id": None,
    }]
    return {
        "properties": properties,
        "income": income,
        "expenses": expenses,
        "maintenance": maintenance,
        "invoices": invoices,
    }
