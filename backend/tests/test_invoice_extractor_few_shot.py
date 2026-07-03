from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.llm.base import LLMResponse, Usage
from app.services.invoice_extractor import (
    build_system_prompt,
    default_field_configs,
    extract_invoice_with_config,
    set_default_client,
)


class FakeRecordingClient:
    def __init__(self) -> None:
        self.last_system: str = ""

    def generate(self, **kwargs: object) -> LLMResponse:
        self.last_system = str(kwargs["system"])
        schema = kwargs["schema"]
        # type: ignore[misc] -- schema is a pydantic model class
        parsed = schema(
            vendor_name="ACME",
            Is_Invoice="True",
            invoice_type="Invoice",
            PO_number="",
            invoice_number="INV-9",
            invoice_date="05/01/2026",
            commodity_amount=0.0,
            freight_amount=0.0,
            tax_amount=0.0,
            total_amount=182.0,
        )
        return LLMResponse(
            text="{}",
            parsed=parsed,
            usage=Usage(),
            latency_ms=0,
            cost_usd=0.0,
            model="fake",
            provider="fake",
            request_id="test",
        )


class BuildSystemPromptFewShotTest(unittest.TestCase):
    def test_no_block_when_few_shot_block_empty(self) -> None:
        prompt = build_system_prompt("body", default_field_configs())

        self.assertNotIn("Reference:", prompt)
        self.assertNotIn("Example 1:", prompt)

    def test_block_inserted_before_json_template(self) -> None:
        prompt = build_system_prompt(
            "body",
            default_field_configs(),
            few_shot_block="Reference: 3 prior invoices.\nExample 1: {\"x\": 1}",
        )

        reference_at = prompt.find("Reference:")
        template_at = prompt.find("JSON template:")
        self.assertGreater(reference_at, 0)
        self.assertGreater(template_at, reference_at, "few-shot block must precede JSON template")


class ExtractInvoiceFewShotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.invoice_path = Path(self.tmpdir.name) / "invoice.pdf"
        self.invoice_path.write_bytes(b"%PDF-1.4\n")
        self.client = FakeRecordingClient()
        set_default_client(self.client)

    def tearDown(self) -> None:
        set_default_client(None)
        self.tmpdir.cleanup()

    def test_few_shot_examples_appear_in_system_prompt(self) -> None:
        examples = [
            {"vendor_code": "1000", "invoice_number": "INV-A", "total_amount": "182.00"},
            {"vendor_code": "1000", "invoice_number": "INV-B", "total_amount": "245.00"},
            {"vendor_code": "1000", "invoice_number": "INV-C", "total_amount": "310.00"},
        ]

        extract_invoice_with_config(
            self.invoice_path,
            None,
            None,
            confirmed_vendor_name="ACME",
            confirmed_vendor_code="1000",
            few_shot_examples=examples,
        )

        self.assertIn("Reference:", self.client.last_system)
        self.assertIn("vendor_code=1000", self.client.last_system)
        self.assertIn("INV-A", self.client.last_system)
        self.assertIn("INV-C", self.client.last_system)
        self.assertIn("NOT the answer", self.client.last_system)

    def test_no_few_shot_block_when_examples_empty(self) -> None:
        extract_invoice_with_config(
            self.invoice_path,
            None,
            None,
            confirmed_vendor_name="ACME",
            confirmed_vendor_code="1000",
            few_shot_examples=[],
        )

        self.assertNotIn("Reference:", self.client.last_system)
        self.assertNotIn("Example 1:", self.client.last_system)

    def test_no_few_shot_block_when_examples_omitted(self) -> None:
        extract_invoice_with_config(
            self.invoice_path,
            None,
            None,
            confirmed_vendor_name="ACME",
            confirmed_vendor_code="1000",
        )

        self.assertNotIn("Reference:", self.client.last_system)


if __name__ == "__main__":
    unittest.main()
