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


def pdf_bytes(data):
    parts = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = match.group(1)
        try:
            parts.append(zlib.decompress(raw))
        except zlib.error:
            parts.append(raw)
    return b"\n".join(parts)


if __name__ == "__main__":
    unittest.main()
