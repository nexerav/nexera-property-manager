import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zlib
from datetime import datetime as RealDateTime

from openpyxl import load_workbook

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
        self.assertNotIn(b"Open Source", page.data)
        self.assertIn("Premium feature – contact Nexera Ventures".encode(), page.data)
        self.assertIn(b"Advanced charts", page.data)
        premium = self.client.get("/premium")
        self.assertEqual(premium.get_json()["message"], "Premium feature – contact Nexera Ventures")

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
        self.assertIn(b"8350.00", page.data)

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
            "/export/profit-and-loss.pdf?period=month",
            "/export/profit-and-loss.xlsx?period=month",
            "/export/rent-roll.pdf?period=month",
            "/export/rent-roll.xlsx?period=month",
            "/export/transactions.pdf?period=month",
            "/export/transactions.xlsx?period=month",
            "/export/invoices.pdf?period=month",
            "/export/invoices.xlsx?period=month",
            "/export/tenant-statement.pdf?period=month",
            "/export/tenant-statement.xlsx?period=month",
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
            b"Bond Interest (Tax Deductible)",
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
        self.assertTrue(has_text(pl_values, "Bond Interest (Tax Deductible)"))
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
