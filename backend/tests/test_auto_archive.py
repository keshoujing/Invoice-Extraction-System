from __future__ import annotations

import unittest

from app.services.auto_archive import evaluate_auto_archive_checks


class AutoArchiveEvaluatorTest(unittest.TestCase):
    def test_passes_when_all_enabled_value_fields_are_within_percent(self) -> None:
        fields = [{
            "key": "total_amount",
            "type": "value",
            "auto_archive_check": {
                "enabled": True,
                "baseline_value": "1000.00",
                "tolerance_percent": "1",
            },
        }]
        result = evaluate_auto_archive_checks(fields, {"total_amount": "1009.99"})

        self.assertTrue(result.passed)
        self.assertEqual(result.failed_fields, [])

    def test_fails_when_value_is_outside_percent(self) -> None:
        fields = [{
            "key": "total_amount",
            "type": "value",
            "auto_archive_check": {
                "enabled": True,
                "baseline_value": "1000.00",
                "tolerance_percent": "1",
            },
        }]
        result = evaluate_auto_archive_checks(fields, {"total_amount": "1011.00"})

        self.assertFalse(result.passed)
        self.assertEqual(result.failed_fields, ["total_amount"])

    def test_fails_empty_or_non_numeric_value(self) -> None:
        fields = [{
            "key": "freight",
            "type": "value",
            "auto_archive_check": {
                "enabled": True,
                "baseline_value": "120",
                "tolerance_percent": "2",
            },
        }]

        self.assertFalse(evaluate_auto_archive_checks(fields, {"freight": ""}).passed)
        self.assertFalse(evaluate_auto_archive_checks(fields, {"freight": "abc"}).passed)

    def test_ignores_disabled_and_non_value_fields(self) -> None:
        fields = [
            {
                "key": "invoice_number",
                "type": "string",
                "auto_archive_check": {
                    "enabled": True,
                    "baseline_value": "1000",
                    "tolerance_percent": "1",
                },
            },
            {
                "key": "tax",
                "type": "value",
                "auto_archive_check": {"enabled": False},
            },
        ]

        result = evaluate_auto_archive_checks(fields, {"invoice_number": "INV-1"})

        self.assertFalse(result.has_checks)
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
