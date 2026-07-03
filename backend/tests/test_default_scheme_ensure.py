from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.database import init_db


class DefaultSchemeEnsureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self._patch = patch.object(database, "DB_PATH", self.db_path)
        self._patch.start()
        init_db()

    def tearDown(self) -> None:
        self._patch.stop()
        self.tmpdir.cleanup()

    def test_default_scheme_recreated_after_deletion(self) -> None:
        from app.main import _ensure_default_scheme

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("DELETE FROM schemes WHERE name = 'default'")
            conn.commit()
        finally:
            conn.close()

        _ensure_default_scheme()

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT name, is_default FROM schemes WHERE name = 'default'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("default", 1))


if __name__ == "__main__":
    unittest.main()
