from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import _migration_006_add_review_labels


def _seed_invoice(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO invoices(original_filename, stored_filename, file_path, mime_type, uploaded_at, updated_at)
        VALUES ('invoice.pdf', 'invoice.pdf', '/tmp/invoice.pdf', 'application/pdf', '2026-05-10T00:00:00Z', '2026-05-10T00:00:00Z')
        """
    )


def _insert_confirmation(
    conn: sqlite3.Connection,
    *,
    supplier_code: str,
    confirmed_at: str,
    user_confirmed: dict[str, object] | str,
    invoice_id: int = 1,
    was_corrected: int = 1,
) -> None:
    payload = (
        user_confirmed
        if isinstance(user_confirmed, str)
        else json.dumps(user_confirmed, ensure_ascii=False, sort_keys=True)
    )
    conn.execute(
        """
        INSERT INTO review_confirmations(
            invoice_id, confirmed_at, source_status, model_output_json,
            user_confirmed_json, fields_changed_json, was_corrected,
            supplier_code, supplier_name, prompt_tag, document_type
        )
        VALUES (?, ?, 'recognized', '{}', ?, '[]', ?, ?, '', '', '')
        """,
        (invoice_id, confirmed_at, payload, was_corrected, supplier_code),
    )


class FewShotFetchTest(unittest.TestCase):
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
        _seed_invoice(self.conn)
        _migration_006_add_review_labels(self.conn.cursor())

    def tearDown(self) -> None:
        self.conn.close()
        self.tmpdir.cleanup()

    def _fetch(self, vendor_code: str, **kwargs: object) -> list[dict[str, object]]:
        from app.services.few_shot import fetch_supplier_examples

        return fetch_supplier_examples(self.conn.cursor(), vendor_code, **kwargs)

    def test_returns_empty_for_empty_vendor_code(self) -> None:
        self.assertEqual(self._fetch(""), [])
        self.assertEqual(self._fetch("   "), [])

    def test_returns_empty_when_supplier_has_no_history(self) -> None:
        self.assertEqual(self._fetch("9999"), [])

    def test_returns_empty_when_history_below_min(self) -> None:
        for ts in ("2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z"):
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=ts,
                user_confirmed={"vendor_code": "1000", "invoice_number": "INV"},
            )

        self.assertEqual(self._fetch("1000"), [])

    def test_returns_three_when_history_has_exactly_three(self) -> None:
        for index, ts in enumerate(
            ("2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z", "2026-05-03T00:00:00Z")
        ):
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=ts,
                user_confirmed={
                    "vendor_code": "1000",
                    "vendor_name": "ACME",
                    "PO_number": "PO-100",
                    "invoice_number": f"INV-{index + 1}",
                    "invoice_date": "05/01/2026",
                    "total_amount": "182.00",
                },
            )

        result = self._fetch("1000")
        self.assertEqual(len(result), 3)
        invoice_numbers = [example["invoice_number"] for example in result]
        self.assertEqual(invoice_numbers, ["INV-3", "INV-2", "INV-1"])

    def test_returns_most_recent_three_when_history_has_more(self) -> None:
        for index in range(5):
            ts = f"2026-05-0{index + 1}T00:00:00Z"
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=ts,
                user_confirmed={"vendor_code": "1000", "invoice_number": f"INV-{index + 1}"},
            )

        result = self._fetch("1000")
        self.assertEqual([example["invoice_number"] for example in result], ["INV-5", "INV-4", "INV-3"])

    def test_filters_by_supplier_code(self) -> None:
        for index in range(3):
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=f"2026-05-0{index + 1}T00:00:00Z",
                user_confirmed={"vendor_code": "1000", "invoice_number": f"A-{index + 1}"},
            )
            _insert_confirmation(
                self.conn,
                supplier_code="2000",
                confirmed_at=f"2026-05-0{index + 1}T00:00:00Z",
                user_confirmed={"vendor_code": "2000", "invoice_number": f"B-{index + 1}"},
            )

        result = self._fetch("1000")
        self.assertEqual(len(result), 3)
        for example in result:
            self.assertEqual(example["vendor_code"], "1000")
            self.assertTrue(example["invoice_number"].startswith("A-"))

    def test_strips_non_core_fields(self) -> None:
        for index in range(3):
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=f"2026-05-0{index + 1}T00:00:00Z",
                user_confirmed={
                    "vendor_code": "1000",
                    "vendor_name": "ACME",
                    "PO_number": "PO-1",
                    "invoice_number": f"INV-{index + 1}",
                    "invoice_date": "05/01/2026",
                    "total_amount": "182.00",
                    "tax_amount": "10.00",
                    "supplier_stage": "ready",
                    "_hitl_model_output": {"invoice_number": "OLD"},
                    "vendor_match_confidence": 0.99,
                },
            )

        for example in self._fetch("1000"):
            self.assertEqual(
                set(example.keys()),
                {"vendor_code", "vendor_name", "PO_number", "invoice_number", "invoice_date", "total_amount"},
            )

    def test_skips_malformed_json_rows(self) -> None:
        for index, ts in enumerate(
            ("2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z", "2026-05-03T00:00:00Z")
        ):
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=ts,
                user_confirmed={"vendor_code": "1000", "invoice_number": f"INV-{index + 1}"},
            )
        _insert_confirmation(
            self.conn,
            supplier_code="1000",
            confirmed_at="2026-05-04T00:00:00Z",
            user_confirmed="not json",
        )

        result = self._fetch("1000")
        self.assertEqual(len(result), 3)
        self.assertNotIn("not json", json.dumps(result, ensure_ascii=False))

    def test_canonicalizes_legacy_field_keys(self) -> None:
        for index, ts in enumerate(
            ("2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z", "2026-05-03T00:00:00Z")
        ):
            _insert_confirmation(
                self.conn,
                supplier_code="1000",
                confirmed_at=ts,
                user_confirmed={
                    "supplier_code": "1000",
                    "supplier_name": "ACME",
                    "po_number": "PO-1",
                    "invoice_number": f"INV-{index + 1}",
                    "invoice_date": "05/01/2026",
                    "total_amount": "182.00",
                },
            )

        for example in self._fetch("1000"):
            self.assertIn("vendor_code", example)
            self.assertIn("vendor_name", example)
            self.assertIn("PO_number", example)


class FormatFewShotBlockTest(unittest.TestCase):
    def test_returns_empty_when_no_examples(self) -> None:
        from app.services.few_shot import format_few_shot_block

        self.assertEqual(format_few_shot_block([], "1000"), "")
        self.assertEqual(format_few_shot_block(None, "1000"), "")

    def test_block_contains_header_examples_and_safety_footer(self) -> None:
        from app.services.few_shot import format_few_shot_block

        examples = [
            {"vendor_code": "1000", "invoice_number": "INV-A", "total_amount": "182.00"},
            {"vendor_code": "1000", "invoice_number": "INV-B", "total_amount": "245.00"},
        ]

        block = format_few_shot_block(examples, "1000")

        self.assertIn("vendor_code=1000", block)
        self.assertIn("INV-A", block)
        self.assertIn("INV-B", block)
        self.assertIn("NOT the answer", block)
        self.assertEqual(block.count("Example "), 2)


class GetFewShotExamplesIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
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
        _seed_invoice(conn)
        _migration_006_add_review_labels(conn.cursor())
        for index in range(3):
            _insert_confirmation(
                conn,
                supplier_code="1000",
                confirmed_at=f"2026-05-0{index + 1}T00:00:00Z",
                user_confirmed={"vendor_code": "1000", "invoice_number": f"INV-{index + 1}"},
            )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_get_few_shot_examples_uses_provided_db_path(self) -> None:
        from app.services.few_shot import get_few_shot_examples

        result = get_few_shot_examples("1000", db_path=self.db_path)

        self.assertEqual(len(result), 3)
        self.assertEqual([example["invoice_number"] for example in result], ["INV-3", "INV-2", "INV-1"])


if __name__ == "__main__":
    unittest.main()
