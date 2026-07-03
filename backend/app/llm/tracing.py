from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .base import BytesPart, Part, TextPart, Usage


TRUTHY_ENV_VALUES = {"1", "true", "yes", "y", "on"}
TEXT_TRUNCATE_LIMIT = 12_000

CallResult = tuple[str, BaseModel | None, Usage, Any]

RAW_RESPONSE_METADATA_FIELDS = (
    "id",
    "model",
    "model_version",
    "created",
    "object",
    "service_tier",
    "system_fingerprint",
    "prompt_feedback",
    "response_metadata",
)
CANDIDATE_METADATA_FIELDS = (
    "index",
    "finish_reason",
    "finish_message",
    "safety_ratings",
    "citation_metadata",
    "grounding_metadata",
    "avg_logprobs",
)


def langsmith_tracing_enabled() -> bool:
    return (os.getenv("LANGSMITH_TRACING") or "").strip().lower() in TRUTHY_ENV_VALUES


def _truncate_text(value: str, limit: int = TEXT_TRUNCATE_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated {len(value) - limit} chars]"


def sanitize_trace_payload(value: Any) -> Any:
    if isinstance(value, bytes | bytearray | memoryview):
        return {"type": "bytes", "byte_count": len(value)}
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): sanitize_trace_payload(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [sanitize_trace_payload(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return sanitize_trace_payload(model_dump())
        except Exception:
            pass

    as_dict = getattr(value, "__dict__", None)
    if isinstance(as_dict, dict):
        public = {key: item for key, item in as_dict.items() if not str(key).startswith("_")}
        if public:
            return sanitize_trace_payload(public)

    return _truncate_text(repr(value))


def _summarize_part(part: Part) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {"kind": "text", "text": _truncate_text(part.text)}
    if isinstance(part, BytesPart):
        return {"kind": "bytes", "mime_type": part.mime_type, "byte_count": len(part.data)}
    return {"kind": "unknown", "repr": _truncate_text(repr(part))}


def _read_field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _raw_usage_metadata(raw_response: Any) -> Any:
    return _read_field(raw_response, "usage_metadata") or _read_field(raw_response, "usage")


def _provider_reported_cost(raw_response: Any) -> float | None:
    hidden = _read_field(raw_response, "_hidden_params")
    if not isinstance(hidden, dict):
        return None
    raw_cost = hidden.get("response_cost")
    if raw_cost is None:
        return None
    try:
        return float(raw_cost)
    except (TypeError, ValueError):
        return None


def _cost_metadata(model: str, usage: Usage, raw_response: Any) -> dict[str, Any]:
    from .pricing import PRICING, cost_usd

    provider_cost = _provider_reported_cost(raw_response)
    estimated_cost = cost_usd(model, usage)
    if provider_cost is not None:
        return {
            "cost_usd": provider_cost,
            "cost_source": "provider",
            "provider_reported_cost_usd": provider_cost,
            "estimated_cost_usd": estimated_cost if model in PRICING else None,
        }
    if model in PRICING:
        return {
            "cost_usd": estimated_cost,
            "cost_source": "pricing_table",
            "provider_reported_cost_usd": None,
            "estimated_cost_usd": estimated_cost,
        }
    return {
        "cost_usd": None,
        "cost_source": "unavailable",
        "provider_reported_cost_usd": None,
        "estimated_cost_usd": None,
    }


def _candidate_metadata(candidate: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field in CANDIDATE_METADATA_FIELDS:
        value = _read_field(candidate, field)
        if value is not None:
            metadata[field] = sanitize_trace_payload(value)
    return metadata


def _raw_response_metadata(raw_response: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field in RAW_RESPONSE_METADATA_FIELDS:
        value = _read_field(raw_response, field)
        if value is not None:
            metadata[field] = sanitize_trace_payload(value)

    candidates = _read_field(raw_response, "candidates")
    if candidates:
        metadata["candidates"] = [
            item for item in (_candidate_metadata(candidate) for candidate in candidates) if item
        ]
    return metadata


def trace_llm_call(
    *,
    provider: str,
    model: str,
    stage: str,
    metadata: dict[str, Any],
    system: str,
    contents: list[Part],
    func: Callable[[], CallResult],
) -> CallResult:
    if not langsmith_tracing_enabled():
        return func()

    try:
        from langsmith import traceable
    except Exception:
        return func()

    trace_metadata = {
        "ls_provider": provider,
        "ls_model_name": model,
        "stage": stage,
        **sanitize_trace_payload(metadata),
    }
    inputs = {
        "model": model,
        "stage": stage,
        "system": _truncate_text(system),
        "contents": [_summarize_part(part) for part in contents],
        "metadata": trace_metadata,
    }

    def process_inputs(_inputs: dict[str, Any]) -> dict[str, Any]:
        return inputs

    def process_outputs(result: CallResult | Any) -> dict[str, Any]:
        if not isinstance(result, tuple) or len(result) != 4:
            return {"messages": [], "usage_metadata": {}}
        text, _parsed, usage, raw = result
        usage_metadata = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
        raw_usage = _raw_usage_metadata(raw)
        if raw_usage is not None:
            usage_metadata["raw"] = sanitize_trace_payload(raw_usage)

        return {
            "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": _truncate_text(text)}]}
            ],
            "usage_metadata": usage_metadata,
            "cost_metadata": _cost_metadata(model, usage, raw),
            "response_metadata": _raw_response_metadata(raw),
        }

    traced = traceable(
        name=f"{provider}.{stage}" if stage else provider,
        run_type="llm",
        metadata=trace_metadata,
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )(func)
    return traced()
