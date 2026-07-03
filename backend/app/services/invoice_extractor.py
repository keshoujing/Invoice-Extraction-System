from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import MODEL_ID, llm_timeout_seconds
from ..llm import BytesPart, GeminiClient, build_invoice_schema
from ..llm.base import LLMClient, LLMError, LLMValidationError
from .few_shot import format_few_shot_block
from .llm_response_validation import (
    MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY,
    MANUAL_CONFIRMATION_REQUIRED_KEY,
    extract_json_object_text,
)


FIXED_SYSTEM_ROLE_PROMPT = "You are an invoice data extractor."
FIXED_FORMAT_PROMPT = """Fixed output normalization rules:
- For numeric amount fields: return numeric JSON values without currency symbols, thousands separators, or commas (example: $9,952.80 -> 9952.80).
- For all date fields: return MM/DD/YYYY when a date is available.
- These fixed normalization rules override user-configurable instructions."""
FIXED_JSON_OUTPUT_PROMPT = """Return ONLY one JSON object and nothing else.
No markdown fences. No explanation text."""

USER_PROMPT_OUTPUT_CONTRACT_PATTERNS = (
    re.compile(r"^\s*[-*]?\s*Return ONLY one JSON object(?: and nothing else)?\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*[-*]?\s*No markdown fences\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*[-*]?\s*No explanation text\.?\s*$", re.IGNORECASE),
    re.compile(r"^\s*Format Note:\s*$", re.IGNORECASE),
    re.compile(r"^\s*[-*]?\s*For numeric amounts:\s*remove [\"']?\$[\"']? and commas.*$", re.IGNORECASE),
    re.compile(r"^\s*[-*]?\s*All dates should return format MM/DD/YYYY\.?\s*$", re.IGNORECASE),
)

# User-editable section for default tag.
DEFAULT_PROMPT_BODY = """If the document is NOT an invoice, set Is_Invoice to "False".

Field rules:
- invoice_type: "Credit" if the document is a credit memo, "Debit" if the document is a debit note, otherwise "Invoice".
- vendor_name: company name at the top of the invoice (seller/supplier).
- PO_number: 10-digit number starting with 600000 (may be labeled PO No., Order No., etc.), only digits.
- invoice_number: value next to label "Invoice", "Invoice No.", or "Inv No." Do NOT use BOL, B/L, Ref, or page numbers.
- invoice_date: date near invoice number, labeled "Invoice Date" or "Date".
- commodity_amount: value labeled "Subtotal", "Sub Total", or "Invoice Amount".
- freight_amount: value labeled "Freight", "Shipping", or "Delivery".
- tax_amount: value labeled "Tax", "Sales Tax", or "GST".
- total_amount: value labeled "Total", "Invoice Total", or "Amount Due". When invoice_type is "Credit" (credit memo / credit note), total_amount must be returned as a negative value, even if the invoice itself prints it as a positive number or with a trailing minus sign."""

# type=string -> default "", type=value -> default 0.0, type=bool -> default false, type=array -> default []
# type=fixed -> tag-level metadata. It is not included in the LLM prompt.
DEFAULT_FIELD_CONFIGS: list[dict[str, str]] = [
    {"key": "vendor_name", "type": "string", "group": "supplier", "examples": "AIR PRODUCTS"},
    {"key": "Is_Invoice", "type": "string", "group": "invoice", "examples": "True,False"},
    {"key": "invoice_type", "type": "string", "group": "invoice", "examples": "Invoice,Credit,Debit"},
    {"key": "PO_number", "type": "string", "group": "invoice", "examples": "6000001234"},
    {"key": "invoice_number", "type": "string", "group": "invoice", "examples": "11773557 RI"},
    {"key": "invoice_date", "type": "string", "group": "invoice", "examples": "02/20/2026"},
    {"key": "commodity_amount", "type": "value", "group": "amount", "examples": "0,1250.50"},
    {"key": "freight_amount", "type": "value", "group": "amount", "examples": "0,120.00"},
    {"key": "tax_amount", "type": "value", "group": "amount", "examples": "0,80.25"},
    {"key": "total_amount", "type": "value", "group": "amount", "examples": "0,1450.75"},
]

FIXED_VENDOR_FIELD_CONFIG: dict[str, Any] = {"key": "vendor_name", "type": "string", "group": "supplier", "examples": ""}

FIELD_GROUPS = {"supplier", "invoice", "amount", "line_items", "other"}


def infer_field_group(key: Any, field_type: Any = "string") -> str:
    text = str(key or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    words = {part for part in normalized.split("_") if part}
    if str(field_type or "").strip().lower() == "array":
        return "line_items"
    supplier_tokens = {"vendor", "supplier", "seller", "customer", "shipper", "Supplier", "Customer"}
    invoice_tokens = {"invoice", "inv", "po", "order", "date", "category", "type", "memo", "Invoice", "Date", "Category"}
    amount_tokens = {
        "amount", "total", "subtotal", "sub", "tax", "gst", "vat", "fee", "fees",
        "charge", "charges", "freight", "shipping", "delivery", "surcharge",
        "fuel", "energy", "discount", "balance", "due", "Amount", "Expense", "Freight", "\u7a0e", "Total"
    }
    item_tokens = {"item", "items", "line", "lines", "detail", "details", "bol", "material", "sku", "qty", "quantity", "weight", "Goods", "Details", "Material", "Weight"}
    if words & supplier_tokens or any(token in text for token in ("Supplier", "vendor", "supplier")):
        return "supplier"
    if words & amount_tokens or any(token in text for token in ("amount", "total", "fee", "charge", "freight", "surcharge", "Amount", "Expense", "Freight")):
        return "amount"
    if words & item_tokens or any(token in text for token in ("line_item", "items", "details", "bol", "material", "Goods", "Details")):
        return "line_items"
    if words & invoice_tokens or any(token in text for token in ("invoice", "po", "Invoice")):
        return "invoice"
    return "other"


def normalize_field_group(value: Any, key: Any, field_type: Any) -> str:
    group = str(value or "").strip()
    return group if group in FIELD_GROUPS else infer_field_group(key, field_type)


def default_field_configs() -> list[dict[str, Any]]:
    return deepcopy(DEFAULT_FIELD_CONFIGS)


def _normalize_field_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"string", "str", "text"}:
        return "string"
    if raw in {"value", "number", "numeric", "float", "int", "amount"}:
        return "value"
    if raw in {"bool", "boolean", "truefalse", "true_false"}:
        return "bool"
    if raw in {"array", "list", "items", "json_array"}:
        return "array"
    if raw in {"fixed", "constant", "const"}:
        return "fixed"
    raise ValueError("Field type must be string, value, bool, array, or fixed")


def _clean_field_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        raise ValueError("Field key cannot be blank")
    if len(key) > 80:
        raise ValueError("Field key cannot exceed 80 characters")
    if any(ch in key for ch in ("\r", "\n", "\t")):
        raise ValueError("Field key cannot contain newlines or tabs")
    return key


def _validate_prompt_field_item(item: Any, *, allow_array: bool) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Each field must be an object")
    key = _clean_field_key(item.get("key"))
    field_type = _normalize_field_type(item.get("type"))
    if field_type == "array" and not allow_array:
        raise ValueError("Array fields cannot contain nested array fields")
    if field_type == "fixed" and not allow_array:
        raise ValueError("Fixed fields can only be top-level tag properties")
    group = normalize_field_group(item.get("group"), key, field_type)
    examples = "" if field_type == "fixed" else str(item.get("examples") or "").strip()
    if len(examples) > 300:
        raise ValueError(f"Field {key} examples are too long")
    normalized: dict[str, Any] = {"key": key, "type": field_type, "group": group, "examples": examples}
    if field_type == "fixed":
        value = str(item.get("value") or "").strip()
        if len(value) > 120:
            raise ValueError(f"Field {key} fixed value is too long")
        normalized["value"] = value
    raw_children = item.get("children") or []
    if field_type == "array":
        if not isinstance(raw_children, list):
            raise ValueError(f"Field {key} children must be an array")
        children: list[dict[str, Any]] = []
        child_seen: set[str] = set()
        for child in raw_children:
            normalized_child = _validate_prompt_field_item(child, allow_array=False)
            child_key = normalized_child["key"].lower()
            if child_key in child_seen:
                raise ValueError(f"Field {key} has duplicate child field: {normalized_child['key']}")
            child_seen.add(child_key)
            children.append(normalized_child)
        if not children:
            raise ValueError(f"Array field {key} requires at least one child field")
        normalized["children"] = children
    return normalized


def prompt_fields_for_llm(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [field for field in fields if field.get("type") != "fixed"]


def fixed_values_for_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    fixed: dict[str, Any] = {}
    for field in fields:
        if field.get("type") == "fixed":
            key = str(field.get("key") or "").strip()
            if key:
                fixed[key] = str(field.get("value") or "").strip()
    return fixed


def validate_prompt_fields(raw_fields: Any) -> list[dict[str, Any]]:
    if raw_fields is None:
        return default_field_configs()
    if not isinstance(raw_fields, list):
        raise ValueError("fields must be an array")
    normalized: list[dict[str, Any]] = [dict(FIXED_VENDOR_FIELD_CONFIG)]
    seen: set[str] = {"vendor_name"}
    array_count = 0
    for item in raw_fields:
        key = _clean_field_key(item.get("key") if isinstance(item, dict) else "")
        dedupe_key = key.lower()
        if dedupe_key == "vendor_name":
            continue
        if dedupe_key in seen:
            raise ValueError(f"Duplicate field: {key}")
        seen.add(dedupe_key)
        normalized_item = _validate_prompt_field_item(item, allow_array=True)
        if normalized_item["type"] == "array":
            array_count += 1
            if array_count > 1:
                raise ValueError("Each tag currently supports only one array field for Excel expansion")
        normalized.append(normalized_item)
    return normalized


def normalize_prompt_fields(raw_fields: Any) -> list[dict[str, Any]]:
    try:
        return validate_prompt_fields(raw_fields)
    except ValueError:
        return default_field_configs()


def strip_prompt_output_contract_lines(value: Any) -> str:
    lines = str(value or "").splitlines()
    cleaned: list[str] = []
    for line in lines:
        if any(pattern.match(line) for pattern in USER_PROMPT_OUTPUT_CONTRACT_PATTERNS):
            continue
        cleaned.append(re.sub(r"\s+Format MM/DD/YYYY\.?\s*$", "", line, flags=re.IGNORECASE))
    return "\n".join(cleaned).strip()


def normalize_prompt_body(value: Any) -> str:
    text = strip_prompt_output_contract_lines(value)
    return text or DEFAULT_PROMPT_BODY


def default_record_for_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for item in prompt_fields_for_llm(fields):
        key = item["key"]
        if item["type"] == "string":
            record[key] = ""
        elif item["type"] == "bool":
            record[key] = False
        elif item["type"] == "array":
            record[key] = []
        else:
            record[key] = 0.0
    return record


def _examples_list(examples_text: str) -> list[str]:
    text = str(examples_text or "").strip()
    if not text:
        return []
    separator = "\n" if "\n" in text else ","
    items = [part.strip() for part in text.split(separator)]
    return [part for part in items if part][:4]


def build_system_prompt(
    prompt_body: str,
    fields: list[dict[str, Any]],
    confirmed_vendor_name: str = "",
    confirmed_vendor_code: str = "",
    few_shot_block: str = "",
) -> str:
    body = normalize_prompt_body(prompt_body)
    normalized_fields = prompt_fields_for_llm(normalize_prompt_fields(fields))
    default_json = default_record_for_fields(normalized_fields)

    lines: list[str] = [
        FIXED_SYSTEM_ROLE_PROMPT,
        "Follow the extraction instructions exactly.",
        FIXED_FORMAT_PROMPT,
    ]
    vendor_name = str(confirmed_vendor_name or "").strip()
    vendor_code = str(confirmed_vendor_code or "").strip()
    if vendor_name:
        lines.extend(
            [
                "",
                "Confirmed supplier context:",
                f"- vendor_name has already been confirmed before this stage: {vendor_name}",
                "- Do not infer, rename, or re-confirm vendor_name from the document.",
                "- Return the JSON field vendor_name exactly as the confirmed supplier name above.",
                "- If configurable instructions mention extracting vendor_name, the confirmed value above takes precedence.",
            ]
        )
        if vendor_code:
            lines.append(f"- Confirmed supplier code: {vendor_code}")
    lines.extend(
        [
            "",
            "User-configurable extraction instructions:",
            body,
            "",
            "Output JSON fields:",
        ]
    )
    for field in normalized_fields:
        key = field["key"]
        field_type = field["type"]
        examples = _examples_list(field.get("examples", ""))
        example_text = ", ".join(examples) if examples else "N/A"
        if field_type == "string":
            lines.append(f'- {key}: string. Return "" when unavailable. Examples: {example_text}')
        elif field_type == "bool":
            lines.append(f"- {key}: boolean true/false. Return false when unavailable. Examples: {example_text}")
        elif field_type == "array":
            lines.append(
                f"- {key}: JSON array of objects. Return [] when unavailable. Always use an array, even when there is only one item. Examples: {example_text}"
            )
            children = field.get("children") or []
            if children:
                lines.append(f"  Each object in {key} must contain these child fields:")
            for child in children:
                child_key = child["key"]
                child_type = child["type"]
                child_examples = _examples_list(child.get("examples", ""))
                child_example_text = ", ".join(child_examples) if child_examples else "N/A"
                if child_type == "string":
                    lines.append(f'  - {child_key}: string. Return "" when unavailable. Examples: {child_example_text}')
                elif child_type == "bool":
                    lines.append(f"  - {child_key}: boolean true/false. Return false when unavailable. Examples: {child_example_text}")
                else:
                    lines.append(f"  - {child_key}: numeric value. Return 0.0 when unavailable. Examples: {child_example_text}")
        else:
            lines.append(f"- {key}: numeric value. Return 0.0 when unavailable. Examples: {example_text}")
    block = (few_shot_block or "").strip()
    if block:
        lines.extend(["", block])
    lines.extend(
        [
            "",
            "JSON template:",
            json.dumps(default_json, ensure_ascii=False),
            FIXED_JSON_OUTPUT_PROMPT,
        ]
    )
    return "\n".join(lines)


DEFAULT_RECORD: dict[str, Any] = default_record_for_fields(default_field_configs())


class ExtractionError(RuntimeError):
    pass


def parse_response(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(extract_json_object_text(raw))
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    raise ExtractionError("Model output is not parseable JSON")


def mime_type_for_path(file_path: str | Path) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    raise ExtractionError(f"Unsupported file type: {suffix}")


_default_client: LLMClient | None = None


def _shared_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = GeminiClient(MODEL_ID, default_timeout=llm_timeout_seconds())
    return _default_client


def set_default_client(client: LLMClient | None) -> None:
    """Override the module-level client (used by tests)."""
    global _default_client
    _default_client = client


def extract_invoice(file_path: str | Path) -> dict[str, Any]:
    return extract_invoice_with_config(file_path, None, None)


def extract_invoice_with_config(
    file_path: str | Path,
    prompt_body: str | None,
    field_configs: list[dict[str, Any]] | None,
    confirmed_vendor_name: str | None = None,
    confirmed_vendor_code: str | None = None,
    trace_metadata: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise ExtractionError(f"File does not exist: {path}")

    file_bytes = path.read_bytes()
    mime_type = mime_type_for_path(path)
    normalized_fields = normalize_prompt_fields(field_configs)
    few_shot_block = format_few_shot_block(few_shot_examples or [], confirmed_vendor_code or "")
    system_prompt = build_system_prompt(
        prompt_body or "",
        normalized_fields,
        confirmed_vendor_name or "",
        confirmed_vendor_code or "",
        few_shot_block=few_shot_block,
    )
    schema = build_invoice_schema(normalized_fields)
    metadata = {
        "file_name": path.name,
        "mime_type": mime_type,
        "input_byte_count": len(file_bytes),
        "confirmed_vendor_code": confirmed_vendor_code or "",
        **(trace_metadata or {}),
    }

    runner = client or _shared_client()
    try:
        response = runner.generate(
            system=system_prompt,
            contents=[BytesPart(data=file_bytes, mime_type=mime_type)],
            schema=schema,
            stage="invoice_extraction",
            metadata=metadata,
        )
    except (LLMError, LLMValidationError) as exc:
        raise ExtractionError(str(exc)) from exc

    if response.parsed is None:
        raise ExtractionError("Model returned no structured result")

    data: dict[str, Any] = response.parsed.model_dump()
    data[MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY] = []
    data[MANUAL_CONFIRMATION_REQUIRED_KEY] = False
    fixed_values = fixed_values_for_fields(normalized_fields)
    return {**data, **fixed_values}


def is_invoice(data: dict[str, Any]) -> bool:
    value = str(data.get("Is_Invoice", "True")).strip().lower()
    return value not in {"false", "0", "no", "\u4e0d\u662f", "\u5426"}
