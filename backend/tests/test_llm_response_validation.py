from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.services.llm_response_validation import (
    extract_json_object_text,
    validate_supplier_candidate_response,
)
from app.services.supplier_preview_extractor import _extract_document_type, _preferred_option_by_candidate_order


class LlmResponseValidationTest(unittest.TestCase):
    def test_extract_json_object_text_accepts_markdown_fence(self) -> None:
        raw = '```json\n{"vendor_name": "AIR PRODUCTS", "total_amount": 12.5}\n```'

        self.assertEqual(
            extract_json_object_text(raw),
            '{"vendor_name": "AIR PRODUCTS", "total_amount": 12.5}',
        )

    def test_validate_supplier_candidate_response_rejects_wrong_candidate_shape(self) -> None:
        raw = """
        {
          "document_type": "invoice",
          "document_is_invoice": true,
          "document_type_reason": "header says invoice",
          "vendor_name_candidates": "AIR PRODUCTS",
          "evidence": "AIR PRODUCTS"
        }
        """

        with self.assertRaises(ValidationError):
            validate_supplier_candidate_response(raw)

    def test_supplier_preview_treats_credit_memo_as_invoice_like(self) -> None:
        doc_type, is_invoice, _ = _extract_document_type(
            {
                "document_type": "credit_memo",
                "document_is_invoice": False,
                "document_type_reason": "credit memo",
            }
        )

        self.assertEqual(doc_type, "credit_memo")
        self.assertIs(is_invoice, True)

    def test_supplier_preview_prefers_first_candidate_when_confident(self) -> None:
        selected = _preferred_option_by_candidate_order(
            ["H C Spinks Clay Company", "Lhoist North America"],
            [
                {
                    "code": "20003008",
                    "name": "LHOIST NORTH AMERICA",
                    "score": 1.0,
                    "source_candidate": "Lhoist North America",
                },
                {
                    "code": "20007211",
                    "name": "H.C. SPINKS CLAY COMPANY, INC.",
                    "score": 0.8236,
                    "source_candidate": "H C Spinks Clay Company",
                },
            ],
            0.82,
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["code"], "20007211")


if __name__ == "__main__":
    unittest.main()
