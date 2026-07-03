from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from ..config import default_service_account_path, load_env_file
from .base import (
    BytesPart,
    LLMClient,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMValidationError,
    Part,
    TextPart,
    Usage,
)


def _load_service_account_credentials(path: str) -> tuple[Any, str]:
    """Load a GC service-account JSON and return ``(credentials, project_id)``."""
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise LLMError("Missing google-auth dependency. Install backend/requirements.txt first.") from exc

    cred_path = Path(path).expanduser()
    if not cred_path.is_file():
        raise LLMError(f"Service Account credentials file not found: {cred_path}")
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(cred_path),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    except (ValueError, KeyError) as exc:
        raise LLMError(f"Invalid Service Account credentials file: {cred_path} ({exc})") from exc
    return credentials, (getattr(credentials, "project_id", "") or "")


def _build_native_client() -> Any:
    load_env_file()
    try:
        from google import genai
    except ImportError as exc:
        raise LLMError("Missing google-genai dependency. Install backend/requirements.txt first.") from exc

    project = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or os.getenv("VERTEX_PROJECT")
        or ""
    ).strip()
    location = (
        os.getenv("GOOGLE_CLOUD_LOCATION")
        or os.getenv("VERTEX_LOCATION")
        or "us-central1"
    ).strip()
    credentials_path = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not credentials_path:
        # Packaged app convention: secrets/gemini-service-account.json next to the exe.
        default_sa = default_service_account_path()
        if default_sa.is_file():
            credentials_path = str(default_sa)
    gemini_api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

    # Preferred: use a GC service account with Vertex AI, the production authentication path.
    if credentials_path:
        credentials, sa_project = _load_service_account_credentials(credentials_path)
        project = project or sa_project
        if not project:
            raise LLMError(
                "GOOGLE_CLOUD_PROJECT is required when using a Service Account, "
                "or the credential file must include project_id."
            )
        return genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
        )

    # Fallback: use local ADC (gcloud auth application-default login) with Vertex AI.
    if project:
        return genai.Client(vertexai=True, project=project, location=location)

    # Last resort: AI Studio API key, not Vertex, for temporary local development only.
    if gemini_api_key:
        return genai.Client(api_key=gemini_api_key)

    raise LLMError(
        "Missing model authentication. Set GOOGLE_APPLICATION_CREDENTIALS to a GC Service Account JSON "
        "and configure GOOGLE_CLOUD_PROJECT (recommended), configure local ADC, or temporarily set GEMINI_API_KEY."
    )


def _usage_from_response(response: Any) -> Usage:
    usage = getattr(response, "usage_metadata", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage_metadata")
    if usage is None:
        return Usage()

    def read(*names: str) -> int:
        for name in names:
            raw = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
        return 0

    input_tokens = read("prompt_token_count", "input_tokens")
    output_tokens = read("candidates_token_count", "output_tokens")
    total = read("total_token_count", "total_tokens")
    if not total:
        total = input_tokens + output_tokens
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total)


def _is_deadline_exceeded(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 504:
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return "deadline_exceeded" in text or "deadline expired" in text


def _provider_status_code(exc: Exception) -> int | None:
    raw = getattr(exc, "status_code", None)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_rate_limit_error(exc: Exception) -> bool:
    if _provider_status_code(exc) == 429:
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "resource_exhausted",
            "rate limit",
            "rate_limit",
            "too many requests",
            "quota",
        )
    )


def _is_transient_provider_error(exc: Exception) -> bool:
    status_code = _provider_status_code(exc)
    if status_code in {499, 500, 502, 503, 504}:
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "cancelled",
            "deadline_exceeded",
            "internal error",
            "temporarily unavailable",
            "service unavailable",
            "readtimeout",
            "read operation timed out",
        )
    )


class GeminiClient(LLMClient):
    provider: ClassVar[str] = "gemini"

    def __init__(
        self,
        model: str,
        *,
        default_timeout: float = 60.0,
        client_factory: Any = None,
    ) -> None:
        super().__init__(model, default_timeout=default_timeout)
        self._client_factory = client_factory or _build_native_client

    def _build_parts(self, contents: list[Part]) -> list[Any]:
        from google.genai import types

        parts: list[Any] = []
        for item in contents:
            if isinstance(item, TextPart):
                parts.append(types.Part.from_text(text=item.text))
            elif isinstance(item, BytesPart):
                parts.append(types.Part.from_bytes(data=item.data, mime_type=item.mime_type))
            else:
                raise LLMError(f"Unsupported content type: {type(item).__name__}")
        return parts

    def _call(
        self,
        *,
        system: str,
        contents: list[Part],
        schema: type[BaseModel] | None,
        temperature: float,
        thinking_budget: int | None,
    ) -> tuple[str, BaseModel | None, Usage, Any]:
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "temperature": temperature,
            "http_options": types.HttpOptions(timeout=max(1, int(self.default_timeout * 1000))),
        }
        if schema is not None:
            config_kwargs["response_schema"] = schema
        if thinking_budget is not None:
            thinking_fields = getattr(types.ThinkingConfig, "model_fields", {})
            if "thinking_budget" in thinking_fields:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

        client = self._client_factory()
        try:
            try:
                response = client.models.generate_content(
                    model=self.model,
                    config=types.GenerateContentConfig(**config_kwargs),
                    contents=self._build_parts(contents),
                )
            except TimeoutError as exc:
                raise LLMTimeoutError(f"Gemini request exceeded {self.default_timeout:.0f} seconds without a response") from exc
            except Exception as exc:
                if "timeout" in type(exc).__name__.lower() or _is_deadline_exceeded(exc):
                    raise LLMTimeoutError(f"Gemini request exceeded {self.default_timeout:.0f} seconds without a response") from exc
                if _is_rate_limit_error(exc):
                    status_code = _provider_status_code(exc)
                    prefix = f"Gemini rate limit {status_code}" if status_code else "Gemini rate limit"
                    raise LLMRateLimitError(f"{prefix}: {exc}") from exc
                if _is_transient_provider_error(exc):
                    status_code = _provider_status_code(exc)
                    prefix = f"Gemini transient error {status_code}" if status_code else "Gemini transient error"
                    raise LLMError(f"{prefix}: {exc}") from exc
                raise
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        text = getattr(response, "text", "") or ""
        if not text:
            raise LLMError("Model returned empty content")

        parsed: BaseModel | None = None
        if schema is not None:
            parsed_attr = getattr(response, "parsed", None)
            if isinstance(parsed_attr, schema):
                parsed = parsed_attr
            else:
                try:
                    parsed = schema.model_validate_json(text)
                except ValidationError as exc:
                    raise LLMValidationError(f"Response does not match schema: {exc}") from exc
                except ValueError as exc:
                    raise LLMValidationError(f"Model returned invalid JSON: {exc}") from exc

        return text, parsed, _usage_from_response(response), response
