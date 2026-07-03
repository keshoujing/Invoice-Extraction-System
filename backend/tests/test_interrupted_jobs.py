from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app import main as main_module
from app.database import db_cursor, init_db, now_iso, upsert_extracted_data


class InterruptedJobsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.patch_db = patch.object(database, "DB_PATH", self.db_path)
        self.patch_db.start()
        init_db()
        self.timestamp = now_iso()

    def tearDown(self) -> None:
        self.patch_db.stop()
        self.tmpdir.cleanup()

    def test_startup_recovery_marks_stuck_upload_preview_failed(self) -> None:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO invoices(
                    original_filename, stored_filename, file_path, mime_type,
                    status, uploaded_at, updated_at
                )
                VALUES ('invoice.pdf', 'invoice.pdf', 'invoice.pdf', 'application/pdf', 'pending', ?, ?)
                """,
                (self.timestamp, self.timestamp),
            )
            invoice_id = int(cur.lastrowid)
            upsert_extracted_data(
                cur,
                invoice_id,
                {
                    "supplier_stage": "scanning",
                    "supplier_warning": "Supplier preview in progress...",
                },
            )
            cur.execute(
                """
                INSERT INTO upload_preview_jobs(id, status, total, processed, succeeded, failed_count, created_at, updated_at)
                VALUES ('job-1', 'running', 1, 0, 0, 0, ?, ?)
                """,
                (self.timestamp, self.timestamp),
            )
            cur.execute(
                """
                INSERT INTO upload_preview_job_items(job_id, invoice_id, status, created_at, updated_at)
                VALUES ('job-1', ?, 'running', ?, ?)
                """,
                (invoice_id, self.timestamp, self.timestamp),
            )

        main_module._mark_interrupted_jobs_failed()

        with db_cursor() as cur:
            job = cur.execute("SELECT * FROM upload_preview_jobs WHERE id = 'job-1'").fetchone()
            item = cur.execute("SELECT * FROM upload_preview_job_items WHERE job_id = 'job-1'").fetchone()
            invoice = cur.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            data_row = cur.execute("SELECT data_json FROM extracted_data WHERE invoice_id = ?", (invoice_id,)).fetchone()

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["processed"], 1)
        self.assertEqual(job["failed_count"], 1)
        self.assertEqual(item["status"], "failed")
        self.assertEqual(invoice["error_message"], main_module.INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE)
        data = json.loads(data_row["data_json"])
        self.assertEqual(data["supplier_stage"], "needs_confirmation")
        self.assertEqual(data["supplier_warning"], main_module.INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE)


if __name__ == "__main__":
    unittest.main()
