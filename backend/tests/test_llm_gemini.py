from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import BaseModel, ConfigDict

from app.llm.base import (
    BytesPart,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMValidationError,
    TextPart,
)


class _Echo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor_name: str = ""


def _install_fake_genai() -> tuple[types.ModuleType, types.ModuleType]:
    """Install a minimal fake ``google.genai`` so GeminiClient imports work in tests."""
    google_pkg = types.ModuleType("google")
    google_pkg.__path__ = []  # mark as package
    genai_module = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")

    class GenerateContentConfig:
        model_fields: dict[str, Any] = {
            "http_options": None,
            "system_instruction": None,
            "response_mime_type": None,
            "response_schema": None,
            "temperature": None,
            "thinking_config": None,
        }

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class ThinkingConfig:
        model_fields: dict[str, Any] = {"thinking_budget": None}

        def __init__(self, *, thinking_budget: int | None = 0) -> None:
            self.thinking_budget = thinking_budget

    class HttpOptions:
        def __init__(self, *, timeout: int | None = None) -> None:
            self.timeout = timeout

    class Part:
        @staticmethod
        def from_text(*, text: str) -> dict[str, Any]:
            return {"kind": "text", "text": text}

        @staticmethod
        def from_bytes(*, data: bytes, mime_type: str) -> dict[str, Any]:
            return {"kind": "bytes", "byte_count": len(data), "mime_type": mime_type}

    genai_types.GenerateContentConfig = GenerateContentConfig
    genai_types.ThinkingConfig = ThinkingConfig
    genai_types.HttpOptions = HttpOptions
    genai_types.Part = Part
    genai_module.types = genai_types
    google_pkg.genai = genai_module

    sys.modules.setdefault("google", google_pkg)
    sys.modules["google.genai"] = genai_module
    sys.modules["google.genai.types"] = genai_types
    return genai_module, genai_types


class GeminiClientCallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_fake_genai()
        # Import after fakes so ``from google.genai import types`` resolves.
        from app.llm.gemini import GeminiClient

        cls.GeminiClient = GeminiClient

    def _client_with_response(self, *, response: Any) -> Any:
        sdk = MagicMock()
        sdk.models.generate_content.return_value = response
        sdk.close = MagicMock()
        return self.GeminiClient("gemini-2.5-flash", client_factory=lambda: sdk)

    def test_call_with_schema_returns_parsed(self) -> None:
        echo = _Echo(vendor_name="ACME")
        fake_response = types.SimpleNamespace(
            text='{"vendor_name":"ACME"}',
            parsed=echo,
            usage_metadata=types.SimpleNamespace(
                prompt_token_count=10, candidates_token_count=5, total_token_count=15
            ),
        )
        client = self._client_with_response(response=fake_response)
        text, parsed, usage, raw = client._call(
            system="sys",
            contents=[TextPart("hello"), BytesPart(b"x", "image/png")],
            schema=_Echo,
            temperature=0.0,
            thinking_budget=0,
        )

        self.assertEqual(text, '{"vendor_name":"ACME"}')
        self.assertIs(parsed, echo)
        self.assertEqual(usage.input_tokens, 10)
        self.assertEqual(usage.output_tokens, 5)
        self.assertEqual(usage.total_tokens, 15)
        self.assertIs(raw, fake_response)
        config = client._client_factory().models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.kwargs["http_options"].timeout, 60_000)

    def test_call_passes_configured_timeout_to_google_genai(self) -> None:
        fake_response = types.SimpleNamespace(
            text='{"vendor_name":"ACME"}',
            parsed=_Echo(vendor_name="ACME"),
            usage_metadata=None,
        )
        sdk = MagicMock()
        sdk.models.generate_content.return_value = fake_response
        sdk.close = MagicMock()
        client = self.GeminiClient("gemini-2.5-flash", default_timeout=12.5, client_factory=lambda: sdk)
        client._call(
            system="",
            contents=[TextPart("x")],
            schema=_Echo,
            temperature=0.0,
            thinking_budget=None,
        )

        config = sdk.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.kwargs["http_options"].timeout, 12_500)

    def test_call_maps_google_deadline_exceeded_to_timeout(self) -> None:
        class DeadlineExceeded(Exception):
            status_code = 504

        sdk = MagicMock()
        sdk.models.generate_content.side_effect = DeadlineExceeded("504 DEADLINE_EXCEEDED")
        sdk.close = MagicMock()
        client = self.GeminiClient("gemini-2.5-flash", default_timeout=7, client_factory=lambda: sdk)

        with self.assertRaises(LLMTimeoutError) as ctx:
            client._call(
                system="",
                contents=[TextPart("x")],
                schema=_Echo,
                temperature=0.0,
                thinking_budget=None,
            )

        self.assertIn("7", str(ctx.exception))
        sdk.close.assert_called_once()

    def test_call_maps_google_internal_error_to_llm_error(self) -> None:
        class InternalError(Exception):
            status_code = 500

        sdk = MagicMock()
        sdk.models.generate_content.side_effect = InternalError("500 INTERNAL")
        sdk.close = MagicMock()
        client = self.GeminiClient("gemini-2.5-flash", client_factory=lambda: sdk)

        with self.assertRaises(LLMError) as ctx:
            client._call(
                system="",
                contents=[TextPart("x")],
                schema=_Echo,
                temperature=0.0,
                thinking_budget=None,
            )

        self.assertIn("Gemini transient error 500", str(ctx.exception))
        sdk.close.assert_called_once()

    def test_call_maps_google_resource_exhausted_to_rate_limit(self) -> None:
        class ResourceExhausted(Exception):
            status_code = 429

        sdk = MagicMock()
        sdk.models.generate_content.side_effect = ResourceExhausted("429 RESOURCE_EXHAUSTED: quota")
        sdk.close = MagicMock()
        client = self.GeminiClient("gemini-2.5-flash", client_factory=lambda: sdk)

        with self.assertRaises(LLMRateLimitError) as ctx:
            client._call(
                system="",
                contents=[TextPart("x")],
                schema=_Echo,
                temperature=0.0,
                thinking_budget=None,
            )

        self.assertIn("Gemini rate limit 429", str(ctx.exception))
        sdk.close.assert_called_once()

    def test_call_falls_back_to_validate_json_when_parsed_missing(self) -> None:
        fake_response = types.SimpleNamespace(
            text='{"vendor_name":"ACME"}',
            parsed=None,
            usage_metadata=types.SimpleNamespace(
                prompt_token_count=2, candidates_token_count=1, total_token_count=3
            ),
        )
        client = self._client_with_response(response=fake_response)
        _text, parsed, _usage, _raw = client._call(
            system="",
            contents=[TextPart("x")],
            schema=_Echo,
            temperature=0.0,
            thinking_budget=None,
        )
        self.assertIsInstance(parsed, _Echo)
        self.assertEqual(parsed.vendor_name, "ACME")

    def test_call_raises_validation_error_on_bad_schema(self) -> None:
        fake_response = types.SimpleNamespace(
            text='{"vendor_name": 12345}',  # wrong type
            parsed=None,
            usage_metadata=None,
        )
        client = self._client_with_response(response=fake_response)
        with self.assertRaises(LLMValidationError):
            client._call(
                system="",
                contents=[TextPart("x")],
                schema=type(
                    "StrictEcho",
                    (BaseModel,),
                    {
                        "__annotations__": {"vendor_name": str},
                        "model_config": ConfigDict(extra="forbid"),
                    },
                ),
                temperature=0.0,
                thinking_budget=None,
            )


def _fake_service_account_modules() -> tuple[types.ModuleType, types.ModuleType]:
    """Fake ``google.oauth2.service_account`` (the other test installs a fake ``google``)."""
    fake_oauth2 = types.ModuleType("google.oauth2")
    fake_sa = types.ModuleType("google.oauth2.service_account")

    class _Credentials:
        @staticmethod
        def from_service_account_file(path: str, scopes: Any = None) -> Any:
            return types.SimpleNamespace(project_id="proj-from-file")

    fake_sa.Credentials = _Credentials
    fake_oauth2.service_account = fake_sa
    return fake_oauth2, fake_sa


class LoadServiceAccountCredentialsTest(unittest.TestCase):
    def test_missing_file_raises_llm_error(self) -> None:
        fake_oauth2, fake_sa = _fake_service_account_modules()
        with patch.dict(
            sys.modules,
            {"google.oauth2": fake_oauth2, "google.oauth2.service_account": fake_sa},
        ):
            from app.llm.gemini import _load_service_account_credentials

            with self.assertRaises(LLMError) as ctx:
                _load_service_account_credentials(r"C:\\nope\\does-not-exist.json")
        self.assertIn("not found", str(ctx.exception))

    def test_returns_credentials_and_project_id(self) -> None:
        fake_oauth2, fake_sa = _fake_service_account_modules()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{}")
            path = fh.name
        try:
            with patch.dict(
                sys.modules,
                {"google.oauth2": fake_oauth2, "google.oauth2.service_account": fake_sa},
            ):
                from app.llm.gemini import _load_service_account_credentials

                credentials, project = _load_service_account_credentials(path)
            self.assertEqual(project, "proj-from-file")
            self.assertEqual(getattr(credentials, "project_id", None), "proj-from-file")
        finally:
            os.unlink(path)


class BuildNativeClientAuthTest(unittest.TestCase):
    def test_service_account_path_builds_vertex_client(self) -> None:
        from app.llm import gemini

        captured: dict[str, Any] = {}

        class _Client:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = _Client

        sentinel_credentials = object()

        with patch.object(gemini, "load_env_file", lambda: None), patch.object(
            gemini,
            "_load_service_account_credentials",
            lambda path: (sentinel_credentials, "sa-proj"),
        ), patch.dict(sys.modules, {"google.genai": fake_genai}), patch.dict(
            os.environ,
            {
                "GOOGLE_APPLICATION_CREDENTIALS": r"C:\\creds\\sa.json",
                "GOOGLE_CLOUD_PROJECT": "test-project",
                "GOOGLE_CLOUD_LOCATION": "global",
            },
            clear=True,
        ):
            gemini._build_native_client()

        self.assertTrue(captured.get("vertexai"))
        self.assertEqual(captured.get("project"), "test-project")
        self.assertEqual(captured.get("location"), "global")
        self.assertIs(captured.get("credentials"), sentinel_credentials)
        self.assertNotIn("api_key", captured)

    def test_service_account_falls_back_to_file_project(self) -> None:
        from app.llm import gemini

        captured: dict[str, Any] = {}

        class _Client:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = _Client

        with patch.object(gemini, "load_env_file", lambda: None), patch.object(
            gemini,
            "_load_service_account_credentials",
            lambda path: (object(), "proj-from-file"),
        ), patch.dict(sys.modules, {"google.genai": fake_genai}), patch.dict(
            os.environ,
            {"GOOGLE_APPLICATION_CREDENTIALS": r"C:\\creds\\sa.json"},
            clear=True,
        ):
            gemini._build_native_client()

        self.assertEqual(captured.get("project"), "proj-from-file")

    def test_missing_all_auth_raises_llm_error(self) -> None:
        from app.llm import gemini

        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = lambda **kwargs: None

        with patch.object(gemini, "load_env_file", lambda: None), patch.dict(
            sys.modules, {"google.genai": fake_genai}
        ), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMError):
                gemini._build_native_client()


if __name__ == "__main__":
    unittest.main()
