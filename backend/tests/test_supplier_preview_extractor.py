from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.llm.base import LLMError, LLMRateLimitError, LLMResponse, LLMTimeoutError, Usage
from app.services.supplier_preview_extractor import SupplierPreviewError, extract_supplier_preview, set_default_client


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        parsed = kwargs["schema"](
            document_type="invoice",
            document_is_invoice=True,
            vendor_name_candidates=["GLOBEX MINERALS INC."],
            evidence="GLOBEX MINERALS INC.",
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


class FakeSupplierMatcher:
    def top_matches(self, query: str, limit: int):
        return [
            SimpleNamespace(
                code="10001234",
                name="GLOBEX MINERALS INC.",
                confidence=0.99,
                method="exact",
            )
        ]


class SupplierPreviewExtractorTests(unittest.TestCase):
    def test_supplier_preview_uses_structured_schema_for_candidate_response(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "invoice.png"
            image_path.write_bytes(b"not-a-real-image-but-client-is-faked")
            set_default_client(FakeClient())
            try:
                result = extract_supplier_preview(image_path, FakeSupplierMatcher())
            finally:
                set_default_client(None)

        self.assertEqual(result["vendor_code"], "10001234")
        self.assertEqual(result["document_is_invoice"], "True")
        self.assertEqual(result["document_type"], "invoice")

    def test_supplier_preview_retries_transient_llm_failure(self) -> None:
        class FlakyClient(FakeClient):
            def generate(self, **kwargs):
                if self.calls == 0:
                    self.calls += 1
                    raise LLMTimeoutError("Gemini request exceeded 60 seconds without a response")
                return super().generate(**kwargs)

        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "invoice.png"
            image_path.write_bytes(b"not-a-real-image-but-client-is-faked")
            client = FlakyClient()
            set_default_client(client)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "SUPPLIER_PREVIEW_RETRY_ATTEMPTS": "2",
                        "SUPPLIER_PREVIEW_RETRY_DELAY_SECONDS": "0",
                    },
                ):
                    result = extract_supplier_preview(image_path, FakeSupplierMatcher())
            finally:
                set_default_client(None)

        self.assertEqual(result["vendor_code"], "10001234")
        self.assertEqual(client.calls, 2)

    def test_supplier_preview_retries_resource_exhausted_then_succeeds(self) -> None:
        class RateLimitedClient(FakeClient):
            def generate(self, **kwargs):
                if self.calls < 2:
                    self.calls += 1
                    raise LLMRateLimitError("Gemini rate limit 429: RESOURCE_EXHAUSTED")
                return super().generate(**kwargs)

        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "invoice.png"
            image_path.write_bytes(b"not-a-real-image-but-client-is-faked")
            client = RateLimitedClient()
            set_default_client(client)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "SUPPLIER_PREVIEW_RETRY_ATTEMPTS": "5",
                        "SUPPLIER_PREVIEW_RETRY_DELAY_SECONDS": "0",
                    },
                ):
                    result = extract_supplier_preview(image_path, FakeSupplierMatcher())
            finally:
                set_default_client(None)

        self.assertEqual(result["vendor_code"], "10001234")
        self.assertEqual(client.calls, 3)

    def test_supplier_preview_resource_exhausted_exhausts_retries_for_manual_review(self) -> None:
        class AlwaysRateLimitedClient(FakeClient):
            def generate(self, **kwargs):
                self.calls += 1
                raise LLMRateLimitError("Gemini rate limit 429: RESOURCE_EXHAUSTED")

        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "invoice.png"
            image_path.write_bytes(b"not-a-real-image-but-client-is-faked")
            client = AlwaysRateLimitedClient()
            set_default_client(client)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "SUPPLIER_PREVIEW_RETRY_ATTEMPTS": "5",
                        "SUPPLIER_PREVIEW_RETRY_DELAY_SECONDS": "0",
                    },
                ):
                    with self.assertRaises(SupplierPreviewError):
                        extract_supplier_preview(image_path, FakeSupplierMatcher())
            finally:
                set_default_client(None)

        self.assertEqual(client.calls, 5)

    def test_supplier_preview_reports_retry_progress_via_callback(self) -> None:
        class FlakyClient(FakeClient):
            def generate(self, **kwargs):
                if self.calls < 2:
                    self.calls += 1
                    raise LLMRateLimitError("Gemini rate limit 429: RESOURCE_EXHAUSTED")
                return super().generate(**kwargs)

        progress: list[tuple[int, int]] = []
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "invoice.png"
            image_path.write_bytes(b"not-a-real-image-but-client-is-faked")
            set_default_client(FlakyClient())
            try:
                with patch.dict(
                    os.environ,
                    {
                        "SUPPLIER_PREVIEW_RETRY_ATTEMPTS": "5",
                        "SUPPLIER_PREVIEW_RETRY_DELAY_SECONDS": "0",
                    },
                ):
                    extract_supplier_preview(
                        image_path,
                        FakeSupplierMatcher(),
                        on_retry=lambda attempt, max_attempts: progress.append((attempt, max_attempts)),
                    )
            finally:
                set_default_client(None)

        self.assertEqual(progress, [(1, 5), (2, 5)])

    def test_supplier_preview_does_not_retry_non_transient_llm_failure(self) -> None:
        class AuthFailureClient(FakeClient):
            def generate(self, **kwargs):
                self.calls += 1
                raise LLMError("missing credentials")

        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "invoice.png"
            image_path.write_bytes(b"not-a-real-image-but-client-is-faked")
            client = AuthFailureClient()
            set_default_client(client)
            try:
                with patch.dict(os.environ, {"SUPPLIER_PREVIEW_RETRY_ATTEMPTS": "3"}):
                    with self.assertRaises(SupplierPreviewError):
                        extract_supplier_preview(image_path, FakeSupplierMatcher())
            finally:
                set_default_client(None)

        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
