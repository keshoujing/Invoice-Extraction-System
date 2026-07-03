from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database
from app.database import init_db


class SchemeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self._patch = patch.object(database, "DB_PATH", self.db_path)
        self._patch.start()
        init_db()
        from app.main import app, _ensure_default_scheme, supplier_matcher

        _ensure_default_scheme()
        supplier_matcher.reload()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._patch.stop()
        self.tmpdir.cleanup()

    def test_list_schemes_includes_default(self) -> None:
        response = self.client.get("/api/schemes")
        self.assertEqual(response.status_code, 200)
        self.assertIn("default", [item["name"] for item in response.json()])

    def test_create_scheme_inherits_from_default(self) -> None:
        response = self.client.post("/api/schemes", json={"name": "Restaurant Scheme", "inherit_from": "default"})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        default = next(item for item in self.client.get("/api/schemes").json() if item["name"] == "default")
        self.assertEqual(body["name"], "Restaurant Scheme")
        self.assertEqual(body["prompt_body"], default["prompt_body"])

    def test_create_duplicate_name_rejected(self) -> None:
        self.client.post("/api/schemes", json={"name": "X", "inherit_from": "default"})
        response = self.client.post("/api/schemes", json={"name": "X", "inherit_from": "default"})
        self.assertEqual(response.status_code, 409)

    def test_rename_scheme_cascades_map(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                    VALUES ('S001', 'A', '2026-05-11', '2026-05-11');
                INSERT INTO schemes(name, prompt_body, fields_json, export_settings_json,
                                    is_default, created_at, updated_at)
                    VALUES ('old_name', '', '[]', '', 0, '2026-05-11', '2026-05-11');
                INSERT INTO supplier_scheme_map(vendor_code, scheme_name, updated_at)
                    VALUES ('S001', 'old_name', '2026-05-11');
                """
            )
            conn.commit()
        finally:
            conn.close()

        response = self.client.put("/api/schemes/old_name", json={"name": "new_name"})
        self.assertEqual(response.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT scheme_name FROM supplier_scheme_map WHERE vendor_code = 'S001'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "new_name")

    def test_rename_default_rejected(self) -> None:
        response = self.client.put("/api/schemes/default", json={"name": "other"})
        self.assertEqual(response.status_code, 400)

    def test_delete_default_rejected(self) -> None:
        response = self.client.delete("/api/schemes/default")
        self.assertEqual(response.status_code, 400)

    def test_delete_scheme_cascades_map(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                    VALUES ('S002', 'B', '2026-05-11', '2026-05-11');
                INSERT INTO schemes(name, prompt_body, fields_json, export_settings_json,
                                    is_default, created_at, updated_at)
                    VALUES ('to_delete', '', '[]', '', 0, '2026-05-11', '2026-05-11');
                INSERT INTO supplier_scheme_map(vendor_code, scheme_name, updated_at)
                    VALUES ('S002', 'to_delete', '2026-05-11');
                """
            )
            conn.commit()
        finally:
            conn.close()

        response = self.client.delete("/api/schemes/to_delete")
        self.assertEqual(response.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM supplier_scheme_map WHERE vendor_code='S002'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_supplier_scheme_map_endpoint(self) -> None:
        self.client.post("/api/suppliers", json={"code": "M001", "name": "A"})
        self.client.post("/api/schemes", json={"name": "scheme_a", "inherit_from": "default"})
        response = self.client.put("/api/supplier-scheme-map/M001", json={"scheme_name": "scheme_a"})
        self.assertEqual(response.status_code, 200)

        listing = self.client.get("/api/supplier-scheme-map").json()
        self.assertEqual(listing.get("M001"), "scheme_a")

        clear = self.client.delete("/api/supplier-scheme-map/M001")
        self.assertEqual(clear.status_code, 200)
        self.assertNotIn("M001", self.client.get("/api/supplier-scheme-map").json())


if __name__ == "__main__":
    unittest.main()
