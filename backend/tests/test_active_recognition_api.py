from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from app.database import init_db


class ActiveRecognitionApiTest(unittest.TestCase):
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

    def _seed_running_job(self) -> int:
        ts = "2026-06-17T00:00:00+00:00"
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO invoices(original_filename, stored_filename, file_path, mime_type,
                                     status, uploaded_at, updated_at)
                VALUES ('a.pdf', 'a.pdf', '/tmp/a.pdf', 'application/pdf', 'pending', ?, ?)
                """,
                (ts, ts),
            )
            invoice_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO recognition_jobs(id, status, total, processed, succeeded, failed_count,
                                             created_at, updated_at)
                VALUES ('job-active', 'running', 1, 0, 0, 0, ?, ?)
                """,
                (ts, ts),
            )
            conn.execute(
                """
                INSERT INTO recognition_job_items(job_id, invoice_id, status, created_at, updated_at)
                VALUES ('job-active', ?, 'running', ?, ?)
                """,
                (invoice_id, ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
        return invoice_id

    def test_active_recognition_reports_running_job_and_invoice(self) -> None:
        invoice_id = self._seed_running_job()
        data = self.client.get("/api/recognition/active").json()
        self.assertIsNotNone(data["job"])
        self.assertEqual(data["job"]["id"], "job-active")
        self.assertEqual(data["invoice_ids"], [invoice_id])

    def test_active_recognition_empty_when_no_running_job(self) -> None:
        data = self.client.get("/api/recognition/active").json()
        self.assertIsNone(data["job"])
        self.assertEqual(data["invoice_ids"], [])

    def test_start_recognition_rejects_invoice_already_running(self) -> None:
        invoice_id = self._seed_running_job()
        response = self.client.post("/api/recognition/jobs", json={"invoice_ids": [invoice_id]})
        self.assertEqual(response.status_code, 409)

    def test_active_upload_preview_null_when_none(self) -> None:
        response = self.client.get("/api/upload-preview/active")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_active_upload_preview_returns_running_job(self) -> None:
        ts = "2026-06-17T00:00:00+00:00"
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO invoices(original_filename, stored_filename, file_path, mime_type,
                                     status, uploaded_at, updated_at)
                VALUES ('b.pdf', 'b.pdf', '/tmp/b.pdf', 'application/pdf', 'pending', ?, ?)
                """,
                (ts, ts),
            )
            invoice_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO upload_preview_jobs(id, status, total, processed, succeeded, failed_count,
                                                created_at, updated_at)
                VALUES ('preview-active', 'running', 1, 0, 0, 0, ?, ?)
                """,
                (ts, ts),
            )
            conn.execute(
                """
                INSERT INTO upload_preview_job_items(job_id, invoice_id, status, created_at, updated_at)
                VALUES ('preview-active', ?, 'running', ?, ?)
                """,
                (invoice_id, ts, ts),
            )
            conn.commit()
        finally:
            conn.close()

        data = self.client.get("/api/upload-preview/active").json()
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], "preview-active")
        self.assertEqual(data["status"], "running")


if __name__ == "__main__":
    unittest.main()
