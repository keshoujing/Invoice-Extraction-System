from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import app.config as config
from app.config import (
    hitl_review_enabled,
    llm_timeout_seconds,
    supplier_preview_retry_attempts,
    supplier_preview_retry_delay_seconds,
    supplier_preview_worker_count,
)


class ConfigTest(unittest.TestCase):
    def test_model_id_defaults_to_flash_lite(self) -> None:
        self.assertEqual(getattr(config, "MODEL_ID", None), "gemini-3.1-flash-lite")

    def test_hitl_review_enabled_defaults_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(hitl_review_enabled())

    def test_hitl_review_enabled_accepts_truthy_values(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"HITL_REVIEW_ENABLED": value}, clear=True):
                    self.assertTrue(hitl_review_enabled())

    def test_hitl_review_enabled_rejects_falsey_values(self) -> None:
        for value in ("", "0", "false", "no", "off"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"HITL_REVIEW_ENABLED": value}, clear=True):
                    self.assertFalse(hitl_review_enabled())

    def test_llm_timeout_seconds_defaults_and_clamps(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 60.0)
        with patch.dict(os.environ, {"GEMINI_TIMEOUT_SECONDS": "12.5"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 12.5)
        with patch.dict(os.environ, {"GEMINI_TIMEOUT_SECONDS": "1"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 5.0)
        with patch.dict(os.environ, {"GEMINI_TIMEOUT_SECONDS": "9999"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 600.0)

    def test_supplier_preview_controls_default_and_clamp(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(supplier_preview_worker_count(), 2)
            self.assertEqual(supplier_preview_retry_attempts(), 5)
            self.assertEqual(supplier_preview_retry_delay_seconds(), 1.0)
        with patch.dict(
            os.environ,
            {
                "SUPPLIER_PREVIEW_WORKERS": "99",
                "SUPPLIER_PREVIEW_RETRY_ATTEMPTS": "0",
                "SUPPLIER_PREVIEW_RETRY_DELAY_SECONDS": "99",
            },
            clear=True,
        ):
            self.assertEqual(supplier_preview_worker_count(), 5)
            self.assertEqual(supplier_preview_retry_attempts(), 1)
            self.assertEqual(supplier_preview_retry_delay_seconds(), 30.0)


if __name__ == "__main__":
    unittest.main()
