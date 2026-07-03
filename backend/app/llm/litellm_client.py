from __future__ import annotations

import base64
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

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


class LiteLLMClient(LLMClient):
    """Provider client backed by LiteLLM. Use for OpenAI / Claude / Mistral / etc.

    Gemini calls should continue to use ``GeminiClient`` directly because LiteLLM's
    ``vertex_ai/`` path requires Google ADC and does not accept Vertex Express API
    keys, while ``gemini/`` would route through AI Studio billing rather than the
    project's existing Vertex billing.
    """

    provider: ClassVar[str] = "litellm"

    def __init__(
        self,
        model: str,
        *,
        default_timeout: float = 60.0,
        **completion_kwargs: Any,
    ) -> None:
        super().__init__(model, default_timeout=default_timeout)
        self._extra_kwargs = completion_kwargs

    def _build_messages(self, system: str, contents: list[Part]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        user_parts: list[dict[str, Any]] = []
        for part in contents:
            if isinstance(part, TextPart):
                user_parts.append({"type": "text", "text": part.text})
            elif isinstance(part, BytesPart):
                if part.mime_type.startswith("image/"):
                    encoded = base64.b64encode(part.data).decode("ascii")
                    user_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{part.mime_type};base64,{encoded}"},
                        }
                    )
                elif part.mime_type == "application/pdf":
                    raise LLMError(
                        "LiteLLMClient does not support PDF input yet. Use GeminiClient for PDFs; "
                        "for other providers, render the PDF to images before passing BytesPart."
                    )
                else:
                    raise LLMError(f"LiteLLMClient unsupported mime_type: {part.mime_type}")
            else:
                raise LLMError(f"LiteLLMClient unsupported content type: {type(part).__name__}")
        if user_parts:
            messages.append({"role": "user", "content": user_parts})
        return messages

    def _call(
        self,
        *,
        system: str,
        contents: list[Part],
        schema: type[BaseModel] | None,
        temperature: float,
        thinking_budget: int | None,
    ) -> tuple[str, BaseModel | None, Usage, Any]:
        try:
            import litellm
            from litellm.exceptions import (
                APIConnectionError,
                APIError,
                AuthenticationError,
                BadRequestError,
                RateLimitError,
                Timeout,
            )
        except ImportError as exc:
            raise LLMError("Missing litellm dependency. Install it with: uv pip install litellm") from exc

        messages = self._build_messages(system, contents)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "timeout": self.default_timeout,
            **self._extra_kwargs,
        }
        if schema is not None:
            kwargs["response_format"] = schema

        try:
            response = litellm.completion(**kwargs)
        except RateLimitError as exc:
            raise LLMRateLimitError(str(exc)) from exc
        except Timeout as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except (AuthenticationError, BadRequestError, APIError, APIConnectionError) as exc:
            raise LLMError(str(exc)) from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LLMError("Model returned no choices")
        message = getattr(choices[0], "message", None)
        text = getattr(message, "content", None) or ""
        if not text:
            raise LLMError("Model returned empty content")

        usage_obj = getattr(response, "usage", None)
        usage = Usage(
            input_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage_obj, "total_tokens", 0) or 0),
        )
        if not usage.total_tokens:
            usage = Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
            )

        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(text)
            except ValidationError as exc:
                raise LLMValidationError(f"Response does not match schema: {exc}") from exc
            except ValueError as exc:
                raise LLMValidationError(f"Model returned invalid JSON: {exc}") from exc

        return text, parsed, usage, response

    def _compute_cost(self, usage: Usage, raw_response: Any) -> float:
        hidden = getattr(raw_response, "_hidden_params", None)
        if isinstance(hidden, dict):
            cost = hidden.get("response_cost")
            if cost is not None:
                try:
                    return float(cost)
                except (TypeError, ValueError):
                    pass
        return super()._compute_cost(usage, raw_response)
