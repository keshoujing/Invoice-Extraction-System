from __future__ import annotations

import unittest
import sys
import types
from typing import Any, ClassVar
from unittest.mock import patch

from pydantic import BaseModel

from app.llm.base import (
    BytesPart,
    LLMClient,
    LLMResponse,
    Part,
    TextPart,
    Usage,
)


class _Echo(BaseModel):
    msg: str


def _silence_telemetry() -> Any:
    return patch.multiple(
        "app.llm.telemetry",
        record_llm_call=lambda *args, **kwargs: None,
        record_llm_failure=lambda *args, **kwargs: None,
    )


class _StubClient(LLMClient):
    provider: ClassVar[str] = "stub"

    def __init__(self, model: str, *, response: tuple[str, BaseModel | None, Usage, Any], cost: float = 0.0) -> None:
        super().__init__(model)
        self._response = response
        self._cost_override = cost
        self.last_kwargs: dict[str, Any] | None = None

    def _call(
        self,
        *,
        system: str,
        contents: list[Part],
        schema: type[BaseModel] | None,
        temperature: float,
        thinking_budget: int | None,
    ) -> tuple[str, BaseModel | None, Usage, Any]:
        self.last_kwargs = {
            "system": system,
            "contents": list(contents),
            "schema": schema,
            "temperature": temperature,
            "thinking_budget": thinking_budget,
        }
        return self._response

    def _compute_cost(self, usage: Usage, raw_response: Any) -> float:
        if self._cost_override:
            return self._cost_override
        return super()._compute_cost(usage, raw_response)


class LLMClientGenerateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._telemetry_patch = _silence_telemetry()
        self._telemetry_patch.start()

    def tearDown(self) -> None:
        self._telemetry_patch.stop()

    def test_generate_passes_arguments_through_to_call(self) -> None:
        client = _StubClient(
            "stub-model",
            response=("ok", _Echo(msg="ok"), Usage(1, 2, 3), {"raw": True}),
        )
        contents: list[Part] = [TextPart("hi"), BytesPart(b"abc", "image/png")]

        response = client.generate(
            system="sys",
            contents=contents,
            schema=_Echo,
            temperature=0.2,
            thinking_budget=128,
            stage="unit_test",
            metadata={"file": "x.pdf"},
        )

        self.assertIsInstance(response, LLMResponse)
        self.assertEqual(response.text, "ok")
        self.assertIsInstance(response.parsed, _Echo)
        self.assertEqual(response.parsed.msg, "ok")
        self.assertEqual(response.usage, Usage(1, 2, 3))
        self.assertEqual(response.model, "stub-model")
        self.assertEqual(response.provider, "stub")
        self.assertGreaterEqual(response.latency_ms, 0)
        self.assertTrue(response.request_id)
        self.assertEqual(client.last_kwargs["system"], "sys")
        self.assertEqual(client.last_kwargs["contents"], contents)
        self.assertIs(client.last_kwargs["schema"], _Echo)
        self.assertEqual(client.last_kwargs["temperature"], 0.2)
        self.assertEqual(client.last_kwargs["thinking_budget"], 128)

    def test_generate_uses_static_pricing_when_subclass_does_not_override(self) -> None:
        client = _StubClient(
            "gpt-4o",
            response=("ok", None, Usage(1_000_000, 1_000_000, 2_000_000), None),
        )
        response = client.generate(system="", contents=[TextPart("hi")])

        # gpt-4o priced 2.5 in / 10 out per 1M tokens
        self.assertAlmostEqual(response.cost_usd, 12.5, places=4)

    def test_generate_respects_subclass_cost_override(self) -> None:
        client = _StubClient(
            "stub-model",
            response=("ok", None, Usage(10, 20, 30), None),
            cost=0.99,
        )
        response = client.generate(system="", contents=[TextPart("hi")])
        self.assertEqual(response.cost_usd, 0.99)

    def test_generate_skips_langsmith_when_disabled(self) -> None:
        client = _StubClient("stub-model", response=("ok", None, Usage(), None))
        with patch.dict("os.environ", {"LANGSMITH_TRACING": "false"}, clear=False):
            response = client.generate(system="", contents=[TextPart("hi")])
        self.assertEqual(response.text, "ok")

    def test_generate_tolerates_langsmith_none_output_processing(self) -> None:
        langsmith = types.ModuleType("langsmith")

        def traceable(**kwargs: Any) -> Any:
            def decorate(func: Any) -> Any:
                def wrapper() -> Any:
                    kwargs["process_outputs"](None)
                    return func()

                return wrapper

            return decorate

        langsmith.traceable = traceable
        client = _StubClient("stub-model", response=("ok", None, Usage(), None))
        with patch.dict(sys.modules, {"langsmith": langsmith}), patch.dict(
            "os.environ", {"LANGSMITH_TRACING": "true"}, clear=False
        ):
            response = client.generate(system="", contents=[TextPart("hi")])
        self.assertEqual(response.text, "ok")


if __name__ == "__main__":
    unittest.main()
