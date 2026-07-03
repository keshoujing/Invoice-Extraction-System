from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.llm.schema_builder import build_invoice_schema


class BuildInvoiceSchemaTest(unittest.TestCase):
    def test_supports_string_value_bool_array_fields(self) -> None:
        schema = build_invoice_schema(
            [
                {"key": "vendor_name", "type": "string", "examples": ""},
                {"key": "total_amount", "type": "value", "examples": ""},
                {"key": "paid", "type": "bool", "examples": ""},
                {
                    "key": "line_items",
                    "type": "array",
                    "examples": "",
                    "children": [
                        {"key": "sku", "type": "string", "examples": ""},
                        {"key": "qty", "type": "value", "examples": ""},
                    ],
                },
            ]
        )

        parsed = schema.model_validate(
            {
                "vendor_name": "AIR PRODUCTS",
                "total_amount": "$1,234.50",
                "paid": "yes",
                "line_items": [{"sku": "A-1", "qty": "2"}],
            }
        )

        dumped = parsed.model_dump()
        self.assertEqual(dumped["vendor_name"], "AIR PRODUCTS")
        self.assertEqual(dumped["total_amount"], 1234.5)
        self.assertIs(dumped["paid"], True)
        self.assertEqual(dumped["line_items"], [{"sku": "A-1", "qty": 2.0}])

    def test_skips_fixed_fields(self) -> None:
        schema = build_invoice_schema(
            [
                {"key": "vendor_name", "type": "string", "examples": ""},
                {"key": "tag_label", "type": "fixed", "value": "MRO"},
            ]
        )

        self.assertIn("vendor_name", schema.model_fields)
        self.assertNotIn("tag_label", schema.model_fields)

    def test_missing_fields_use_defaults(self) -> None:
        schema = build_invoice_schema(
            [
                {"key": "vendor_name", "type": "string"},
                {"key": "total_amount", "type": "value"},
                {"key": "paid", "type": "bool"},
                {
                    "key": "line_items",
                    "type": "array",
                    "children": [{"key": "sku", "type": "string"}],
                },
            ]
        )

        parsed = schema.model_validate({}).model_dump()
        self.assertEqual(parsed["vendor_name"], "")
        self.assertEqual(parsed["total_amount"], 0.0)
        self.assertIs(parsed["paid"], False)
        self.assertEqual(parsed["line_items"], [])

    def test_amount_handles_parens_for_negatives(self) -> None:
        schema = build_invoice_schema([{"key": "total_amount", "type": "value"}])
        parsed = schema.model_validate({"total_amount": "(2,848.40)"}).model_dump()
        self.assertEqual(parsed["total_amount"], -2848.40)

    def test_invalid_value_raises_validation_error(self) -> None:
        schema = build_invoice_schema([{"key": "total_amount", "type": "value"}])
        with self.assertRaises(ValidationError):
            schema.model_validate({"total_amount": "not a number"})

    def test_extra_keys_are_preserved(self) -> None:
        schema = build_invoice_schema([{"key": "vendor_name", "type": "string"}])
        parsed = schema.model_validate({"vendor_name": "ACME", "ad_hoc_note": "freight"})
        self.assertEqual(parsed.model_dump().get("ad_hoc_note"), "freight")


if __name__ == "__main__":
    unittest.main()
