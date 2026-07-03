from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from app.database import init_db, upsert_extracted_data


class SupplierCrudApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self._patch = patch.object(database, "DB_PATH", self.db_path)
        self._patch.start()
        init_db()
        from app.main import app, supplier_matcher

        supplier_matcher.reload()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._patch.stop()
        self.tmpdir.cleanup()

    def test_create_supplier(self) -> None:
        response = self.client.post("/api/suppliers", json={"code": "NEW001", "name": "New Supplier"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "NEW001")

        listed = self.client.get("/api/suppliers").json()
        self.assertTrue(any(item["code"] == "NEW001" for item in listed))

    def test_create_duplicate_code_rejected(self) -> None:
        self.client.post("/api/suppliers", json={"code": "DUP001", "name": "A"})
        response = self.client.post("/api/suppliers", json={"code": "DUP001", "name": "B"})
        self.assertEqual(response.status_code, 409)

    def test_delete_supplier_cascades_operational_data_but_preserves_invoices_and_schemes(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                    VALUES ('DEL001', 'Supplier To Delete', '2026-05-11', '2026-05-11');
                INSERT OR IGNORE INTO schemes(name, prompt_body, fields_json, export_settings_json,
                                    is_default, created_at, updated_at)
                    VALUES ('default', '', '[]', '', 1, '2026-05-11', '2026-05-11');
                INSERT INTO schemes(name, prompt_body, fields_json, export_settings_json,
                                    is_default, created_at, updated_at)
                    VALUES ('Scheme To Delete', '', '[]', '', 0, '2026-05-11', '2026-05-11');
                INSERT INTO supplier_scheme_map(vendor_code, scheme_name, updated_at)
                    VALUES ('DEL001', 'Scheme To Delete', '2026-05-11');
                INSERT INTO llm_calls(ts, request_id, provider, model, stage, success, supplier_code)
                    VALUES ('2026-05-11', 'req-1', 'gemini', 'flash', 'extract', 1, 'DEL001');
                INSERT INTO invoices(original_filename, stored_filename, file_path, mime_type,
                                     status, uploaded_at, updated_at, vendor_code, vendor_name,
                                     po_number, invoice_number, invoice_date, invoice_date_iso,
                                     total_amount, expense_type, invoice_category)
                    VALUES ('a.pdf', 'a.pdf', '/tmp/a.pdf', 'application/pdf',
                            'confirmed', '2026-05-11', '2026-05-11', 'DEL001', 'Supplier To Delete',
                            '', '', '', '', 0, '', '');
                INSERT INTO supplier_expense_type_history(invoice_id, vendor_code, expense_type, selected_at)
                    VALUES (1, 'DEL001', 'X', '2026-05-11');
                """
            )
            conn.commit()
        finally:
            conn.close()

        response = self.client.delete("/api/suppliers/DEL001")
        self.assertEqual(response.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM suppliers WHERE code='DEL001'").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM supplier_scheme_map WHERE vendor_code='DEL001'").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM supplier_expense_type_history WHERE vendor_code='DEL001'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM llm_calls WHERE supplier_code='DEL001'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices WHERE vendor_code='DEL001'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM schemes WHERE name='Scheme To Delete'").fetchone()[0], 1)
        finally:
            conn.close()

    def test_delete_unknown_supplier_404(self) -> None:
        response = self.client.delete("/api/suppliers/NONEXISTENT")
        self.assertEqual(response.status_code, 404)

    def test_confirm_pending_supplier_uses_latest_normalized_supplier_library(self) -> None:
        with database.db_cursor() as cur:
            cur.execute(
                "INSERT INTO suppliers(code, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("20003187", "TK ELEVATOR\u00a0CORPORATION", "2026-05-11", "2026-05-11"),
            )
            cur.execute(
                """
                INSERT INTO invoices(original_filename, stored_filename, file_path, mime_type,
                                     status, uploaded_at, updated_at)
                VALUES ('4800014329.pdf', '4800014329.pdf', '/tmp/4800014329.pdf',
                        'application/pdf', 'pending', '2026-05-11', '2026-05-11')
                """
            )
            invoice_id = cur.lastrowid
            upsert_extracted_data(
                cur,
                invoice_id,
                {
                    "document_type": "invoice",
                    "document_is_invoice": "True",
                    "Is_Invoice": "True",
                },
            )

        response = self.client.post(
            f"/api/invoices/{invoice_id}/supplier-confirm",
            json={"vendor_code": "20003187", "vendor_name": "TK ELEVATOR CORPORATION"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["vendor_code"], "20003187")
        self.assertEqual(payload["vendor_name"], "TK ELEVATOR CORPORATION")
        self.assertEqual(payload["extracted_data"]["supplier_confirmed"], "True")


if __name__ == "__main__":
    unittest.main()
