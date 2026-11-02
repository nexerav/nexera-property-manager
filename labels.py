# Copyright (C) 2026 Nexera Ventures
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plain labels and one rand format for the books.

Older expense categories stay valid. They are shown with the plain name.
"""

EXPENSE_CHOICES = (
    ("Utilities", ""),
    ("Rates", "Municipal property rates."),
    ("Refuse", ""),
    ("Maintenance", ""),
    ("Insurance", ""),
    ("Repairs", ""),
    ("Managing agent fees", ""),
    ("Accountant fees", ""),
    ("Consulting fees", ""),
    ("Bond interest", "Tax deductible."),
    ("Bond capital payment", "Not a tax deduction. This builds equity."),
    ("Technology and systems", ""),
    ("Travel for property work", ""),
    ("Transfer and bond registration", "A capital cost, not a running expense."),
    ("Other banking costs", ""),
    ("Other", ""),
)

# Stored values from earlier versions. The file can keep these; the screen uses the plain name.
LEGACY_CATEGORIES = {
    "Managing Agent Fees": "Managing agent fees",
    "Accountant Fees": "Accountant fees",
    "Consulting Fees": "Consulting fees",
    "Bond Interest (Tax Deductible)": "Bond interest",
    "Bond Capital Payment (Equity - Not Deductible)": "Bond capital payment",
    "Technology & Systems": "Technology and systems",
    "Travel – Property Operations": "Travel for property work",
    "Travel - Property Operations": "Travel for property work",
    "Transfer & Bond Registration – Capital Costs": "Transfer and bond registration",
    "Transfer & Bond Registration - Capital Costs": "Transfer and bond registration",
    "Other Banking Expenses": "Other banking costs",
}


def category_label(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return "Other"
    return LEGACY_CATEGORIES.get(text, text)


def category_help(label):
    for name, help_text in EXPENSE_CHOICES:
        if name == label:
            return help_text
    return ""


def format_zar(value):
    """The only rand format: R 8,500.00 (comma thousands, dot cents).

    The browser copy lives in static/js/format.js and must match this.
    """
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    sign = "-" if amount < 0 else ""
    whole, cents = f"{abs(amount):.2f}".split(".")
    groups = []
    while whole:
        groups.append(whole[-3:])
        whole = whole[:-3]
    return f"R {sign}{','.join(reversed(groups))}.{cents}"


def format_qty(value):
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number == int(number):
        return str(int(number))
    return f"{number:,.2f}"
