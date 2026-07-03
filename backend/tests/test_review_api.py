from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from app import main as main_module
from app.database import init_db, now_iso, upsert_extracted_data
from app.main import app
from app.review_labels import attach_model_snapshot


class ReviewApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.pending_file = Path(self.tmpdir.name) / "invoice.pdf"
        self.pending_file.write_bytes(b"%PDF-1.4\n")
        self.confirmed_dir = Path(self.tmpdir.name) / "confirmed"
        self.confirmed_dir.mkdir()
        self.patch_db = patch.object(database, "DB_PATH", self.db_path)
        self.patch_db.start()
        self.patch_confirmed_dir = patch.object(main_module, "CONFIRMED_DIR", self.confirmed_dir)
        self.patch_confirmed_dir.start()
        init_db()
        timestamp = now_iso()
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                VALUES ('1000', 'ACME MATERIALS CO.,LTD.', ?, ?)
                """,
                (timestamp, timestamp),
            )
            cur.execute(
                """
                INSERT INTO invoices(
                    original_filename, stored_filename, file_path, mime_type,
                    status, uploaded_at, recognized_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'recognized', ?, ?, ?)
                """,
                ("invoice.pdf", "invoice.pdf", str(self.pending_file), "application/pdf", timestamp, timestamp, timestamp),
            )
            self.invoice_id = int(cur.lastrowid)
            self._upsert_data(
                cur,
                {
                    "vendor_code": "1000",
                    "vendor_name": "ACME MATERIALS CO.,LTD.",
                    "PO_number": "",
                    "invoice_number": "INV-1",
                    "invoice_date": "05/01/2026",
                    "total_amount": 182.0,
                },
            )
        main_module.supplier_matcher.reload()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patch_confirmed_dir.stop()
        self.patch_db.stop()
        self.tmpdir.cleanup()

    def _upsert_data(self, cur, data: dict[str, object]) -> None:
        upsert_extracted_data(cur, self.invoice_id, data)

    def test_confirm_review_field_endpoint_is_removed(self) -> None:
        response = self.client.post(
            f"/api/invoices/{self.invoice_id}/review-fields/confirm",
            json={"field_key": "invoice_number"},
        )

        self.assertEqual(response.status_code, 404)

    def test_confirm_invoice_has_no_hitl_field_gate(self) -> None:
        with patch.dict(os.environ, {"HITL_REVIEW_ENABLED": "1"}):
            response = self.client.post(f"/api/invoices/{self.invoice_id}/confirm")

        self.assertEqual(response.status_code, 200, response.text)

    def test_confirm_invoice_does_not_record_hitl_when_disabled(self) -> None:
        with database.db_cursor() as cur:
            self._upsert_data(
                cur,
                attach_model_snapshot(
                    {
                        "vendor_code": "1000",
                        "vendor_name": "ACME MATERIALS CO.,LTD.",
                        "invoice_number": "INV-2",
                        "invoice_date": "05/01/2026",
                        "total_amount": 182.0,
                    }
                ),
            )

        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post(f"/api/invoices/{self.invoice_id}/confirm")

        self.assertEqual(response.status_code, 200, response.text)
        with database.db_cursor() as cur:
            count = cur.execute("SELECT COUNT(*) AS count FROM review_confirmations").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_confirm_invoice_records_changed_confirmation_when_hitl_enabled(self) -> None:
        original = {
            "vendor_code": "1000",
            "vendor_name": "ACME MATERIALS CO.,LTD.",
            "PO_number": "",
            "invoice_number": "INV-1",
            "invoice_date": "05/01/2026",
            "total_amount": 182.0,
        }
        changed = attach_model_snapshot(original)
        changed["invoice_number"] = "INV-2"
        with database.db_cursor() as cur:
            self._upsert_data(cur, changed)

        with patch.dict(os.environ, {"HITL_REVIEW_ENABLED": "1"}):
            response = self.client.post(f"/api/invoices/{self.invoice_id}/confirm")

        self.assertEqual(response.status_code, 200, response.text)
        with database.db_cursor() as cur:
            confirmation = cur.execute("SELECT * FROM review_confirmations").fetchone()
            legacy_tables = cur.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name IN ('review_field_labels', 'review_model_snapshots')
                """
            ).fetchall()
        self.assertIsNotNone(confirmation)
        self.assertEqual(json.loads(confirmation["fields_changed_json"]), ["invoice_number"])
        self.assertEqual(int(confirmation["was_corrected"]), 1)
        self.assertEqual(legacy_tables, [])

    def test_confirm_invoice_skips_unchanged_confirmation_when_hitl_enabled(self) -> None:
        data = attach_model_snapshot(
            {
                "vendor_code": "1000",
                "vendor_name": "ACME MATERIALS CO.,LTD.",
                "PO_number": "",
                "invoice_number": "INV-1",
                "invoice_date": "05/01/2026",
                "total_amount": 182.0,
            }
        )
        with database.db_cursor() as cur:
            self._upsert_data(cur, data)

        with patch.dict(os.environ, {"HITL_REVIEW_ENABLED": "1"}):
            response = self.client.post(f"/api/invoices/{self.invoice_id}/confirm")

        self.assertEqual(response.status_code, 200, response.text)
        with database.db_cursor() as cur:
            count = cur.execute("SELECT COUNT(*) AS count FROM review_confirmations").fetchone()["count"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
