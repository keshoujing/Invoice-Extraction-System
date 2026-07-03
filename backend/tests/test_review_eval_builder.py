from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.database import init_db, now_iso

from evals.refresh_from_review_labels import (
    EXTRACTION_FIELDS,
    MANIFEST_COLUMNS,
    build_manifest_rows,
    write_manifest,
)


class ReviewEvalBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "test.sqlite3"
        self.patch_db = patch.object(database, "DB_PATH", self.db_path)
        self.patch_db.start()
        init_db()

    def tearDown(self) -> None:
        self.patch_db.stop()
        self.tmpdir.cleanup()

    def _insert_invoice(
        self,
        *,
        invoice_id: int,
        corrected: bool = True,
        missing_field: str = "",
        file_name: str | None = None,
    ) -> None:
        timestamp = now_iso()
        file_path = self.root / (file_name or f"invoice-{invoice_id}.pdf")
        file_path.write_bytes(b"%PDF-1.4\n")
        user_json = {
            "vendor_code": "1000",
            "vendor_name": "ACME MATERIALS CO.,LTD.",
            "PO_number": f"PO-{invoice_id}",
            "invoice_number": f"INV-{invoice_id}",
            "invoice_date": "05/01/2026",
            "total_amount": str(float(invoice_id)),
            "expense_type": "Non-expense",
            "document_type": "invoice",
        }
        if missing_field:
            user_json.pop(missing_field)
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO invoices(
                    id, original_filename, stored_filename, file_path, mime_type,
                    status, uploaded_at, recognized_at, confirmed_at, updated_at,
                    vendor_code, vendor_name, po_number, invoice_number,
                    invoice_date, invoice_date_iso, total_amount, expense_type
                )
                VALUES (?, ?, ?, ?, 'application/pdf', 'confirmed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    file_path.name,
                    file_path.name,
                    str(file_path),
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                    "1000",
                    "ACME MATERIALS CO.,LTD.",
                    f"PO-{invoice_id}",
                    f"INV-{invoice_id}",
                    "05/01/2026",
                    "2026-05-01",
                    float(invoice_id),
                    "Non-expense",
                ),
            )
            cur.execute(
                """
                INSERT INTO review_confirmations(
                    invoice_id, confirmed_at, source_status, model_output_json,
                    user_confirmed_json, fields_changed_json, was_corrected,
                    supplier_code, supplier_name, prompt_tag, document_type
                )
                VALUES (?, ?, 'recognized', '{}', ?, ?, ?, '1000', 'ACME MATERIALS CO.,LTD.', 'default', 'invoice')
                """,
                (
                    invoice_id,
                    timestamp,
                    json.dumps(user_json, ensure_ascii=False),
                    json.dumps(["invoice_number"] if corrected else []),
                    1 if corrected else 0,
                ),
            )

    def test_build_manifest_rows_excludes_deleted_or_orphaned_invoices(self) -> None:
        self._insert_invoice(invoice_id=1)
        self._insert_invoice(invoice_id=2)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM invoices WHERE id = 2")
            conn.commit()
        finally:
            conn.close()

        rows = build_manifest_rows(db_path=self.db_path, limit=10)

        self.assertEqual([row["document_no"] for row in rows], ["review-1"])

    def test_build_manifest_rows_requires_all_extraction_fields(self) -> None:
        self._insert_invoice(invoice_id=1)
        self._insert_invoice(invoice_id=2, missing_field="total_amount")

        rows = build_manifest_rows(db_path=self.db_path, limit=10)

        self.assertEqual([row["document_no"] for row in rows], ["review-1"])
        self.assertEqual(set(EXTRACTION_FIELDS), {"PO_number", "invoice_number", "invoice_date", "total_amount"})

    def test_limit_only_uses_corrected_rows_without_unchanged_fillers(self) -> None:
        self._insert_invoice(invoice_id=1, corrected=True)
        self._insert_invoice(invoice_id=2, corrected=False)
        self._insert_invoice(invoice_id=3, corrected=True)
        self._insert_invoice(invoice_id=4, corrected=False)

        rows = build_manifest_rows(db_path=self.db_path, limit=10)

        self.assertEqual([row["document_no"] for row in rows], ["review-3", "review-1"])

    def test_write_manifest_matches_existing_manifest_columns(self) -> None:
        self._insert_invoice(invoice_id=1)
        rows = build_manifest_rows(db_path=self.db_path, limit=10)
        output = self.root / "review_golden_mini.tsv"

        write_manifest(rows, output)

        with output.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            self.assertEqual(reader.fieldnames, MANIFEST_COLUMNS)
            loaded = list(reader)
        self.assertEqual(loaded[0]["document_no"], "review-1")
        self.assertEqual(loaded[0]["po_number"], "PO-1")


if __name__ == "__main__":
    unittest.main()
