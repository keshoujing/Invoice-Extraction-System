from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from app.database import init_db
from app.main import app
from app.services.invoice_extractor import default_field_configs


OLD_TS = "2026-05-10T10:00:00+00:00"
LOCAL_TS = "2026-05-11T10:00:00+00:00"
NEW_TS = "2026-05-12T10:00:00+00:00"


class PromptRulesImportExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.patch_db = patch.object(database, "DB_PATH", self.db_path)
        self.patch_db.start()
        init_db()
        from app.main import _ensure_default_scheme, supplier_matcher

        _ensure_default_scheme()
        supplier_matcher.reload()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patch_db.stop()
        self.tmpdir.cleanup()

    def _seed_custom_config(self) -> None:
        fields_json = json.dumps(default_field_configs(), ensure_ascii=False)
        with database.db_cursor() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO suppliers(code, name, created_at, updated_at)
                VALUES ('1000', 'ACME MATERIALS CO.,LTD.', ?, ?),
                       ('1010', 'JUSHI GROUP HK CO., LTD.', ?, ?)
                """,
                (LOCAL_TS, LOCAL_TS, LOCAL_TS, LOCAL_TS),
            )
            cur.execute(
                """
                INSERT INTO schemes(
                    name, prompt_body, fields_json, export_settings_json,
                    is_default, created_at, updated_at
                )
                VALUES (?, ?, ?, '', 0, ?, ?)
                """,
                ("Chem", "local prompt", fields_json, LOCAL_TS, LOCAL_TS),
            )
            cur.execute(
                """
                INSERT INTO supplier_scheme_map(vendor_code, scheme_name, updated_at)
                VALUES (?, ?, ?)
                """,
                ("1000", "Chem", LOCAL_TS),
            )
            cur.execute(
                """
                INSERT INTO supplier_auto_archive_checks(
                    vendor_code, field_key, enabled, baseline_value, tolerance_percent, updated_at
                )
                VALUES (?, ?, 1, ?, ?, ?)
                """,
                ("1000", "total_amount", "1000", "1", LOCAL_TS),
            )

    def _legacy_payload(self, *, timestamp: str, tag_prompt: str = "import prompt") -> dict:
        return {
            "schema": "invoice-archive.prompt-rules",
            "version": 3,
            "exported_at": timestamp,
            "tags": [
                {
                    "tag": "Chem",
                    "prompt_body": tag_prompt,
                    "fields": default_field_configs(),
                    "export_settings": {"custom": False, "columns": []},
                    "is_default": False,
                    "updated_at": timestamp,
                }
            ],
            "supplier_tag_map": [
                {
                    "vendor_code": "1000",
                    "tag": "Chem",
                    "vendor_name": "ACME MATERIALS CO.,LTD.",
                    "updated_at": timestamp,
                }
            ],
            "special_document_rules": [
                {
                    "vendor_code": "1010",
                    "vendor_name": "JUSHI GROUP HK CO., LTD.",
                    "prompt_body": "legacy special",
                    "fields": default_field_configs(),
                    "is_active": True,
                    "updated_at": timestamp,
                }
            ],
        }

    def test_export_uses_schemes_schema_with_updated_at_for_config_items(self) -> None:
        self._seed_custom_config()
        with database.db_cursor() as cur:
            cur.execute(
                """
                UPDATE schemes
                SET preview_prompt_body = ?, preview_prompt_enabled = 1
                WHERE name = 'Chem'
                """,
                ("Match ACME MATERIALS invoices by letterhead.",),
            )

        response = self.client.get("/api/prompt-rules/export")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        scheme = next(item for item in data["schemes"] if item["name"] == "Chem")
        mapping = next(item for item in data["supplier_scheme_map"] if item["vendor_code"] == "1000")
        supplier = next(item for item in data["suppliers"] if item["code"] == "1000")
        auto_check = next(item for item in data["auto_archive_checks"] if item["vendor_code"] == "1000")
        self.assertEqual(scheme["updated_at"], LOCAL_TS)
        self.assertEqual(scheme["preview_prompt_body"], "Match ACME MATERIALS invoices by letterhead.")
        self.assertTrue(scheme["preview_prompt_enabled"])
        self.assertEqual(mapping["updated_at"], LOCAL_TS)
        self.assertEqual(supplier["name"], "ACME MATERIALS CO.,LTD.")
        self.assertEqual(auto_check["field_key"], "total_amount")
        self.assertEqual(auto_check["baseline_value"], "1000")
        self.assertEqual(auto_check["updated_at"], LOCAL_TS)
        self.assertEqual(data["tags"], [])
        self.assertEqual(data["supplier_tag_map"], [])
        self.assertEqual(data["special_document_rules"], [])

    def test_import_config_includes_suppliers_and_auto_archive_checks(self) -> None:
        payload = {
            "schema": "invoice-archive.prompt-rules",
            "version": 4,
            "exported_at": NEW_TS,
            "suppliers": [
                {"code": "9000", "name": "NEW SUPPLIER", "updated_at": NEW_TS}
            ],
            "schemes": [
                {
                    "name": "Amounts",
                    "preview_prompt_body": "Match NEW SUPPLIER invoices.",
                    "preview_prompt_enabled": True,
                    "prompt_body": "amount prompt",
                    "fields": default_field_configs(),
                    "export_settings": {"custom": False, "columns": []},
                    "is_default": False,
                    "updated_at": NEW_TS,
                }
            ],
            "supplier_scheme_map": [
                {"vendor_code": "9000", "scheme_name": "Amounts", "updated_at": NEW_TS}
            ],
            "auto_archive_checks": [
                {
                    "vendor_code": "9000",
                    "field_key": "total_amount",
                    "baseline_value": "2500",
                    "tolerance_percent": "0.5",
                    "enabled": True,
                    "updated_at": NEW_TS,
                }
            ],
            "tags": [],
            "supplier_tag_map": [],
            "special_document_rules": [],
        }

        response = self.client.post("/api/prompt-rules/import", json={"payload": payload})

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["suppliers_created"], 1)
        self.assertEqual(result["supplier_mappings_imported"], 1)
        self.assertEqual(result["auto_archive_checks_imported"], 1)
        with database.db_cursor() as cur:
            supplier = cur.execute("SELECT name FROM suppliers WHERE code = '9000'").fetchone()
            scheme = cur.execute(
                """
                SELECT preview_prompt_body, preview_prompt_enabled
                FROM schemes
                WHERE name = 'Amounts'
                """
            ).fetchone()
            mapping = cur.execute("SELECT scheme_name FROM supplier_scheme_map WHERE vendor_code = '9000'").fetchone()
            check = cur.execute(
                "SELECT field_key, baseline_value, tolerance_percent FROM supplier_auto_archive_checks WHERE vendor_code = '9000'"
            ).fetchone()
        self.assertEqual(supplier["name"], "NEW SUPPLIER")
        self.assertEqual(scheme["preview_prompt_body"], "Match NEW SUPPLIER invoices.")
        self.assertEqual(scheme["preview_prompt_enabled"], 1)
        self.assertEqual(mapping["scheme_name"], "Amounts")
        self.assertEqual(check["field_key"], "total_amount")
        self.assertEqual(check["baseline_value"], "2500")
        self.assertEqual(check["tolerance_percent"], "0.5")

    def test_import_legacy_tags_payload_converts_to_schemes(self) -> None:
        self._seed_custom_config()
        payload = self._legacy_payload(timestamp=NEW_TS)
        payload["tags"][0]["tag"] = "legacy_tag"
        payload["supplier_tag_map"] = []
        payload["special_document_rules"] = []

        response = self.client.post("/api/prompt-rules/import", json={"payload": payload})

        self.assertEqual(response.status_code, 200, response.text)
        schemes = self.client.get("/api/schemes").json()
        self.assertIn("legacy_tag", [item["name"] for item in schemes])

    def test_import_legacy_special_rules_converts_to_scheme_and_mapping(self) -> None:
        self._seed_custom_config()
        payload = self._legacy_payload(timestamp=NEW_TS)
        payload["tags"] = []
        payload["supplier_tag_map"] = []

        response = self.client.post("/api/prompt-rules/import", json={"payload": payload})

        self.assertEqual(response.status_code, 200, response.text)
        with database.db_cursor() as cur:
            scheme = cur.execute(
                "SELECT prompt_body FROM schemes WHERE name = ?",
                ("JUSHI GROUP HK CO., LTD.",),
            ).fetchone()
            mapping = cur.execute(
                "SELECT scheme_name FROM supplier_scheme_map WHERE vendor_code = '1010'",
            ).fetchone()
        self.assertEqual(scheme["prompt_body"], "legacy special")
        self.assertEqual(mapping["scheme_name"], "JUSHI GROUP HK CO., LTD.")

    def test_import_skips_stale_config_by_default(self) -> None:
        self._seed_custom_config()

        response = self.client.post("/api/prompt-rules/import", json={"payload": self._legacy_payload(timestamp=OLD_TS)})

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["stale_conflicts_skipped"], 2)
        self.assertEqual({item["kind"] for item in result["stale_conflicts"]}, {"scheme", "supplier_scheme_mapping"})
        with database.db_cursor() as cur:
            scheme = cur.execute("SELECT prompt_body FROM schemes WHERE name = 'Chem'").fetchone()
            mapping = cur.execute("SELECT scheme_name FROM supplier_scheme_map WHERE vendor_code = '1000'").fetchone()
        self.assertEqual(scheme["prompt_body"], "local prompt")
        self.assertEqual(mapping["scheme_name"], "Chem")

    def test_import_override_updates_stale_config(self) -> None:
        self._seed_custom_config()

        response = self.client.post(
            "/api/prompt-rules/import",
            json={"payload": self._legacy_payload(timestamp=OLD_TS), "override_stale": True},
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["stale_conflicts_skipped"], 0)
        self.assertEqual(len(result["stale_conflicts"]), 2)
        with database.db_cursor() as cur:
            scheme = cur.execute("SELECT prompt_body FROM schemes WHERE name = 'Chem'").fetchone()
        self.assertEqual(scheme["prompt_body"], "import prompt")

    def test_import_does_not_delete_local_rows_absent_from_snapshot(self) -> None:
        self._seed_custom_config()
        payload = self._legacy_payload(timestamp=NEW_TS)
        payload["tags"] = []
        payload["supplier_tag_map"] = []
        payload["special_document_rules"] = []

        response = self.client.post("/api/prompt-rules/import", json={"payload": payload})

        self.assertEqual(response.status_code, 200, response.text)
        with database.db_cursor() as cur:
            scheme_count = cur.execute("SELECT COUNT(*) AS count FROM schemes WHERE name = 'Chem'").fetchone()["count"]
            map_count = cur.execute(
                "SELECT COUNT(*) AS count FROM supplier_scheme_map WHERE vendor_code = '1000'"
            ).fetchone()["count"]
        self.assertEqual(scheme_count, 1)
        self.assertEqual(map_count, 1)

    def test_enabled_scheme_preview_prompt_feeds_supplier_preview_rules(self) -> None:
        self._seed_custom_config()
        with database.db_cursor() as cur:
            cur.execute(
                """
                UPDATE schemes
                SET preview_prompt_body = ?, preview_prompt_enabled = 1
                WHERE name = 'Chem'
                """,
                ("Use this only when the invoice issuer is ACME MATERIALS.",),
            )

        from app.main import _special_document_preview_rules

        rules = _special_document_preview_rules()

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["vendor_code"], "1000")
        self.assertEqual(rules[0]["vendor_name"], "ACME MATERIALS CO.,LTD.")
        self.assertEqual(rules[0]["scheme_name"], "Chem")
        self.assertEqual(rules[0]["prompt_body"], "Use this only when the invoice issuer is ACME MATERIALS.")


if __name__ == "__main__":
    unittest.main()
