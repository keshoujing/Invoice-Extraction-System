from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evals.run_eval import load_manifest


class RunEvalManifestTest(unittest.TestCase):
    def test_load_manifest_accepts_custom_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.tsv"
            manifest.write_text(
                "\t".join(
                    [
                        "dataset",
                        "document_no",
                        "expense_type",
                        "vendor_code",
                        "vendor_name",
                        "po_number",
                        "invoice_number",
                        "invoice_date",
                        "total_amount",
                        "file_path",
                        "expected_document_type",
                        "expected_is_invoice",
                        "expected_special_document_matched",
                    ]
                )
                + "\n"
                + "\t".join(
                    [
                        "Generated",
                        "review-1",
                        "Non-expense",
                        "1000",
                        "ACME MATERIALS CO.,LTD.",
                        "PO-1",
                        "INV-1",
                        "05/01/2026",
                        "1.00",
                        "evaluation/generated/example.pdf",
                        "invoice",
                        "True",
                        "False",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rows = load_manifest(manifest)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].document_no, "review-1")
        self.assertEqual(rows[0].expected["total_amount"], "1.00")


if __name__ == "__main__":
    unittest.main()
