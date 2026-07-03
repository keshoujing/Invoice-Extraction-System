from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database


class Migration008Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self._patch = patch.object(database, "DB_PATH", self.db_path)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.tmpdir.cleanup()

    def _table_columns(self, table: str) -> set[str]:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        finally:
            conn.close()
        return {row[1] for row in rows}

    def _foreign_keys(self, table: str) -> list[tuple[str, str, str, str]]:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        finally:
            conn.close()
        return [(row[2], row[3], row[5], row[6]) for row in rows]

    def test_new_tables_exist(self) -> None:
        database.init_db()
        self.assertEqual(
            self._table_columns("suppliers"),
            {"code", "name", "created_at", "updated_at"},
        )
        self.assertEqual(
            self._table_columns("schemes"),
            {
                "name",
                "preview_prompt_body",
                "preview_prompt_enabled",
                "prompt_body",
                "fields_json",
                "export_settings_json",
                "is_default",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(
            self._table_columns("supplier_scheme_map"),
            {"vendor_code", "scheme_name", "updated_at"},
        )

    def test_supplier_scheme_map_foreign_keys(self) -> None:
        database.init_db()
        by_from = {fk[1]: fk for fk in self._foreign_keys("supplier_scheme_map")}
        self.assertIn("vendor_code", by_from)
        self.assertIn("scheme_name", by_from)
        self.assertEqual(by_from["vendor_code"][0], "suppliers")
        self.assertEqual(by_from["vendor_code"][3], "CASCADE")
        self.assertEqual(by_from["scheme_name"][0], "schemes")
        self.assertEqual(by_from["scheme_name"][2], "CASCADE")
        self.assertEqual(by_from["scheme_name"][3], "CASCADE")


if __name__ == "__main__":
    unittest.main()
