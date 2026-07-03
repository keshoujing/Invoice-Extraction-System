from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from dashboards.eval_metrics import aggregate, write_aggregate


def _write_extraction_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ("PO_number", "invoice_number", "invoice_date", "total_amount")
    header = ["document_no", "dataset", "vendor_code", "tag"]
    for f in fields:
        header.extend([f"{f}_expected", f"{f}_actual", f"{f}_ok"])
    header.extend(["overall_ok", "error"])
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(col, "") for col in header])


class EvalMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tsv = Path(self.tmpdir.name) / "run.tsv"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_aggregate_extraction_counts_overall_and_per_field(self) -> None:
        _write_extraction_tsv(
            self.tsv,
            [
                {
                    "document_no": "K1", "dataset": "MRO", "vendor_code": "V1", "tag": "default",
                    "PO_number_expected": "6000001", "PO_number_actual": "6000001", "PO_number_ok": "1",
                    "invoice_number_expected": "INV-1", "invoice_number_actual": "INV-1", "invoice_number_ok": "1",
                    "invoice_date_expected": "1/2/2026", "invoice_date_actual": "1/2/2026", "invoice_date_ok": "1",
                    "total_amount_expected": "100.00", "total_amount_actual": "100.00", "total_amount_ok": "1",
                    "overall_ok": "1", "error": "",
                },
                {
                    "document_no": "K2", "dataset": "MRO", "vendor_code": "V2", "tag": "default",
                    "PO_number_expected": "6000002", "PO_number_actual": "6000002", "PO_number_ok": "1",
                    "invoice_number_expected": "INV-2", "invoice_number_actual": "INV-2X", "invoice_number_ok": "0",
                    "invoice_date_expected": "1/3/2026", "invoice_date_actual": "1/3/2026", "invoice_date_ok": "1",
                    "total_amount_expected": "200.00", "total_amount_actual": "200.00", "total_amount_ok": "1",
                    "overall_ok": "0", "error": "",
                },
                {
                    "document_no": "K3", "dataset": "Raw", "vendor_code": "V1", "tag": "default",
                    "PO_number_expected": "", "PO_number_actual": "", "PO_number_ok": "0",
                    "invoice_number_expected": "", "invoice_number_actual": "", "invoice_number_ok": "0",
                    "invoice_date_expected": "", "invoice_date_actual": "", "invoice_date_ok": "0",
                    "total_amount_expected": "", "total_amount_actual": "", "total_amount_ok": "0",
                    "overall_ok": "0", "error": "ExtractionError: model timed out",
                },
            ],
        )

        metrics = aggregate(self.tsv)

        self.assertEqual(metrics["stage"], "extraction")
        self.assertEqual(metrics["row_count"], 3)
        self.assertAlmostEqual(metrics["overall_accuracy"], 1 / 3, places=4)
        self.assertEqual(metrics["error_count"], 1)
        self.assertAlmostEqual(metrics["error_rate"], 1 / 3, places=4)

        # PO_number: 2 of 3 correct
        self.assertEqual(metrics["fields"]["PO_number"]["correct"], 2)
        self.assertEqual(metrics["fields"]["PO_number"]["total"], 3)
        # invoice_number: 1 of 3 correct
        self.assertEqual(metrics["fields"]["invoice_number"]["correct"], 1)

        # By dataset
        ds_map = {g["name"]: g for g in metrics["by_dataset"]}
        self.assertIn("MRO", ds_map)
        self.assertIn("Raw", ds_map)
        self.assertEqual(ds_map["MRO"]["rows"], 2)
        self.assertAlmostEqual(ds_map["MRO"]["overall_accuracy"], 0.5)

        # By supplier
        sup_map = {g["name"]: g for g in metrics["by_supplier"]}
        self.assertEqual(sup_map["V1"]["rows"], 2)
        self.assertEqual(sup_map["V2"]["rows"], 1)

        # Bad cases include the failures
        self.assertEqual(len(metrics["bad_cases"]), 2)
        bad_docs = {bc["document_no"] for bc in metrics["bad_cases"]}
        self.assertEqual(bad_docs, {"K2", "K3"})

        # Error classes
        self.assertEqual(metrics["error_classes"], {"ExtractionError": 1})

    def test_aggregate_handles_empty_tsv(self) -> None:
        _write_extraction_tsv(self.tsv, [])
        metrics = aggregate(self.tsv)
        self.assertEqual(metrics["row_count"], 0)
        self.assertEqual(metrics["overall_accuracy"], 0.0)
        self.assertEqual(metrics["bad_cases"], [])

    def test_write_aggregate_creates_json(self) -> None:
        _write_extraction_tsv(
            self.tsv,
            [
                {
                    "document_no": "K1", "dataset": "MRO", "vendor_code": "V1", "tag": "default",
                    "PO_number_expected": "1", "PO_number_actual": "1", "PO_number_ok": "1",
                    "invoice_number_expected": "I", "invoice_number_actual": "I", "invoice_number_ok": "1",
                    "invoice_date_expected": "1/1/26", "invoice_date_actual": "1/1/26", "invoice_date_ok": "1",
                    "total_amount_expected": "1", "total_amount_actual": "1", "total_amount_ok": "1",
                    "overall_ok": "1", "error": "",
                }
            ],
        )

        target = write_aggregate(self.tsv)
        self.assertTrue(target.exists())
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["row_count"], 1)
        self.assertAlmostEqual(payload["overall_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
