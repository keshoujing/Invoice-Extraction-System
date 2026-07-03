from __future__ import annotations

import sys
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import BaseModel, ConfigDict

from app.llm.base import BytesPart, LLMRateLimitError, LLMValidationError, TextPart


class _Echo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor_name: str = ""


def _silence_telemetry() -> Any:
    return patch.multiple(
        "app.llm.telemetry",
        record_llm_call=lambda *args, **kwargs: None,
        record_llm_failure=lambda *args, **kwargs: None,
    )


def _install_fake_litellm(*, completion: MagicMock) -> types.ModuleType:
    module = types.ModuleType("litellm")
    module.completion = completion
    exceptions = types.ModuleType("litellm.exceptions")

    class _Err(Exception):
        pass

    exceptions.RateLimitError = type("RateLimitError", (_Err,), {})
    exceptions.Timeout = type("Timeout", (_Err,), {})
    exceptions.APIError = type("APIError", (_Err,), {})
    exceptions.APIConnectionError = type("APIConnectionError", (_Err,), {})
    exceptions.AuthenticationError = type("AuthenticationError", (_Err,), {})
    exceptions.BadRequestError = type("BadRequestError", (_Err,), {})

    module.exceptions = exceptions
    module.RateLimitError = exceptions.RateLimitError
    sys.modules["litellm"] = module
    sys.modules["litellm.exceptions"] = exceptions
    return module


def _build_response(*, text: str, prompt_tokens: int = 10, completion_tokens: int = 5, cost: float | None = None) -> Any:
    message = types.SimpleNamespace(content=text)
    choice = types.SimpleNamespace(message=message)
    response = types.SimpleNamespace(
        choices=[choice],
        usage=types.SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )
    if cost is not None:
        response._hidden_params = {"response_cost": cost}
    return response


class LiteLLMClientCallTest(unittest.TestCase):
    def setUp(self) -> None:
        self._telemetry_patch = _silence_telemetry()
        self._telemetry_patch.start()

    def tearDown(self) -> None:
        self._telemetry_patch.stop()

    def test_image_bytes_become_data_url(self) -> None:
        completion = MagicMock(return_value=_build_response(text='{"vendor_name":"ACME"}'))
        _install_fake_litellm(completion=completion)
        from app.llm.litellm_client import LiteLLMClient

        client = LiteLLMClient("gpt-4o")
        client._call(
            system="sys",
            contents=[TextPart("look"), BytesPart(b"\xff\xd8\xff", "image/jpeg")],
            schema=_Echo,
            temperature=0.0,
            thinking_budget=None,
        )
        kwargs = completion.call_args.kwargs
        messages = kwargs["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "sys"})
        user_parts = messages[1]["content"]
        self.assertEqual(user_parts[0], {"type": "text", "text": "look"})
        self.assertEqual(user_parts[1]["type"], "image_url")
        self.assertTrue(user_parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertIs(kwargs["response_format"], _Echo)

    def test_pdf_bytes_raise_clear_error(self) -> None:
        completion = MagicMock()
        _install_fake_litellm(completion=completion)
        from app.llm.base import LLMError
        from app.llm.litellm_client import LiteLLMClient

        client = LiteLLMClient("gpt-4o")
        with self.assertRaises(LLMError):
            client._call(
                system="",
                contents=[BytesPart(b"%PDF-", "application/pdf")],
                schema=None,
                temperature=0.0,
                thinking_budget=None,
            )

    def test_rate_limit_maps_to_llm_rate_limit_error(self) -> None:
        completion = MagicMock()
        module = _install_fake_litellm(completion=completion)
        completion.side_effect = module.exceptions.RateLimitError("limit")
        from app.llm.litellm_client import LiteLLMClient

        client = LiteLLMClient("gpt-4o")
        with self.assertRaises(LLMRateLimitError):
            client._call(
                system="",
                contents=[TextPart("x")],
                schema=None,
                temperature=0.0,
                thinking_budget=None,
            )

    def test_schema_failure_raises_validation_error(self) -> None:
        completion = MagicMock(return_value=_build_response(text='{"vendor_name": 12345}'))
        _install_fake_litellm(completion=completion)
        from app.llm.litellm_client import LiteLLMClient

        client = LiteLLMClient("gpt-4o")
        StrictEcho = type(
            "StrictEcho",
            (BaseModel,),
            {
                "__annotations__": {"vendor_name": str},
                "model_config": ConfigDict(extra="forbid"),
            },
        )
        with self.assertRaises(LLMValidationError):
            client._call(
                system="",
                contents=[TextPart("x")],
                schema=StrictEcho,
                temperature=0.0,
                thinking_budget=None,
            )

    def test_compute_cost_prefers_response_cost_when_present(self) -> None:
        completion = MagicMock(return_value=_build_response(text='{"vendor_name":"x"}', cost=0.0123))
        _install_fake_litellm(completion=completion)
        from app.llm.litellm_client import LiteLLMClient

        client = LiteLLMClient("some-model-without-pricing")
        response = client.generate(
            system="",
            contents=[TextPart("x")],
            schema=_Echo,
        )
        self.assertEqual(response.cost_usd, 0.0123)


if __name__ == "__main__":
    unittest.main()
