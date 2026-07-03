from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import _migration_006_add_review_labels, _migration_007_simplify_hitl_review_confirmations
from app.review_labels import (
    HITL_MODEL_OUTPUT_KEY,
    attach_model_snapshot,
    changed_fields,
    model_snapshot_from_data,
    public_review_data,
    record_review_confirmation,
)


class ReviewLabelsTest(unittest.TestCase):
    def test_attach_model_snapshot_keeps_internal_snapshot_out_of_public_data(self) -> None:
        data = {"invoice_number": "INV-1", HITL_MODEL_OUTPUT_KEY: {"invoice_number": "OLD"}}

        next_data = attach_model_snapshot(data)

        self.assertEqual(next_data[HITL_MODEL_OUTPUT_KEY], {"invoice_number": "INV-1"})
        self.assertEqual(model_snapshot_from_data(next_data), {"invoice_number": "INV-1"})
        self.assertEqual(public_review_data(next_data), {"invoice_number": "INV-1"})

    def test_changed_fields_normalizes_dates_amounts_and_ids(self) -> None:
        model = {
            "invoice_number": " 000123 ",
            "invoice_date": "2026-05-01",
            "total_amount": "182",
            "PO_number": "",
        }
        confirmed = {
            "invoice_number": "123",
            "invoice_date": "05/01/2026",
            "total_amount": "182.00",
            "PO_number": "60001",
        }

        self.assertEqual(
            changed_fields(model, confirmed, ("invoice_number", "invoice_date", "total_amount", "PO_number")),
            ["PO_number"],
        )


class ReviewLabelMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute(
            """
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                uploaded_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_migration_006_adds_only_review_confirmations(self) -> None:
        _migration_006_add_review_labels(self.conn.cursor())

        table_names = {
            row["name"]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        self.assertIn("review_confirmations", table_names)
        self.assertNotIn("review_model_snapshots", table_names)
        self.assertNotIn("review_field_labels", table_names)

    def test_migration_007_drops_legacy_hitl_tables_and_columns(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE review_model_snapshots(id INTEGER PRIMARY KEY);
            CREATE TABLE review_field_labels(id INTEGER PRIMARY KEY);
            CREATE TABLE review_confirmations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                confirmed_at TEXT NOT NULL,
                source_status TEXT NOT NULL,
                model_output_json TEXT NOT NULL,
                user_confirmed_json TEXT NOT NULL,
                required_fields_json TEXT NOT NULL,
                confirmed_fields_json TEXT NOT NULL,
                fields_changed_json TEXT NOT NULL,
                was_corrected INTEGER NOT NULL,
                supplier_code TEXT,
                supplier_name TEXT,
                prompt_tag TEXT,
                document_type TEXT
            );
            """
        )

        _migration_007_simplify_hitl_review_confirmations(self.conn.cursor())

        table_names = {
            row["name"]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(review_confirmations)").fetchall()
        }
        self.assertNotIn("review_model_snapshots", table_names)
        self.assertNotIn("review_field_labels", table_names)
        self.assertNotIn("required_fields_json", columns)
        self.assertNotIn("confirmed_fields_json", columns)


class ReviewConfirmationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute(
            """
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                uploaded_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO invoices(original_filename, stored_filename, file_path, mime_type, uploaded_at, updated_at)
            VALUES ('invoice.pdf', 'invoice.pdf', '/tmp/invoice.pdf', 'application/pdf', '2026-05-10T00:00:00Z', '2026-05-10T00:00:00Z')
            """
        )
        _migration_006_add_review_labels(self.conn.cursor())

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def test_record_review_confirmation_skips_unchanged_data(self) -> None:
        confirmation_id = record_review_confirmation(
            self.conn.cursor(),
            invoice={"id": 1},
            model_output={"invoice_number": "INV-1"},
            confirmed_output={"invoice_number": "INV-1"},
            source_status="recognized",
        )

        self.assertIsNone(confirmation_id)

    def test_record_review_confirmation_inserts_changed_invoice_json(self) -> None:
        confirmed = {
            "vendor_code": "1000",
            "vendor_name": "ACME",
            "PO_number": "",
            "invoice_number": "INV-2",
            "invoice_date": "05/01/2026",
            "total_amount": "182.00",
            HITL_MODEL_OUTPUT_KEY: {"invoice_number": "INV-1"},
        }

        confirmation_id = record_review_confirmation(
            self.conn.cursor(),
            invoice={"id": 1, "vendor_code": "1000", "vendor_name": "ACME"},
            model_output={
                "vendor_code": "1000",
                "vendor_name": "ACME",
                "PO_number": "",
                "invoice_number": "INV-1",
                "invoice_date": "05/01/2026",
                "total_amount": "182",
            },
            confirmed_output=confirmed,
            source_status="recognized",
        )

        row = self.conn.execute("SELECT * FROM review_confirmations WHERE id = ?", (confirmation_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row["fields_changed_json"]), ["invoice_number"])
        self.assertNotIn(HITL_MODEL_OUTPUT_KEY, json.loads(row["user_confirmed_json"]))


if __name__ == "__main__":
    unittest.main()
