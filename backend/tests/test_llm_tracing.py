from __future__ import annotations

import sys
import types
import unittest
from typing import Any
from unittest.mock import patch

from app.llm.base import TextPart, Usage
from app.llm.tracing import trace_llm_call


class LangSmithTracingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._captured: dict[str, Any] = {}
        module = types.ModuleType("langsmith")

        def traceable(**kwargs: Any) -> Any:
            self._captured["traceable_kwargs"] = kwargs

            def decorate(func: Any) -> Any:
                def wrapped() -> Any:
                    result = func()
                    self._captured["outputs"] = kwargs["process_outputs"](result)
                    self._captured["inputs"] = kwargs["process_inputs"]({})
                    return result

                return wrapped

            return decorate

        module.traceable = traceable
        self._old_langsmith = sys.modules.get("langsmith")
        sys.modules["langsmith"] = module

    def tearDown(self) -> None:
        if self._old_langsmith is None:
            sys.modules.pop("langsmith", None)
        else:
            sys.modules["langsmith"] = self._old_langsmith

    def test_trace_outputs_include_cost_and_raw_response_metadata(self) -> None:
        raw_response = types.SimpleNamespace(
            usage_metadata=types.SimpleNamespace(
                prompt_token_count=1000,
                candidates_token_count=2000,
                total_token_count=3000,
                cached_content_token_count=700,
                thoughts_token_count=50,
            ),
            model_version="gemini-test-version",
            prompt_feedback={"block_reason": None},
            candidates=[
                types.SimpleNamespace(
                    finish_reason="STOP",
                    safety_ratings=[{"category": "safe"}],
                    content={"parts": [b"do-not-log-raw-bytes"]},
                )
            ],
        )

        with patch.dict("os.environ", {"LANGSMITH_TRACING": "true"}, clear=False):
            trace_llm_call(
                provider="gemini",
                model="gemini-2.5-flash",
                stage="invoice_extract",
                metadata={"supplier_code": "S-1"},
                system="system prompt",
                contents=[TextPart("hello")],
                func=lambda: ("{}", None, Usage(1000, 2000, 3000), raw_response),
            )

        outputs = self._captured["outputs"]
        self.assertEqual(outputs["usage_metadata"]["input_tokens"], 1000)
        self.assertEqual(outputs["usage_metadata"]["raw"]["cached_content_token_count"], 700)
        self.assertEqual(outputs["usage_metadata"]["raw"]["thoughts_token_count"], 50)
        self.assertEqual(outputs["cost_metadata"]["cost_source"], "pricing_table")
        self.assertEqual(outputs["cost_metadata"]["cost_usd"], 0.0053)
        self.assertEqual(outputs["response_metadata"]["model_version"], "gemini-test-version")
        self.assertEqual(outputs["response_metadata"]["candidates"][0]["finish_reason"], "STOP")
        self.assertNotIn("content", outputs["response_metadata"]["candidates"][0])

    def test_trace_outputs_prefer_provider_reported_cost(self) -> None:
        raw_response = types.SimpleNamespace(
            usage=types.SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            _hidden_params={"response_cost": 0.0123},
        )

        with patch.dict("os.environ", {"LANGSMITH_TRACING": "true"}, clear=False):
            trace_llm_call(
                provider="litellm",
                model="unknown-model",
                stage="supplier_preview",
                metadata={},
                system="",
                contents=[TextPart("hello")],
                func=lambda: ("{}", None, Usage(100, 50, 150), raw_response),
            )

        cost = self._captured["outputs"]["cost_metadata"]
        self.assertEqual(cost["cost_source"], "provider")
        self.assertEqual(cost["provider_reported_cost_usd"], 0.0123)
        self.assertEqual(cost["cost_usd"], 0.0123)


if __name__ == "__main__":
    unittest.main()
