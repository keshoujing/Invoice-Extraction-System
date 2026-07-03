from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from app.database import init_db, now_iso
from app.main import app


class SupplierAutoArchiveConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.patch_db = patch.object(database, "DB_PATH", self.db_path)
        self.patch_db.start()
        init_db()
        from app.main import _ensure_default_scheme, supplier_matcher

        _ensure_default_scheme()
        timestamp = now_iso()
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                VALUES ('1000', 'ACME SUPPLY', ?, ?),
                       ('2000', 'BETA SUPPLY', ?, ?)
                """,
                (timestamp, timestamp, timestamp, timestamp),
            )
            cur.execute(
                """
                UPDATE schemes
                SET fields_json = ?
                WHERE name = 'default'
                """,
                (json.dumps([
                    {"key": "vendor_name", "type": "string", "group": "supplier", "examples": ""},
                    {"key": "invoice_number", "type": "string", "group": "invoice", "examples": ""},
                    {"key": "total_amount", "type": "value", "group": "amount", "examples": ""},
                    {"key": "freight_amount", "type": "value", "group": "amount", "examples": ""},
                ], ensure_ascii=False),),
            )
        supplier_matcher.reload()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patch_db.stop()
        self.tmpdir.cleanup()

    def test_supplier_checks_are_independent_for_same_scheme(self) -> None:
        response = self.client.put(
            "/api/suppliers/1000/auto-archive-checks",
            json={"checks": [{
                "field_key": "total_amount",
                "enabled": True,
                "baseline_value": "1000",
                "tolerance_percent": "1",
            }]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        first = self.client.get("/api/suppliers/1000/auto-archive-checks").json()
        second = self.client.get("/api/suppliers/2000/auto-archive-checks").json()
        self.assertEqual(first["checks"][0]["field_key"], "total_amount")
        self.assertEqual(second["checks"], [])

    def test_rejects_non_value_field(self) -> None:
        response = self.client.put(
            "/api/suppliers/1000/auto-archive-checks",
            json={"checks": [{
                "field_key": "invoice_number",
                "enabled": True,
                "baseline_value": "1000",
                "tolerance_percent": "1",
            }]},
        )

        self.assertEqual(response.status_code, 400)

    def test_backend_resolves_supplier_checks_against_effective_value_fields(self) -> None:
        from app import main as main_module

        self.client.put(
            "/api/suppliers/1000/auto-archive-checks",
            json={"checks": [{
                "field_key": "total_amount",
                "enabled": True,
                "baseline_value": "1000",
                "tolerance_percent": "1",
            }]},
        )
        _scheme_name, _prompt_body, fields = main_module._resolve_prompt_for_supplier("1000")

        auto_fields = main_module._auto_archive_fields_for_supplier("1000", fields)

        self.assertEqual(auto_fields[0]["key"], "total_amount")
        self.assertEqual(auto_fields[0]["auto_archive_check"]["baseline_value"], "1000")


if __name__ == "__main__":
    unittest.main()
