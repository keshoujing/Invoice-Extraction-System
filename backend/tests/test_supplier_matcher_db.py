from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.database import init_db
from app.services.supplier_matcher import SupplierMatcher


class SupplierMatcherDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self._patch = patch.object(database, "DB_PATH", self.db_path)
        self._patch.start()
        init_db()

    def tearDown(self) -> None:
        self._patch.stop()
        self.tmpdir.cleanup()

    def _insert(self, code: str, name: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO suppliers(code, name, created_at, updated_at) "
                "VALUES (?, ?, '2026-05-11', '2026-05-11')",
                (code, name),
            )
            conn.commit()
        finally:
            conn.close()

    def test_matcher_loads_from_db(self) -> None:
        self._insert("ZS001", "Zhang San Company")
        matcher = SupplierMatcher()
        results = matcher.search("Zhang San", limit=5)
        self.assertTrue(any(item.code == "ZS001" for item in results))

    def test_reload_picks_up_new_rows(self) -> None:
        matcher = SupplierMatcher()
        self.assertEqual(matcher.search("Li Si", limit=5), [])
        self._insert("LS002", "Li Si Catering")
        matcher.reload()
        results = matcher.search("Li Si", limit=5)
        self.assertTrue(any(item.code == "LS002" for item in results))

    def test_resolve_exact_normalizes_db_supplier_name(self) -> None:
        self._insert("20003187", "TK ELEVATOR\u00a0CORPORATION")
        matcher = SupplierMatcher()

        supplier = matcher.resolve_exact("20003187", "TK ELEVATOR CORPORATION")

        self.assertIsNotNone(supplier)
        self.assertEqual(supplier.code, "20003187")
        self.assertEqual(supplier.name, "TK ELEVATOR CORPORATION")


if __name__ == "__main__":
    unittest.main()
