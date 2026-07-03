from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

from dashboards import eval_view


class EvalViewCommandTest(unittest.TestCase):
    def test_list_runs_skips_unparseable_tsv_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            valid = runs_dir / "20260510_120000.tsv"
            invalid = runs_dir / "20260510_130000.tsv"
            header = [
                "document_no",
                "dataset",
                "vendor_code",
                "tag",
                "PO_number_expected",
                "PO_number_actual",
                "PO_number_ok",
                "invoice_number_expected",
                "invoice_number_actual",
                "invoice_number_ok",
                "invoice_date_expected",
                "invoice_date_actual",
                "invoice_date_ok",
                "total_amount_expected",
                "total_amount_actual",
                "total_amount_ok",
                "overall_ok",
                "error",
            ]
            with valid.open("w", encoding="utf-8", newline="") as fh:
                csv.writer(fh, delimiter="\t").writerow(header)
            invalid.write_text("legacy\tcolumns\nvalue\tvalue\n", encoding="utf-8")

            old_runs_dir = eval_view.RUNS_DIR
            try:
                eval_view.RUNS_DIR = runs_dir
                self.assertEqual(eval_view._list_runs(), [valid])
            finally:
                eval_view.RUNS_DIR = old_runs_dir

    def test_repo_path_accepts_relative_paths_inside_repo(self) -> None:
        path = eval_view._repo_path("evaluation/eval_manifest.tsv")

        self.assertEqual(path, eval_view.REPO_ROOT / "evaluation" / "eval_manifest.tsv")

    def test_repo_path_rejects_paths_outside_repo(self) -> None:
        with self.assertRaises(ValueError):
            eval_view._repo_path("../outside.tsv")

    def test_build_eval_command_maps_form_options_to_run_eval_args(self) -> None:
        command = eval_view._build_eval_command(
            stage="supplier",
            full=False,
            limit=20,
            only="K260699",
            dataset="Raw Material Eval Set",
            vendor="10001234",
            manifest=eval_view.REPO_ROOT / "evaluation" / "eval_manifest.tsv",
        )

        self.assertEqual(command[:4], [sys.executable, "-m", "evals.run_eval", "--stage"])
        self.assertIn("supplier", command)
        self.assertIn("--limit", command)
        self.assertIn("20", command)
        self.assertIn("--only", command)
        self.assertIn("K260699", command)
        self.assertIn("--dataset", command)
        self.assertIn("Raw Material Eval Set", command)
        self.assertIn("--vendor", command)
        self.assertIn("10001234", command)
        self.assertIn("--manifest", command)

    def test_build_eval_command_uses_full_instead_of_limit(self) -> None:
        command = eval_view._build_eval_command(
            stage="both",
            full=True,
            limit=10,
            only="",
            dataset="",
            vendor="",
            manifest=eval_view.REPO_ROOT / "evaluation" / "eval_manifest.tsv",
        )

        self.assertIn("--full", command)
        self.assertNotIn("--limit", command)

    def test_build_hitl_refresh_command_targets_refresh_module(self) -> None:
        command = eval_view._build_hitl_refresh_command(split="mini", limit=50)

        self.assertEqual(
            command,
            [
                sys.executable,
                "-m",
                "evals.refresh_from_review_labels",
                "--split",
                "mini",
                "--limit",
                "50",
            ],
        )


if __name__ == "__main__":
    unittest.main()
