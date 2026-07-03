from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerComposeFilesTest(unittest.TestCase):
    def test_required_docker_files_exist(self) -> None:
        for relative_path in ("Dockerfile", ".dockerignore", "docker-compose.yml"):
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_compose_runs_single_port_app_with_project_scoped_data_volume(self) -> None:
        compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("8000:8000", compose_text)
        self.assertIn("invoice_data:/app/data", compose_text)
        self.assertIn("volumes:\n  invoice_data:", compose_text)

    def test_demo_data_loader_is_a_profiled_optional_service(self) -> None:
        compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("\n  demo-data:", compose_text)          # real service now
        self.assertIn("- demo-data", compose_text)             # gated behind a profile
        self.assertIn("./demo-data:/demo-data:ro", compose_text)  # mounts the snapshot
        self.assertIn("cp -a /demo-data/. /app/data/", compose_text)

    def test_demo_snapshot_is_committed(self) -> None:
        snapshot_db = ROOT / "demo-data" / "invoices.sqlite3"
        self.assertTrue(snapshot_db.is_file(), "run scripts/build_demo_snapshot.py")


if __name__ == "__main__":
    unittest.main()
