from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list | dict):
        raise ValueError("expected string")
    return str(value).strip()


def _coerce_amount(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError("expected number")
    if isinstance(value, int | float):
        return round(float(value), 2)
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    return round(float(text), 2)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "\u662f"}:
        return True
    if text in {"false", "0", "no", "n", "\u5426", ""}:
        return False
    raise ValueError("expected boolean")


StringValue = Annotated[str, BeforeValidator(_coerce_string)]
AmountValue = Annotated[float, BeforeValidator(_coerce_amount)]
BoolValue = Annotated[bool, BeforeValidator(_coerce_bool)]


def _safe_model_name(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", raw or "Item")
    return cleaned or "Item"


def _annotation_for_field(field: dict[str, Any]) -> Any:
    field_type = str(field.get("type") or "string")
    if field_type == "value":
        return AmountValue
    if field_type == "bool":
        return BoolValue
    if field_type == "array":
        item_model = _build_array_item_model(field)
        return list[item_model]
    return StringValue


def _default_for_field(field: dict[str, Any]) -> Any:
    field_type = str(field.get("type") or "string")
    if field_type == "value":
        return 0.0
    if field_type == "bool":
        return False
    if field_type == "array":
        return []
    return ""


def _build_array_item_model(field: dict[str, Any]) -> type[BaseModel]:
    children = field.get("children") or []
    field_definitions: dict[str, tuple[Any, Any]] = {}
    for child in children:
        key = str(child.get("key") or "").strip()
        if not key:
            continue
        annotation = _annotation_for_field(child)
        default = _default_for_field(child)
        field_definitions[key] = (annotation, Field(default=default))
    name = f"InvoiceArrayItem_{_safe_model_name(str(field.get('key') or 'Item'))}"
    return create_model(name, __config__=ConfigDict(extra="allow"), **field_definitions)


def build_invoice_schema(fields: list[dict[str, Any]]) -> type[BaseModel]:
    """Build a Pydantic model that mirrors the dynamic invoice field configuration.

    The resulting model is suitable for ``response_schema`` on Gemini and ``response_format``
    on OpenAI; ``extra="allow"`` keeps any unexpected keys the model returns rather than
    failing the whole call.
    """
    field_definitions: dict[str, tuple[Any, Any]] = {}
    for field in fields:
        if field.get("type") == "fixed":
            continue
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        annotation = _annotation_for_field(field)
        default = _default_for_field(field)
        field_definitions[key] = (annotation, Field(default=default))
    return create_model(
        "DynamicInvoiceResponse",
        __config__=ConfigDict(extra="allow"),
        **field_definitions,
    )
