import base64
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from datetime import datetime as RealDateTime

from openpyxl import load_workbook

import auth
import desktop

TEMP_DIR = tempfile.mkdtemp()
DATA_FILE = os.path.join(TEMP_DIR, "rental_data.json")
os.environ["DATA_FILE"] = DATA_FILE
os.environ["SECRET_KEY"] = "unit-test-secret"
os.environ["APP_USERNAME"] = "admin"
os.environ["APP_PASSWORD"] = "unit-test-password"
os.environ.pop("FLASK_DEBUG", None)

import app as pm


class FixedDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 30)


pm.datetime = FixedDateTime


class PropertyAppTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("NEXERA_DESKTOP", None)
        pm.VALID_PASSWORD = "unit-test-password"
        pm._desktop_ready = False
        with open(DATA_FILE, "w") as handle:
            json.dump({
                "properties": [],
                "income": [],
                "expenses": [],
                "maintenance": [],
            }, handle)
        folder = os.path.dirname(DATA_FILE)
        for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.gif", "logo.webp"):
            leftover = os.path.join(folder, name)
            if os.path.isfile(leftover):
                os.remove(leftover)
        self.client = pm.app.test_client()
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "unit-test-password"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

    def add_property(self, name="Unit A - 123 Main Street", kind="Residential"):
        response = self.client.post("/api/properties", json={
            "name": name,
            "address": "123 Main Street, City",
            "kind": kind,
            "monthly_rent": 8000,
            "notes": "Ground floor",
        })
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def test_refuses_missing_or_placeholder_secrets(self):
        self.assertEqual(pm.VALID_PASSWORD, "unit-test-password")
        self.assertEqual(pm.app.secret_key, "unit-test-secret")
        self.assertFalse(pm.debug_requested())
        blocked = [
            ("SECRET_KEY", "", "APP_PASSWORD", "unit-test-password"),
            ("SECRET_KEY", "change-me-in-production-please", "APP_PASSWORD", "unit-test-password"),
            ("APP_PASSWORD", "", "SECRET_KEY", "unit-test-secret"),
            ("APP_PASSWORD", "admin123", "SECRET_KEY", "unit-test-secret"),
        ]
        root = os.path.dirname(os.path.abspath(pm.__file__))
        for name, bad, other_name, other_value in blocked:
            env = os.environ.copy()
            env["DATA_FILE"] = DATA_FILE
            env[name] = bad
            env[other_name] = other_value
            env.pop("FLASK_DEBUG", None)
            env.pop("NEXERA_DESKTOP", None)
            result = subprocess.run(
                [sys.executable, "-c", "import app"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(name, result.stderr)
            if bad:
                self.assertNotIn(bad, result.stderr)

    def test_sign_in_required(self):
        guest = pm.app.test_client()
        self.assertEqual(guest.get("/api/summary").status_code, 401)
        self.assertEqual(guest.get("/premium").status_code, 401)
        page = guest.get("/")
        self.assertEqual(page.status_code, 302)

    def test_dashboard_shows_locked_premium_features(self):
        page = self.client.get("/")
        self.assertIn(b"Or your own category", page.data)
        self.assertIn(b"Upload logo", page.data)
        self.assertIn(b"Company or trust name", page.data)
        self.assertIn(b"Download PDF", page.data)
        self.assertIn(b'data-tab="settings"', page.data)
        header = page.data.split(b"</header>", 1)[0]
        self.assertNotIn(b"Upload logo", header)
        self.assertNotIn(b"logo-file", header)
        self.assertIn(b"Common Property Electricity", page.data)
        self.assertIn(b"fine-print", page.data)
        self.assertIn(b"Version 1.5.0", page.data)
        self.assertNotIn(b"Open Source", page.data)
        self.assertIn(pm.PREMIUM_DESCRIPTION.encode(), page.data)
        self.assertIn(b"Join the waitlist", page.data)
        self.assertIn(b"https://www.nexerav.com", page.data)
        self.assertIn(b"premium-tag", page.data)
        self.assertIn(b"stored on this computer", page.data)
        self.assertIn(b"not a property", page.data)
        self.assertIn(b'value="last12" selected', page.data)
        self.assertNotIn(b"OCR bill scanning", page.data)
        self.assertNotIn(b"Advanced charts", page.data)
        premium = self.client.get("/premium")
        self.assertEqual(premium.get_json()["message"], pm.PREMIUM_DESCRIPTION)
        self.assertEqual(premium.get_json()["waitlist_url"], "https://www.nexerav.com")

    def test_edit_income_expense_and_custom_category(self):
        prop = self.add_property()
        other = self.add_property(name="Company Expenses", kind="Overhead")
        created = self.client.post("/api/income", json={
            "property_id": prop["id"],
            "amount": 8000,
            "date": "2026-10-05",
            "income_type": "Rent",
            "tenant": "A. Tenant",
            "description": "October rent",
        })
        self.assertEqual(created.status_code, 201)
        income_id = created.get_json()["id"]
        moved = self.client.put(f"/api/income/{income_id}", json={
            "property_id": other["id"],
            "amount": 8100,
            "date": "2026-10-06",
            "income_type": "Recovery",
            "recovery_category": "Water",
            "tenant": "A. Tenant",
            "description": "Water recovery",
        })
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.get_json()["property_id"], other["id"])
        self.assertEqual(moved.get_json()["recovery_category"], "Water")

        expense = self.client.post("/api/expenses", json={
            "property_id": prop["id"],
            "amount": 450,
            "date": "2026-01-15",
            "category": "Garden service",
            "vendor": "Local gardener",
            "description": "January tidy-up",
        })
        self.assertEqual(expense.status_code, 201)
        self.assertEqual(expense.get_json()["category"], "Garden service")

        october = self.client.get("/api/summary?period=month").get_json()
        self.assertEqual(october["income"], 8100)
        self.assertEqual(october["other_income"], 8100)
        self.assertEqual(october["expenses"], 0)

        january = self.client.get("/api/expenses?period=custom&start=2026-01-01&end=2026-01-31").get_json()
        self.assertEqual(len(january), 1)
        self.assertEqual(self.client.get("/api/expenses?period=custom&start=2026-02-01").status_code, 400)
        self.assertEqual(self.client.post("/api/income", json={
            "property_id": prop["id"],
            "amount": -5,
            "date": "2026-10-01",
        }).status_code, 400)

    def test_property_delete_removes_linked_records(self):
        prop = self.add_property()
        self.client.post("/api/income", json={
            "property_id": prop["id"],
            "amount": 100,
            "date": "2026-01-02",
            "description": "Old rent",
        })
        self.client.post("/api/maintenance", json={
            "property_id": prop["id"],
            "description": "Dripping tap",
            "date": "2026-09-01",
            "issue_type": "Plumbing",
            "urgency": "Low",
        })
        self.assertEqual(self.client.delete(f"/api/properties/{prop['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/income?period=all").get_json(), [])
        self.assertEqual(self.client.get("/api/maintenance").get_json(), [])

    def test_maintenance_status_and_expense_copy(self):
        prop = self.add_property()
        created = self.client.post("/api/maintenance", json={
            "property_id": prop["id"],
            "description": "Gate will not lock",
            "issue_type": "Security",
            "urgency": "High",
            "cost": 900,
            "vendor": "Local locksmith",
        })
        self.assertEqual(created.status_code, 201)
        job = created.get_json()
        self.assertEqual(job["status"], "Open")
        updated = self.client.put(f"/api/maintenance/{job['id']}", json={"status": "In progress"})
        self.assertEqual(updated.get_json()["status"], "In progress")
        self.assertEqual(updated.get_json()["description"], "Gate will not lock")
        self.assertEqual(
            self.client.put(f"/api/maintenance/{job['id']}", json={"status": "Waiting"}).status_code,
            400,
        )
        copied = self.client.post(f"/api/maintenance/{job['id']}/expense")
        self.assertEqual(copied.status_code, 201)
        self.assertEqual(copied.get_json()["category"], "Repairs")
        self.assertEqual(copied.get_json()["amount"], 900)
        self.assertEqual(self.client.post(f"/api/maintenance/{job['id']}/expense").status_code, 400)
        open_jobs = self.client.get("/api/maintenance?status=Open").get_json()
        self.assertEqual(open_jobs, [])

    def test_older_file_still_loads_without_being_rewritten(self):
        original = {
            "properties": [
                {"id": "1", "name": "Unit A - 123 Main Street", "address": "123 Main Street, City"},
                {"id": "3", "name": "Company Expenses", "address": "Portfolio overhead"},
            ],
            "income": [{
                "id": "09856598",
                "property_id": "1",
                "amount": 10000.0,
                "date": "2026-10-30",
                "description": "Rent",
                "tenant": "",
            }],
            "expenses": [],
            "maintenance": [{
                "id": "job",
                "property_id": "1",
                "description": "Leak",
                "status": "Open",
                "date": "2026-10-01",
            }],
        }
        raw = json.dumps(original, indent=2)
        with open(DATA_FILE, "w") as handle:
            handle.write(raw)
        income = self.client.get("/api/income?period=all").get_json()
        self.assertEqual(income[0]["income_type"], "Rent")
        self.assertEqual(income[0]["amount"], 10000.0)
        properties = self.client.get("/api/properties").get_json()
        company = next(item for item in properties if item["name"] == "Company Expenses")
        self.assertEqual(company["kind"], "Overhead")
        job = self.client.get("/api/maintenance").get_json()[0]
        self.assertEqual(job["issue_type"], "Other")
        self.assertEqual(job["urgency"], "Medium")
        summary = self.client.get("/api/summary?period=month").get_json()
        self.assertEqual(summary["rent"], 10000.0)
        with open(DATA_FILE) as handle:
            self.assertEqual(handle.read(), raw)

    def test_invoice_can_be_printed_but_not_emailed(self):
        prop = self.add_property()
        created = self.client.post("/api/invoices", json={
            "property_id": prop["id"],
            "tenant": "A. Tenant",
            "date": "2026-10-01",
            "due_date": "2026-10-07",
            "status": "Issued",
            "line_items": [
                {"description": "Rent", "quantity": 1, "unit_price": 8000},
                {"description": "Water", "quantity": 1, "unit_price": 350},
            ],
        })
        self.assertEqual(created.status_code, 201)
        invoice = created.get_json()
        self.assertEqual(invoice["total"], 8350)
        self.assertTrue(invoice["number"].startswith("INV-"))
        refused = self.client.post("/api/income", json={
            "property_id": prop["id"],
            "amount": 50,
            "date": "2026-10-01",
            "income_type": "Recovery",
        })
        self.assertEqual(refused.status_code, 400)
        page = self.client.get("/invoices/" + invoice["id"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Email invoice", page.data)
        self.assertIn(b"Download PDF", page.data)
        self.assertNotIn(b"mailto:", page.data)
        self.assertIn(b"R 8,350.00", page.data)
        self.assertIn(b"R 8,000.00", page.data)
        self.assertNotIn(b">1.0<", page.data)
        self.assertIn(b">1<", page.data)

    def test_logo_upload(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        uploaded = self.client.post(
            "/api/logo",
            data={"logo": (io.BytesIO(png), "mark.png")},
        )
        self.assertEqual(uploaded.status_code, 200)
        guest = pm.app.test_client()
        logo = guest.get("/logo")
        self.assertEqual(logo.status_code, 200)
        self.assertTrue(logo.data.startswith(b"\x89PNG"))

    def test_settings_appear_on_the_invoice_pdf(self):
        saved = self.client.put("/api/settings", json={
            "organisation_name": "Example Holdings",
            "contact_name": "A. Owner",
            "address": "1 Example Road",
            "phone": "0100000000",
            "email": "owner@example.com",
            "registration_number": "REG-1",
            "payment_details": "Use reference INV",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["organisation_name"], "Example Holdings")
        self.assertFalse(saved.get_json()["logo"])
        prop = self.add_property()
        created = self.client.post("/api/invoices", json={
            "property_id": prop["id"],
            "tenant": "A. Tenant",
            "date": "2026-10-01",
            "line_items": [{"description": "Rent", "quantity": 1, "unit_price": 8000}],
        })
        self.assertEqual(created.status_code, 201)
        invoice = created.get_json()
        pdf = self.client.get("/invoices/" + invoice["id"] + "/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertIn("attachment", pdf.headers.get("Content-Disposition", ""))
        text = pdf_bytes(pdf.data)
        self.assertIn(b"Example Holdings", text)
        self.assertIn(b"A. Tenant", text)
        self.assertIn(b"8,000.00", text)
        self.assertIn(b"Use reference INV", text)
        page = self.client.get("/invoices/" + invoice["id"])
        self.assertIn(b"Example Holdings", page.data)
        self.assertIn(b"Download PDF", page.data)
        removed = self.client.delete("/api/logo")
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(self.client.get("/api/settings").get_json()["logo"])

    def test_exports_are_free_for_any_signed_in_user(self):
        # The public demo uses the same routes after its demo login.
        # Nothing in the premium list may describe these downloads.
        guest = pm.app.test_client()
        denied = guest.get("/export/profit-and-loss.pdf?period=month")
        self.assertEqual(denied.status_code, 302)
        self.assertIn("/login", denied.headers["Location"])
        self.assertEqual(guest.get("/invoices/missing/xlsx").status_code, 302)

        premium = self.client.get("/premium").get_json()["features"]
        joined = " ".join(premium).lower()
        self.assertNotIn("export", joined)
        self.assertNotIn("excel", joined)
        self.assertNotIn("spreadsheet", joined)

        page = self.client.get("/")
        expected_links = [
            "/export/profit-and-loss.pdf?period=last12",
            "/export/profit-and-loss.xlsx?period=last12",
            "/export/rent-roll.pdf?period=last12",
            "/export/rent-roll.xlsx?period=last12",
            "/export/transactions.pdf?period=last12",
            "/export/transactions.xlsx?period=last12",
            "/export/invoices.pdf?period=last12",
            "/export/invoices.xlsx?period=last12",
            "/export/tenant-statement.pdf?period=last12",
            "/export/tenant-statement.xlsx?period=last12",
        ]
        for link in expected_links:
            self.assertIn(link.encode(), page.data)
        self.assertGreaterEqual(page.data.count(b">Export PDF<"), 5)
        self.assertGreaterEqual(page.data.count(b">Export Excel<"), 5)
        for tag in re.findall(br"<a\b[^>]*\bdata-export=[^>]*>", page.data):
            self.assertNotIn(b"locked", tag)

        for path in expected_links:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            if path.endswith(".pdf") or ".pdf?" in path:
                self.assertEqual(response.mimetype, "application/pdf", path)
                self.assertTrue(response.data.startswith(b"%PDF"), path)
                self.assertIn(b"Nexera Property Manager", pdf_bytes(response.data))
            else:
                self.assertEqual(
                    response.mimetype,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    path,
                )
                self.assertTrue(response.data.startswith(b"PK"), path)
                load_workbook(io.BytesIO(response.data))
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))

        self.assertEqual(self.client.get("/export/not-a-report.pdf").status_code, 404)
        self.assertEqual(self.client.get("/export/profit-and-loss.csv").status_code, 404)
        self.assertEqual(
            self.client.get("/export/transactions.pdf?period=custom&start=2026-02-01").status_code,
            400,
        )
        self.assertEqual(self.client.get("/invoices/missing/xlsx").status_code, 404)

    def test_period_exports_use_rand_and_branding(self):
        saved = self.client.put("/api/settings", json={
            "organisation_name": "Example Holdings",
            "contact_name": "A. Owner",
            "address": "1 Example Road",
            "phone": "0100000000",
            "email": "owner@example.com",
            "registration_number": "REG-1",
            "payment_details": "Use reference INV",
        })
        self.assertEqual(saved.status_code, 200)
        unit_a = self.add_property()
        unit_b = self.add_property(name="Unit B - 456 Oak Avenue")
        overhead = self.add_property(name="Company Expenses", kind="Overhead")
        vacant = self.add_property(name="Unit C - Empty")
        self.add_property(name="=2+2")
        self.assertEqual(self.client.put(f"/api/properties/{overhead['id']}", json={"monthly_rent": ""}).status_code, 200)
        self.assertEqual(self.client.put(f"/api/properties/{vacant['id']}", json={"monthly_rent": ""}).status_code, 200)

        self.assertEqual(self.client.post("/api/income", json={
            "property_id": unit_a["id"],
            "amount": 8000,
            "date": "2026-10-05",
            "income_type": "Rent",
            "tenant": "A. Tenant",
            "description": "October rent",
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/income", json={
            "property_id": unit_a["id"],
            "amount": 350,
            "date": "2026-10-05",
            "income_type": "Recovery",
            "recovery_category": "Water",
            "tenant": "A. Tenant",
            "description": "Water recovery",
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/income", json={
            "property_id": unit_b["id"],
            "amount": 6500,
            "date": "2026-10-03",
            "income_type": "Rent",
            "tenant": "B. Tenant",
            "description": "October rent B",
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/expenses", json={
            "property_id": unit_a["id"],
            "amount": 1200,
            "date": "2026-10-10",
            "category": "Rates",
            "vendor": "City",
            "description": "October rates",
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/expenses", json={
            "property_id": unit_a["id"],
            "amount": 2000,
            "date": "2026-10-12",
            "category": "Bond Interest (Tax Deductible)",
            "vendor": "Bank",
            "description": "Bond interest",
        }).status_code, 201)
        self.assertEqual(self.client.post("/api/expenses", json={
            "property_id": unit_a["id"],
            "amount": 450,
            "date": "2026-01-15",
            "category": "Garden service",
            "vendor": "January Gardener",
            "description": "January tidy-up",
        }).status_code, 201)
        created = self.client.post("/api/invoices", json={
            "property_id": unit_a["id"],
            "tenant": "A. Tenant",
            "date": "2026-10-01",
            "due_date": "2026-10-07",
            "status": "Issued",
            "notes": "October account",
            "line_items": [
                {"description": "Rent", "quantity": 1, "unit_price": 8000},
                {"description": "Water", "quantity": 1, "unit_price": 350},
            ],
        })
        self.assertEqual(created.status_code, 201)
        invoice = created.get_json()

        pl_pdf = self.client.get("/export/profit-and-loss.pdf?period=month")
        self.assertEqual(pl_pdf.status_code, 200)
        self.assertIn("profit-and-loss_2026-10-01_to_2026-10-31.pdf", pl_pdf.headers["Content-Disposition"])
        pl_text = pdf_bytes(pl_pdf.data)
        for snippet in (
            b"Example Holdings",
            b"A. Owner",
            b"REG-1",
            b"Profit and loss",
            b"8,000.00",
            b"6,500.00",
            b"11,650.00",
            b"3,200.00",
            b"Bond interest",
            b"Water",
            b"October rent",
            b"2026-10-01 to 2026-10-31",
        ):
            self.assertIn(snippet, pl_text)
        self.assertNotIn(b"January tidy-up", pl_text)

        pl_book = load_workbook(io.BytesIO(self.client.get("/export/profit-and-loss.xlsx?period=month").data))
        self.assertEqual(pl_book.sheetnames, ["Profit and loss", "By property", "Transactions"])
        pl_values = sheet_values(pl_book)
        self.assertIn("Example Holdings", pl_values)
        self.assertTrue(has_text(pl_values, "Bond interest"))
        self.assertFalse(has_text(pl_values, "Bond Interest (Tax Deductible)"))
        self.assertTrue(has_text(pl_values, "Water"))
        self.assertIn(11650, pl_values)
        self.assertIn(3200, pl_values)
        self.assertNotIn("January tidy-up", pl_values)
        self.assertTrue(any(cell_is_rand(cell) and cell.value == 8000 for cell in iter_cells(pl_book)))
        signed = [
            cell.value for cell in iter_cells(pl_book["Transactions"])
            if cell.value in (-1200, -2000, 8000, 6500, 350)
        ]
        self.assertIn(-1200, signed)
        self.assertIn(8000, signed)

        month_tx = pdf_bytes(self.client.get("/export/transactions.pdf?period=month").data)
        self.assertIn(b"October rates", month_tx)
        self.assertNotIn(b"January tidy-up", month_tx)
        year_tx = pdf_bytes(self.client.get("/export/transactions.pdf?period=year").data)
        self.assertIn(b"January tidy-up", year_tx)
        self.assertIn(
            "transactions_2026-01-01_to_2026-12-31.pdf",
            self.client.get("/export/transactions.pdf?period=year").headers["Content-Disposition"],
        )
        custom = self.client.get("/export/transactions.xlsx?period=custom&start=2026-01-01&end=2026-01-31")
        custom_values = sheet_values(load_workbook(io.BytesIO(custom.data)))
        self.assertIn("January tidy-up", custom_values)
        self.assertNotIn("October rent", custom_values)
        self.assertIn(450, custom_values)

        roll = self.client.get(f"/export/rent-roll.xlsx?period=month&property_id={unit_a['id']}")
        roll_book = load_workbook(io.BytesIO(roll.data))
        self.assertEqual(roll_book.sheetnames, ["Rent roll", "Tenants"])
        roll_values = sheet_values(roll_book)
        self.assertIn("A. Tenant", roll_values)
        self.assertIn("Occupied", roll_values)
        self.assertNotIn("B. Tenant", roll_values)
        full_roll = sheet_values(load_workbook(io.BytesIO(self.client.get("/export/rent-roll.xlsx?period=month").data)))
        self.assertIn("B. Tenant", full_roll)
        self.assertIn("Vacant", full_roll)
        self.assertIn("Overhead", full_roll)
        self.assertIn("Unit C - Empty", full_roll)
        formula_cells = [
            cell for cell in iter_cells(load_workbook(io.BytesIO(self.client.get("/export/rent-roll.xlsx?period=all").data)))
            if cell.value == "=2+2"
        ]
        self.assertTrue(formula_cells)
        self.assertTrue(all(cell.data_type != "f" for cell in formula_cells))

        roll_pdf = pdf_bytes(self.client.get("/export/rent-roll.pdf?period=month").data)
        self.assertIn(b"Rent roll", roll_pdf)
        self.assertIn(b"A. Tenant", roll_pdf)
        self.assertIn(b"Vacant", roll_pdf)

        only_b = pdf_bytes(self.client.get(f"/export/profit-and-loss.pdf?period=month&property_id={unit_b['id']}").data)
        self.assertIn(b"6,500.00", only_b)
        self.assertNotIn(b"A. Tenant", only_b)
        self.assertNotIn(b"11,650.00", only_b)

        statement = self.client.get("/export/tenant-statement.pdf?period=month&tenant=A.%20Tenant")
        self.assertIn("tenant-statement_A-Tenant_2026-10-01_to_2026-10-31.pdf", statement.headers["Content-Disposition"])
        statement_text = pdf_bytes(statement.data)
        self.assertIn(b"A. Tenant", statement_text)
        self.assertIn(b"8,350.00", statement_text)
        self.assertIn(b"Use reference INV", statement_text)
        self.assertIn(invoice["number"].encode(), statement_text)
        self.assertNotIn(b"B. Tenant", statement_text)

        all_statements = load_workbook(io.BytesIO(self.client.get("/export/tenant-statement.xlsx?period=month").data))
        summary = sheet_values(all_statements)
        self.assertIn("A. Tenant", summary)
        self.assertIn("B. Tenant", summary)
        self.assertIn(8350, summary)
        self.assertIn(-6500, summary)
        self.assertEqual(all_statements["Summary"].title, "Summary")

        invoices_pdf = pdf_bytes(self.client.get("/export/invoices.pdf?period=month").data)
        self.assertIn(invoice["number"].encode(), invoices_pdf)
        self.assertIn(b"8,350.00", invoices_pdf)
        invoices_book = load_workbook(io.BytesIO(self.client.get("/export/invoices.xlsx?period=month").data))
        self.assertEqual(invoices_book.sheetnames, ["Invoices", "Line items"])
        invoice_values = sheet_values(invoices_book)
        self.assertIn(invoice["number"], invoice_values)
        self.assertIn("Water", invoice_values)
        self.assertIn(8350, invoice_values)
        outside = sheet_values(load_workbook(io.BytesIO(
            self.client.get("/export/invoices.xlsx?period=custom&start=2026-01-01&end=2026-01-31").data
        )))
        self.assertNotIn(invoice["number"], outside)

        single = self.client.get("/invoices/" + invoice["id"] + "/xlsx")
        self.assertEqual(single.status_code, 200)
        self.assertIn(invoice["number"] + ".xlsx", single.headers["Content-Disposition"])
        single_values = sheet_values(load_workbook(io.BytesIO(single.data)))
        self.assertIn("Example Holdings", single_values)
        self.assertTrue(has_text(single_values, "October account"))
        self.assertTrue(has_text(single_values, "Use reference INV"))
        self.assertIn(8350, single_values)
        page = self.client.get("/invoices/" + invoice["id"])
        self.assertIn(b"Download PDF", page.data)
        self.assertIn(b"Export Excel", page.data)

        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        self.assertEqual(self.client.post("/api/logo", data={"logo": (io.BytesIO(png), "mark.png")}).status_code, 200)
        branded = self.client.get("/export/profit-and-loss.pdf?period=month")
        self.assertTrue(branded.data.startswith(b"%PDF"))
        self.assertIn(b"Example Holdings", pdf_bytes(branded.data))

    def run_reset(self, password, extra_env=None, args=None):
        env = os.environ.copy()
        env["DATA_FILE"] = DATA_FILE
        env["SECRET_KEY"] = "unit-test-secret"
        env["APP_USERNAME"] = "admin"
        env["APP_PASSWORD"] = "unit-test-password"
        env.pop("DEMO_MODE", None)
        env.pop("ALLOW_PASSWORD_RESET", None)
        env.pop("APP_PASSWORD_RESET", None)
        if password is not None:
            env["APP_PASSWORD_RESET"] = password
        if extra_env:
            env.update(extra_env)
        command = [sys.executable, "app.py", "reset-password"]
        if args:
            command.extend(args)
        root = os.path.dirname(os.path.abspath(pm.__file__))
        return subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )

    def test_password_can_be_changed_and_reset_from_the_server(self):
        guest = pm.app.test_client()
        login = guest.get("/login")
        self.assertIn(b"Forgot password?", login.data)
        help_page = guest.get("/forgot-password")
        self.assertEqual(help_page.status_code, 200)
        self.assertIn(b"python3 app.py reset-password", help_page.data)
        self.assertNotIn(b"Send reset link", help_page.data)
        self.assertEqual(guest.post("/forgot-password", data={"username": "admin"}).status_code, 200)
        with open(DATA_FILE) as handle:
            saved = json.load(handle)
        self.assertFalse((saved.get("auth") or {}).get("reset_token_hash"))

        page = self.client.get("/")
        self.assertIn(b"Change password", page.data)
        self.assertIn(b"Current password", page.data)
        refused = self.client.post("/api/password", json={
            "current_password": "wrong-current-password",
            "new_password": "replacement-password",
            "confirm_password": "replacement-password",
        })
        self.assertEqual(refused.status_code, 400)
        mismatch = self.client.post("/api/password", json={
            "current_password": "unit-test-password",
            "new_password": "replacement-password",
            "confirm_password": "other-replacement",
        })
        self.assertEqual(mismatch.status_code, 400)
        short = self.client.post("/api/password", json={
            "current_password": "unit-test-password",
            "new_password": "short",
            "confirm_password": "short",
        })
        self.assertEqual(short.status_code, 400)
        changed = self.client.post("/api/password", json={
            "current_password": "unit-test-password",
            "new_password": "replacement-password",
            "confirm_password": "replacement-password",
        })
        self.assertEqual(changed.status_code, 200)
        self.assertNotIn("password_hash", self.client.get("/api/settings").get_json())
        with open(DATA_FILE) as handle:
            stored = json.load(handle)
        auth_state = stored["auth"]
        self.assertTrue(auth_state["password_hash"])
        self.assertNotIn("replacement-password", json.dumps(stored))
        self.assertNotEqual(auth_state["password_hash"], "replacement-password")
        self.client.get("/logout")
        old = self.client.post("/login", data={"username": "admin", "password": "unit-test-password"})
        self.assertIn(b"Invalid credentials", old.data)
        new = self.client.post(
            "/login",
            data={"username": "admin", "password": "replacement-password"},
            follow_redirects=True,
        )
        self.assertEqual(new.status_code, 200)
        self.assertIn(b"Change password", new.data)

        missing = self.run_reset(None)
        self.assertNotEqual(missing.returncode, 0)
        self.assertNotIn("replacement-password", missing.stdout + missing.stderr)
        leaked = self.run_reset(None, args=["hunter2-from-argv"])
        self.assertNotEqual(leaked.returncode, 0)
        self.assertNotIn("hunter2-from-argv", leaked.stdout)
        self.assertNotIn("hunter2-from-argv", leaked.stderr)

    def test_lockout_is_cleared_by_reset(self):
        guest = pm.app.test_client()
        for _ in range(4):
            wrong = guest.post("/login", data={"username": "admin", "password": "not-the-password"})
            self.assertIn(b"Invalid credentials", wrong.data)
        locked = guest.post("/login", data={"username": "admin", "password": "not-the-password"})
        self.assertIn(b"Too many sign-in attempts", locked.data)
        still = guest.post("/login", data={"username": "admin", "password": "unit-test-password"})
        self.assertIn(b"Too many sign-in attempts", still.data)
        self.assertNotIn(b"Change password", still.data)

        result = self.run_reset("server-reset-password")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("server-reset-password", result.stdout)
        self.assertNotIn("server-reset-password", result.stderr)
        self.assertIn("Password updated", result.stdout)
        fresh = pm.app.test_client()
        denied = fresh.post("/login", data={"username": "admin", "password": "unit-test-password"})
        self.assertIn(b"Invalid credentials", denied.data)
        allowed = fresh.post(
            "/login",
            data={"username": "admin", "password": "server-reset-password"},
            follow_redirects=True,
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertIn(b"Change password", allowed.data)

    def test_email_reset_link_expires_and_is_single_use(self):
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_FROM"] = "reset@example.com"
        os.environ["PASSWORD_RESET_EMAIL"] = "owner@example.com"
        os.environ["PUBLIC_BASE_URL"] = "https://books.example.com"
        sent = []
        original = auth.deliver_email

        def capture(settings, subject, body):
            sent.append({"settings": settings, "subject": subject, "body": body})

        auth.deliver_email = capture
        try:
            guest = pm.app.test_client()
            form = guest.get("/forgot-password")
            self.assertIn(b"Send reset link", form.data)
            wrong = guest.post("/forgot-password", data={"username": "someone-else"})
            self.assertEqual(wrong.status_code, 200)
            self.assertEqual(sent, [])
            self.assertNotIn(b"/reset/", wrong.data)
            asked = guest.post("/forgot-password", data={"username": "admin"})
            self.assertEqual(asked.status_code, 200)
            self.assertIn(b"reset link is on its way", asked.data)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["settings"]["recipient"], "owner@example.com")
            self.assertNotIn(b"https://", asked.data)
            token = ""
            for line in sent[0]["body"].splitlines():
                if "/reset/" in line:
                    token = line.strip().split("/reset/", 1)[1]
            self.assertTrue(token)
            self.assertNotIn(token.encode(), asked.data)
            with open(DATA_FILE) as handle:
                stored = json.load(handle)["auth"]
            self.assertNotIn(token, json.dumps(stored))
            self.assertEqual(len(stored["reset_token_hash"]), 64)
            self.assertTrue(sent[0]["body"].startswith("A password reset") or "https://books.example.com/reset/" in sent[0]["body"])
            self.assertIn("https://books.example.com/reset/" + token, sent[0]["body"])

            page = guest.get("/reset/" + token)
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"New password", page.data)
            self.assertNotIn(token.encode(), page.data)
            mismatch = guest.post("/reset/" + token, data={"password": "emailed-reset-password", "confirm": "nope"})
            self.assertIn(b"do not match", mismatch.data)
            updated = guest.post(
                "/reset/" + token,
                data={"password": "emailed-reset-password", "confirm": "emailed-reset-password"},
                follow_redirects=True,
            )
            self.assertEqual(updated.status_code, 200)
            self.assertIn(b"Change password", updated.data)
            again = guest.get("/reset/" + token)
            self.assertIn(b"not valid", again.data)
            self.assertNotIn(b'name="password"', again.data)

            # A second link can be issued, then expired before it is used.
            sent.clear()
            guest.get("/logout")
            guest.post("/forgot-password", data={"username": "admin"})
            self.assertEqual(len(sent), 1)
            expired_token = ""
            for line in sent[0]["body"].splitlines():
                if "/reset/" in line:
                    expired_token = line.strip().split("/reset/", 1)[1]
            with open(DATA_FILE) as handle:
                data = json.load(handle)
            data["auth"]["reset_token_expires"] = "2000-01-01T00:00:00Z"
            data["auth"]["locked_until"] = "2999-01-01T00:00:00Z"
            with open(DATA_FILE, "w") as handle:
                json.dump(data, handle)
            expired = guest.get("/reset/" + expired_token)
            self.assertIn(b"not valid", expired.data)
            # The expired link must not clear the lock. A fresh command does.
            blocked = guest.post("/login", data={"username": "admin", "password": "emailed-reset-password"})
            self.assertIn(b"Too many sign-in attempts", blocked.data)
            result = self.run_reset("after-expired-link")
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            cleared = guest.post(
                "/login",
                data={"username": "admin", "password": "after-expired-link"},
                follow_redirects=True,
            )
            self.assertIn(b"Change password", cleared.data)

            called = {"n": 0}

            def broken(settings, subject, body):
                called["n"] += 1
                raise OSError("smtp down")

            with open(DATA_FILE) as handle:
                data = json.load(handle)
            data["auth"]["reset_requests"] = []
            with open(DATA_FILE, "w") as handle:
                json.dump(data, handle)
            auth.deliver_email = broken
            failed_send = guest.post("/forgot-password", data={"username": "admin"})
            self.assertEqual(called["n"], 1)
            self.assertNotIn(b"/reset/", failed_send.data)
            with open(DATA_FILE) as handle:
                after_failure = json.load(handle)["auth"]
            self.assertFalse(after_failure.get("reset_token_hash"))
        finally:
            auth.deliver_email = original
            os.environ.pop("SMTP_HOST", None)
            os.environ.pop("SMTP_FROM", None)
            os.environ.pop("PASSWORD_RESET_EMAIL", None)
            os.environ.pop("PUBLIC_BASE_URL", None)

    def test_demo_account_cannot_be_reset(self):
        self.assertTrue(auth.web_reset_blocked("demo"))
        os.environ["ALLOW_PASSWORD_RESET"] = "1"
        try:
            self.assertFalse(auth.web_reset_blocked("demo"))
        finally:
            os.environ.pop("ALLOW_PASSWORD_RESET", None)
        self.assertTrue(auth.web_reset_blocked("demo"))

        os.environ["DEMO_MODE"] = "1"
        try:
            guest = pm.app.test_client()
            page = guest.get("/login")
            self.assertNotIn(b"Forgot password?", page.data)
            self.assertEqual(guest.post("/forgot-password", data={"username": "admin"}).status_code, 403)
            self.assertEqual(guest.get("/reset/anything").status_code, 403)
            denied = self.client.post("/api/password", json={
                "current_password": "unit-test-password",
                "new_password": "replacement-password",
                "confirm_password": "replacement-password",
            })
            self.assertEqual(denied.status_code, 403)
            dashboard = self.client.get("/")
            self.assertNotIn(b"Change password", dashboard.data)
        finally:
            os.environ.pop("DEMO_MODE", None)

        blocked = self.run_reset("should-not-apply-here", {"DEMO_MODE": "1"})
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("DEMO_MODE", blocked.stderr)
        self.assertNotIn("should-not-apply-here", blocked.stdout)
        self.assertNotIn("should-not-apply-here", blocked.stderr)
        guest = pm.app.test_client()
        signed_in = guest.post(
            "/login",
            data={"username": "admin", "password": "unit-test-password"},
            follow_redirects=True,
        )
        self.assertIn(b"Change password", signed_in.data)

        demo_file = os.path.join(tempfile.mkdtemp(), "demo.json")
        env = os.environ.copy()
        env.update({
            "DATA_FILE": demo_file,
            "SECRET_KEY": "unit-test-secret",
            "APP_USERNAME": "demo",
            "APP_PASSWORD": "unit-test-password",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_FROM": "reset@example.com",
            "PASSWORD_RESET_EMAIL": "owner@example.com",
        })
        env.pop("DEMO_MODE", None)
        env.pop("ALLOW_PASSWORD_RESET", None)
        script = """
import json, os
from app import app
client = app.test_client()
page = client.get("/login")
assert b"Forgot password?" not in page.data, page.data
assert client.post("/forgot-password", data={"username": "demo"}).status_code == 403
signed = client.post("/login", data={"username": "demo", "password": "unit-test-password"}, follow_redirects=True)
assert signed.status_code == 200, signed.status_code
assert b"Change password" not in signed.data
changed = client.post("/api/password", json={
    "current_password": "unit-test-password",
    "new_password": "replacement-password",
    "confirm_password": "replacement-password",
})
assert changed.status_code == 403, changed.status_code
path = os.environ["DATA_FILE"]
if os.path.exists(path):
    with open(path) as handle:
        saved = json.load(handle)
    record = saved.get("auth") or {}
    assert not record.get("password_hash")
    assert not record.get("reset_token_hash")
print("demo-ok")
"""
        root = os.path.dirname(os.path.abspath(pm.__file__))
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("demo-ok", result.stdout)

    def test_last_year_plain_categories_and_demo_seed(self):
        prop = self.add_property()
        self.client.post("/api/income", json={
            "property_id": prop["id"],
            "amount": 100,
            "date": "2026-05-01",
            "income_type": "Rent",
            "description": "May rent",
        })
        self.client.post("/api/income", json={
            "property_id": prop["id"],
            "amount": 9999,
            "date": "2024-01-01",
            "income_type": "Rent",
            "description": "Old rent",
        })
        summary = self.client.get("/api/summary?period=last12").get_json()
        self.assertEqual(summary["income"], 100)
        self.assertEqual(summary["period"]["start"], "2025-10-30")
        self.assertEqual(summary["period"]["end"], "2026-10-30")
        self.client.post("/api/expenses", json={
            "property_id": prop["id"],
            "amount": 50,
            "date": "2026-05-02",
            "category": "Bond Capital Payment (Equity - Not Deductible)",
            "description": "Capital",
        })
        listed = self.client.get("/api/expenses?period=last12").get_json()
        self.assertEqual(listed[0]["category"], "Bond capital payment")
        categories = self.client.get("/api/summary?period=last12").get_json()["by_category"]
        self.assertEqual(categories[0]["category"], "Bond capital payment")
        script = self.client.get("/static/js/app.js")
        self.assertIn(b"Confirm delete", script.data)
        self.assertEqual(pm.labels.format_zar(8500), "R 8,500.00")
        self.assertEqual(pm.labels.format_zar(-8500), "R -8,500.00")
        self.assertNotIn(" ", pm.labels.format_zar(8500).replace("R ", "", 1))
        format_js = self.client.get("/static/js/format.js")
        self.assertEqual(format_js.status_code, 200)
        compared = subprocess.run(
            ["node", "-e", format_js.get_data(as_text=True) + "\nconsole.log(formatZar(8500)); console.log(formatZar(-1200.5));"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(compared.stdout.splitlines(), ["R 8,500.00", pm.labels.format_zar(-1200.5)])
        icon = self.client.get("/favicon.ico")
        self.assertEqual(icon.status_code, 200)
        self.assertTrue(icon.data[:4] in (b"\x00\x00\x01\x00", b"\x89PNG"))
        self.assertEqual(self.client.get("/static/favicon.svg").status_code, 200)
        css = self.client.get("/static/css/app.css").get_data(as_text=True)
        self.assertIn(".invoice-no", css)
        self.assertIn("nowrap", css)
        self.assertIn("--muted: #2d3748", css)
        self.assertEqual(pm.labels.format_qty(1.0), "1")
        self.assertEqual(pm.labels.format_qty(1.5), "1.50")

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "rental_data.json")
        with open(path, "w") as handle:
            json.dump({
                "properties": [{"id": "1", "name": "Unit A", "kind": "Residential"}],
                "income": [{
                    "id": "x",
                    "property_id": "1",
                    "amount": 20000,
                    "date": "2026-08-01",
                    "income_type": "Recovery",
                    "recovery_category": "Electricity",
                    "description": "Electricity",
                    "tenant": "",
                }],
                "expenses": [],
                "maintenance": [],
                "invoices": [],
                "settings": {"organisation_name": "Keep Me"},
                "auth": {"password_hash": "stay"},
            }, handle)
        old_file = pm.DATA_FILE
        os.environ["DEMO_MODE"] = "1"
        pm.DATA_FILE = path
        try:
            pm.ensure_demo_story()
            with open(path) as handle:
                saved = json.load(handle)
            self.assertEqual(saved["settings"]["organisation_name"], "Keep Me")
            self.assertEqual(saved["auth"]["password_hash"], "stay")
            rents = [row for row in saved["income"] if row.get("income_type") == "Rent"]
            self.assertGreaterEqual(len(rents), 24)
            self.assertGreaterEqual(len({row["date"][:7] for row in rents}), 8)
            self.assertEqual(saved["demo_seed"], pm.demo_data.DEMO_SEED_VERSION)
            statuses = {row.get("status") for row in saved["invoices"]}
            self.assertGreaterEqual(len(saved["invoices"]), 5)
            self.assertTrue({"Draft", "Paid", "Overdue", "Outstanding"} <= statuses)
            months = {row["date"][:7] for row in saved["invoices"]}
            self.assertGreaterEqual(len(months), 4)
            self.assertTrue(any(row.get("name") == "Company Expenses" and row.get("kind") == "Overhead" for row in saved["properties"]))
            pm.ensure_demo_story()
            with open(path) as handle:
                again = json.load(handle)
            self.assertEqual(len(again["income"]), len(saved["income"]))
        finally:
            os.environ.pop("DEMO_MODE", None)
            pm.DATA_FILE = old_file

        kept = os.path.join(folder, "kept.json")
        with open(kept, "w") as handle:
            json.dump({
                "properties": [{"id": "1", "name": "Real Unit", "kind": "Residential"}],
                "income": [{
                    "id": "rent",
                    "property_id": "1",
                    "amount": 500,
                    "date": "2026-06-01",
                    "income_type": "Rent",
                    "description": "Rent",
                    "tenant": "A. Tenant",
                }],
                "expenses": [],
                "maintenance": [],
                "invoices": [],
            }, handle)
        os.environ["DEMO_MODE"] = "1"
        pm.DATA_FILE = kept
        try:
            pm.ensure_demo_story()
            with open(kept) as handle:
                untouched = json.load(handle)
            self.assertEqual(untouched["income"][0]["amount"], 500)
            self.assertNotIn("demo_seed", untouched)
        finally:
            os.environ.pop("DEMO_MODE", None)
            pm.DATA_FILE = old_file

    def form_token(self, page):
        match = re.search(br'name="form_token" value="([^"]+)"', page.data)
        self.assertIsNotNone(match)
        return match.group(1).decode("ascii")

    def test_health_reports_the_release_version(self):
        body = self.client.get("/health").get_json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["version"], "1.5.0")

    def test_setup_is_hidden_on_a_server_install(self):
        guest = pm.app.test_client()
        self.assertEqual(guest.get("/setup").status_code, 404)
        self.assertEqual(guest.get("/desktop-reset").status_code, 404)
        self.assertEqual(guest.get("/quit").status_code, 404)
        login = guest.get("/login")
        self.assertIn(b"Version 1.5.0", login.data)
        self.assertIn(b"/forgot-password", login.data)
        self.assertNotIn(b"/desktop-reset", login.data)

    def test_desktop_starts_without_a_bootstrap_password(self):
        env = os.environ.copy()
        env["NEXERA_DESKTOP"] = "1"
        env["SECRET_KEY"] = "unit-test-secret"
        env["DATA_FILE"] = DATA_FILE
        env.pop("APP_PASSWORD", None)
        env.pop("FLASK_DEBUG", None)
        root = os.path.dirname(os.path.abspath(pm.__file__))
        result = subprocess.run(
            [sys.executable, "-c", "import app; print(repr(app.VALID_PASSWORD)); print(app.VERSION)"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("None", result.stdout)
        self.assertIn("1.5.0", result.stdout)

    def test_desktop_setup_reset_and_quit_stay_on_this_computer(self):
        saved = pm.VALID_PASSWORD
        pm.VALID_PASSWORD = None
        pm._desktop_ready = False
        os.environ["NEXERA_DESKTOP"] = "1"
        try:
            guest = pm.app.test_client()
            self.assertEqual(
                guest.get("/setup", environ_overrides={"REMOTE_ADDR": "8.8.8.8"}).status_code,
                404,
            )
            home = guest.get("/", follow_redirects=True)
            self.assertIn(b"Choose a password", home.data)
            self.assertIn(b"admin", home.data)
            self.assertNotIn(b"python3", home.data)
            missing = guest.post("/setup", data={
                "password": "desktop-password",
                "confirm": "desktop-password",
            })
            self.assertIn(b"This page expired", missing.data)
            token = self.form_token(guest.get("/setup"))
            mismatch = guest.post("/setup", data={
                "form_token": token,
                "password": "desktop-password",
                "confirm": "desktop-other-pw",
            })
            self.assertIn(b"do not match", mismatch.data)
            token = self.form_token(mismatch)
            opened = guest.post(
                "/setup",
                data={
                    "form_token": token,
                    "password": "desktop-password",
                    "confirm": "desktop-password",
                },
                follow_redirects=True,
            )
            self.assertEqual(opened.status_code, 200)
            self.assertIn(b"This computer", opened.data)
            self.assertIn(b"Version 1.5.0", opened.data)
            with open(DATA_FILE) as handle:
                stored = json.load(handle)
            self.assertTrue(stored["auth"]["password_hash"])
            self.assertNotIn("desktop-password", json.dumps(stored))

            guest.get("/logout")
            denied = guest.post("/login", data={"username": "admin", "password": "unit-test-password"})
            self.assertIn(b"Invalid credentials", denied.data)
            login = guest.get("/login")
            self.assertIn(b"/desktop-reset", login.data)
            self.assertNotIn(b"python3 app.py reset-password", login.data)

            remote = guest.get("/desktop-reset", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
            self.assertEqual(remote.status_code, 404)
            reset_page = guest.get("/desktop-reset")
            token = self.form_token(reset_page)
            reset = guest.post(
                "/desktop-reset",
                data={
                    "form_token": token,
                    "password": "another-desktop-password",
                    "confirm": "another-desktop-password",
                },
                follow_redirects=True,
            )
            self.assertIn(b"This computer", reset.data)
            guest.get("/logout")
            signed = guest.post(
                "/login",
                data={"username": "admin", "password": "another-desktop-password"},
                follow_redirects=True,
            )
            self.assertIn(b"Change password", signed.data)

            self.assertEqual(
                guest.get("/quit", environ_overrides={"REMOTE_ADDR": "8.8.8.8"}).status_code,
                404,
            )
            calls = []
            original = pm.stop_process
            pm.stop_process = lambda: calls.append("stop")
            pm.QUIT_DELAY_SECONDS = 0
            try:
                quit_page = guest.get("/quit")
                token = self.form_token(quit_page)
                closed = guest.post("/quit", data={"form_token": token})
                self.assertIn(b"Nexera has closed", closed.data)
                deadline = time.time() + 2
                while not calls and time.time() < deadline:
                    time.sleep(0.02)
                self.assertEqual(calls, ["stop"])
            finally:
                pm.stop_process = original
                pm.QUIT_DELAY_SECONDS = 0.4
        finally:
            pm.VALID_PASSWORD = saved
            pm._desktop_ready = False
            os.environ.pop("NEXERA_DESKTOP", None)

    def test_desktop_launcher_keeps_one_copy_and_its_own_secret(self):
        folder = tempfile.mkdtemp()
        saved = os.environ.get("NEXERA_DATA_DIR")
        os.environ["NEXERA_DATA_DIR"] = folder
        try:
            self.assertEqual(desktop.choose_data_dir(), os.path.abspath(folder))
            first = desktop.load_or_create_secret(folder)
            second = desktop.load_or_create_secret(folder)
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 32)
            mode = os.stat(os.path.join(folder, "secret_key")).st_mode
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(mode) & 0o077, 0)
            self.assertTrue(desktop.claim_lock(folder))
            self.assertFalse(desktop.claim_lock(folder))
            desktop.release_lock(folder)
            self.assertFalse(os.path.exists(os.path.join(folder, "nexera.lock")))
            with open(os.path.join(folder, "nexera.lock"), "w") as handle:
                handle.write("99999999")
            self.assertTrue(desktop.claim_lock(folder))
            desktop.release_lock(folder)
            self.assertIsNone(desktop.running_url(folder))
        finally:
            if saved is None:
                os.environ.pop("NEXERA_DATA_DIR", None)
            else:
                os.environ["NEXERA_DATA_DIR"] = saved

    def test_double_click_opens_the_password_page(self):
        folder = tempfile.mkdtemp()
        env = os.environ.copy()
        env["NEXERA_DATA_DIR"] = folder
        env["NEXERA_NO_BROWSER"] = "1"
        env.pop("FLASK_DEBUG", None)
        root = os.path.dirname(os.path.abspath(pm.__file__))
        proc = subprocess.Popen(
            [sys.executable, os.path.join(root, "desktop.py")],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        stderr_parts = []

        def drain_stderr():
            if proc.stderr is not None:
                stderr_parts.append(proc.stderr.read())

        threading.Thread(target=drain_stderr, daemon=True).start()
        try:
            base = None
            deadline = time.time() + 25
            while time.time() < deadline:
                if proc.poll() is not None:
                    time.sleep(0.2)
                    self.fail("desktop app stopped: " + "".join(stderr_parts))
                port_path = os.path.join(folder, "port")
                if os.path.exists(port_path):
                    with open(port_path, encoding="utf-8") as handle:
                        port = handle.read().strip()
                    base = "http://127.0.0.1:%s/" % port
                    try:
                        with urllib.request.urlopen(base + "health", timeout=1) as response:
                            body = json.loads(response.read().decode("utf-8"))
                        if body.get("version") == "1.5.0":
                            break
                    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
                        base = None
                time.sleep(0.2)
            else:
                details = ["".join(stderr_parts)]
                for name in ("startup.txt", "nexera.log", "port"):
                    path = os.path.join(folder, name)
                    if os.path.isfile(path):
                        with open(path, encoding="utf-8") as handle:
                            details.append(name + ":\n" + handle.read()[:2000])
                self.fail("desktop app did not answer\n" + "\n".join(details))
            with urllib.request.urlopen(base + "setup", timeout=5) as response:
                page = response.read()
            self.assertIn(b"Choose a password", page)
            self.assertIn(b"Version 1.5.0", page)
            self.assertNotIn(b"python3", page)
            self.assertTrue(os.path.isfile(os.path.join(folder, "secret_key")))
            with urllib.request.urlopen(base + "login", timeout=5) as response:
                self.assertIn(b"Choose a password", response.read())
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def has_text(values, snippet):
    return any(snippet in str(value) for value in values)


def sheet_values(book):
    values = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            for value in row:
                if value is None or value == "":
                    continue
                if isinstance(value, float) and value.is_integer():
                    value = int(value)
                values.append(value)
    return values


def iter_cells(book):
    sheets = book.worksheets if hasattr(book, "worksheets") else [book]
    for sheet in sheets:
        for row in sheet.iter_rows():
            for cell in row:
                yield cell


def cell_is_rand(cell):
    return "R" in str(cell.number_format)

def pdf_bytes(data):
    parts = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = match.group(1)
        try:
            parts.append(zlib.decompress(raw))
        except zlib.error:
            parts.append(raw)
    text = b"\n".join(parts)
    return text.replace(b"\\(", b"(").replace(b"\\)", b")")


if __name__ == "__main__":
    unittest.main()
