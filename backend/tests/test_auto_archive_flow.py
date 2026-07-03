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
from app.main import AUTO_ARCHIVE_FAILED_FIELDS_KEY, app


class AutoArchiveFlowTest(unittest.TestCase):
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
        main_module._ensure_default_scheme()
        self.client = TestClient(app)
        self.timestamp = now_iso()
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                VALUES ('1000', 'ACME SUPPLY', ?, ?)
                """,
                (self.timestamp, self.timestamp),
            )
        main_module.supplier_matcher.reload()

    def tearDown(self) -> None:
        self.patch_confirmed_dir.stop()
        self.patch_db.stop()
        self.tmpdir.cleanup()

    def _insert_invoice(self, data: dict[str, object]) -> int:
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO invoices(
                    original_filename, stored_filename, file_path, mime_type,
                    status, uploaded_at, recognized_at, updated_at,
                    vendor_code, vendor_name, invoice_number, invoice_date, total_amount
                )
                VALUES (?, ?, ?, ?, 'recognized', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "invoice.pdf",
                    "invoice.pdf",
                    str(self.pending_file),
                    "application/pdf",
                    self.timestamp,
                    self.timestamp,
                    self.timestamp,
                    "1000",
                    "ACME SUPPLY",
                    str(data.get("invoice_number") or "INV-1"),
                    str(data.get("invoice_date") or "05/01/2026"),
                    float(data.get("total_amount") or 0),
                ),
            )
            invoice_id = int(cur.lastrowid)
            upsert_extracted_data(cur, invoice_id, data)
        return invoice_id

    def _fields(self, baseline: str = "1000.00") -> list[dict[str, object]]:
        return [{
            "key": "total_amount",
            "type": "value",
            "auto_archive_check": {
                "enabled": True,
                "baseline_value": baseline,
                "tolerance_percent": "1",
            },
        }]

    def test_passing_checks_confirm_invoice_without_hitl_record(self) -> None:
        invoice_id = self._insert_invoice({
            "vendor_code": "1000",
            "vendor_name": "ACME SUPPLY",
            "invoice_number": "INV-1",
            "invoice_date": "05/01/2026",
            "total_amount": "1009.99",
        })

        with patch.dict(os.environ, {"HITL_REVIEW_ENABLED": "1"}):
            result = main_module._try_auto_archive_after_recognition(invoice_id, {
                "vendor_code": "1000",
                "vendor_name": "ACME SUPPLY",
                "invoice_number": "INV-1",
                "invoice_date": "05/01/2026",
                "total_amount": "1009.99",
            }, self._fields())

        self.assertTrue(result["auto_archived"])
        invoice = main_module._get_invoice(invoice_id)
        self.assertEqual(invoice["status"], "confirmed")
        self.assertTrue(Path(invoice["file_path"]).exists())
        self.assertFalse(self.pending_file.exists())
        with database.db_cursor() as cur:
            count = cur.execute("SELECT COUNT(*) AS count FROM review_confirmations").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_failing_checks_keep_invoice_in_review_and_store_failed_fields(self) -> None:
        invoice_id = self._insert_invoice({
            "vendor_code": "1000",
            "vendor_name": "ACME SUPPLY",
            "invoice_number": "INV-2",
            "invoice_date": "05/01/2026",
            "total_amount": "1011.00",
        })

        result = main_module._try_auto_archive_after_recognition(invoice_id, {
            "vendor_code": "1000",
            "vendor_name": "ACME SUPPLY",
            "invoice_number": "INV-2",
            "invoice_date": "05/01/2026",
            "total_amount": "1011.00",
        }, self._fields())

        self.assertFalse(result["auto_archived"])
        invoice = main_module._get_invoice(invoice_id)
        self.assertEqual(invoice["status"], "recognized")
        data = database.get_extracted_data(invoice_id)
        self.assertEqual(data[AUTO_ARCHIVE_FAILED_FIELDS_KEY], ["total_amount"])

    def test_job_response_summarizes_auto_archived_suppliers(self) -> None:
        job_id = "job-1"
        first_id = self._insert_invoice({"vendor_code": "1000", "vendor_name": "ACME SUPPLY", "total_amount": "1000"})
        second_id = self._insert_invoice({"vendor_code": "1000", "vendor_name": "ACME SUPPLY", "total_amount": "1000"})
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO recognition_jobs(id, status, total, processed, succeeded, failed_count, created_at, updated_at)
                VALUES (?, 'completed', 2, 2, 2, 0, ?, ?)
                """,
                (job_id, self.timestamp, self.timestamp),
            )
            for invoice_id in (first_id, second_id):
                cur.execute(
                    """
                    INSERT INTO recognition_job_items(job_id, invoice_id, status, result_json, created_at, updated_at)
                    VALUES (?, ?, 'succeeded', ?, ?, ?)
                    """,
                    (
                        job_id,
                        invoice_id,
                        json.dumps({"auto_archived": True, "vendor_code": "1000", "vendor_name": "ACME SUPPLY"}),
                        self.timestamp,
                        self.timestamp,
                    ),
                )

        response = self.client.get(f"/api/recognition/jobs/{job_id}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["auto_archived_by_supplier"], [{
            "vendor_code": "1000",
            "vendor_name": "ACME SUPPLY",
            "count": 2,
        }])


if __name__ == "__main__":
    unittest.main()
