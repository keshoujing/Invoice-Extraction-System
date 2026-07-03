from __future__ import annotations

import unittest

from app.services.exporter import _export_columns_for_tag


class ExporterColumnsTest(unittest.TestCase):
    def test_custom_columns_append_new_schema_fields(self) -> None:
        fields = [
            {
                "key": "items",
                "type": "array",
                "children": [
                    {"key": "weight", "type": "value"},
                    {"key": "unit_price", "type": "value"},
                ],
            }
        ]
        settings = {
            "custom": True,
            "columns": [
                {
                    "key": "items.weight",
                    "label": "Weight",
                    "enabled": True,
                    "source": "array_child",
                    "array_key": "items",
                    "child_key": "weight",
                    "type": "value",
                }
            ],
        }

        columns = _export_columns_for_tag(fields, settings)
        keys = [column["key"] for column in columns]

        self.assertEqual(keys[0], "items.weight")
        self.assertIn("items.unit_price", keys)
        unit_price = next(column for column in columns if column["key"] == "items.unit_price")
        self.assertEqual(unit_price["label"], "Unit Price")
        self.assertEqual(unit_price["source"], "array_child")

    def test_disabled_custom_schema_field_is_not_readded(self) -> None:
        fields = [
            {
                "key": "items",
                "type": "array",
                "children": [{"key": "unit_price", "type": "value"}],
            }
        ]
        settings = {
            "custom": True,
            "columns": [
                {
                    "key": "items.unit_price",
                    "label": "Unit Price",
                    "enabled": False,
                    "source": "array_child",
                    "array_key": "items",
                    "child_key": "unit_price",
                    "type": "value",
                }
            ],
        }

        columns = _export_columns_for_tag(fields, settings)

        self.assertNotIn("items.unit_price", [column["key"] for column in columns])


if __name__ == "__main__":
    unittest.main()
