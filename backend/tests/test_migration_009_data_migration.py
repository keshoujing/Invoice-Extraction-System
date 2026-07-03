from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database


class Migration009Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.supplier_file = Path(self.tmpdir.name) / "supplier.txt"
        self.supplier_file.write_text(
            "ZS001\tZhang San Company\n"
            "LS002\tLi Si Catering\n"
            "FAKE003\tOrphan Supplier\n",
            encoding="utf-8",
        )
        self._db_patch = patch.object(database, "DB_PATH", self.db_path)
        self._supplier_patch = patch("app.services.supplier_matcher.SUPPLIER_FILE", self.supplier_file)
        self._db_patch.start()
        self._supplier_patch.start()
        self._seed_old_state()

    def tearDown(self) -> None:
        self._db_patch.stop()
        self._supplier_patch.stop()
        self.tmpdir.cleanup()

    def _seed_old_state(self) -> None:
        original = list(database.MIGRATIONS)
        try:
            database.MIGRATIONS[:] = [migration for migration in original if migration[0] <= "007"]
            database.init_db()
        finally:
            database.MIGRATIONS[:] = original

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO prompt_tags(tag_name, prompt_body, fields_json, export_settings_json, "
                "is_default, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                ("default", "Default body", "[]", "", "2026-01-01", "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO prompt_tags(tag_name, prompt_body, fields_json, export_settings_json, "
                "is_default, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                ("Restaurant Scheme", "Restaurant body", "[]", "", "2026-01-02", "2026-01-02"),
            )
            conn.execute(
                "INSERT INTO supplier_tag_map(vendor_code, tag_name, updated_at) VALUES (?, ?, ?)",
                ("LS002", "Restaurant Scheme", "2026-01-02"),
            )
            conn.execute(
                "INSERT INTO special_document_rules(vendor_code, vendor_name, prompt_body, fields_json, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                ("ZS001", "Zhang San Company", "Custom body", "[]", "2026-01-03", "2026-01-03"),
            )
            conn.execute(
                "INSERT INTO special_document_rules(vendor_code, vendor_name, prompt_body, fields_json, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                ("FAKE003", "Orphan Supplier", "Disabled body", "[]", "2026-01-04", "2026-01-04"),
            )
            conn.commit()
        finally:
            conn.close()

    def test_suppliers_imported_from_file(self) -> None:
        database.init_db()
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT code, name FROM suppliers ORDER BY code").fetchall()
        finally:
            conn.close()
        self.assertEqual(
            rows,
            [("FAKE003", "Orphan Supplier"), ("LS002", "Li Si Catering"), ("ZS001", "Zhang San Company")],
        )

    def test_schemes_migrated_from_prompt_tags_and_active_special_rules(self) -> None:
        database.init_db()
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT name, prompt_body, is_default FROM schemes ORDER BY name").fetchall()
        finally:
            conn.close()
        names = {row[0] for row in rows}
        self.assertIn("default", names)
        self.assertIn("Restaurant Scheme", names)
        self.assertIn("Zhang San Company", names)
        self.assertNotIn("Orphan Supplier", names)

    def test_supplier_scheme_map_migrated(self) -> None:
        database.init_db()
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT vendor_code, scheme_name FROM supplier_scheme_map ORDER BY vendor_code"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("LS002", "Restaurant Scheme"), ("ZS001", "Zhang San Company")])

    def test_supplier_txt_renamed_after_import(self) -> None:
        database.init_db()
        self.assertFalse(self.supplier_file.exists())
        siblings = list(self.supplier_file.parent.glob("supplier.txt.imported_*"))
        self.assertEqual(len(siblings), 1)


if __name__ == "__main__":
    unittest.main()
