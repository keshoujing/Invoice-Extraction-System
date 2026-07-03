from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Union

from pydantic import BaseModel


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class BytesPart:
    data: bytes
    mime_type: str


Part = Union[TextPart, BytesPart]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    text: str
    parsed: BaseModel | None
    usage: Usage
    latency_ms: int
    cost_usd: float
    model: str
    provider: str
    request_id: str
    raw_response: Any = None


class LLMError(RuntimeError):
    pass


class LLMValidationError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMClient(ABC):
    provider: ClassVar[str] = ""

    def __init__(self, model: str, *, default_timeout: float = 60.0) -> None:
        self.model = model
        self.default_timeout = default_timeout

    def generate(
        self,
        *,
        system: str,
        contents: list[Part],
        schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
        thinking_budget: int | None = 0,
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        from .telemetry import record_llm_call, record_llm_failure
        from .tracing import trace_llm_call

        request_id = uuid.uuid4().hex
        started = time.perf_counter()

        try:
            text, parsed, usage, raw = trace_llm_call(
                provider=self.provider,
                model=self.model,
                stage=stage,
                metadata=metadata or {},
                system=system,
                contents=contents,
                func=lambda: self._call(
                    system=system,
                    contents=contents,
                    schema=schema,
                    temperature=temperature,
                    thinking_budget=thinking_budget,
                ),
            )
        except Exception as exc:
            record_llm_failure(
                request_id=request_id,
                provider=self.provider,
                model=self.model,
                stage=stage,
                error_class=type(exc).__name__,
                error_message=str(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
                metadata=metadata or {},
            )
            raise

        latency_ms = int((time.perf_counter() - started) * 1000)
        response = LLMResponse(
            text=text,
            parsed=parsed,
            usage=usage,
            latency_ms=latency_ms,
            cost_usd=self._compute_cost(usage, raw),
            model=self.model,
            provider=self.provider,
            request_id=request_id,
            raw_response=raw,
        )
        record_llm_call(response, stage=stage, metadata=metadata or {})
        return response

    def _compute_cost(self, usage: Usage, raw_response: Any) -> float:
        """Default cost calc uses the project's static pricing table.

        Subclasses may override to use the provider's native cost (e.g. LiteLLM's
        ``response._hidden_params["response_cost"]``).
        """
        from .pricing import cost_usd
        return cost_usd(self.model, usage)

    @abstractmethod
    def _call(
        self,
        *,
        system: str,
        contents: list[Part],
        schema: type[BaseModel] | None,
        temperature: float,
        thinking_budget: int | None,
    ) -> tuple[str, BaseModel | None, Usage, Any]:
        ...
