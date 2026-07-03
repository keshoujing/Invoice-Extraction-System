from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .database import now_iso


HITL_MODEL_OUTPUT_KEY = "_hitl_model_output"
CORE_REVIEW_FIELDS = (
    "vendor_code",
    "vendor_name",
    "PO_number",
    "invoice_number",
    "invoice_date",
    "total_amount",
)

_FIELD_ALIASES = {
    "vendor_code": "vendor_code",
    "Vendor Code": "vendor_code",
    "supplier_code": "vendor_code",
    "vendor_name": "vendor_name",
    "Vendor Name": "vendor_name",
    "supplier_name": "vendor_name",
    "po_number": "PO_number",
    "po": "PO_number",
    "purchase_order": "PO_number",
    "invoice_number": "invoice_number",
    "Invoice Number": "invoice_number",
    "\u53d1\u7968\u53f7\u7801": "invoice_number",
    "invoice_date": "invoice_date",
    "Invoice Date": "invoice_date",
    "\u53d1\u7968\u65e5\u671f": "invoice_date",
    "total_amount": "total_amount",
    "amount": "total_amount",
    "Total Amount": "total_amount",
    "\u603b\u91d1\u989d": "total_amount",
}


def canonical_review_field(field_key: str) -> str:
    raw = str(field_key or "").strip()
    lowered = raw.lower()
    return _FIELD_ALIASES.get(raw, _FIELD_ALIASES.get(lowered, raw))


def attach_model_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    snapshot = _without_internal_keys(data or {})
    next_data = dict(data or {})
    next_data[HITL_MODEL_OUTPUT_KEY] = snapshot
    return next_data


def model_snapshot_from_data(data: dict[str, Any]) -> dict[str, Any]:
    raw = (data or {}).get(HITL_MODEL_OUTPUT_KEY)
    return raw if isinstance(raw, dict) else {}


def public_review_data(data: dict[str, Any]) -> dict[str, Any]:
    return _without_internal_keys(data or {})


def changed_fields(
    model_output: dict[str, Any],
    confirmed_output: dict[str, Any],
    fields: tuple[str, ...] = CORE_REVIEW_FIELDS,
) -> list[str]:
    changed: list[str] = []
    for raw_field in fields:
        field = canonical_review_field(raw_field)
        if _normalized_value(field, model_output.get(field)) != _normalized_value(field, confirmed_output.get(field)):
            changed.append(field)
    return changed


def record_review_confirmation(
    cur: sqlite3.Cursor,
    *,
    invoice: dict[str, Any],
    model_output: dict[str, Any],
    confirmed_output: dict[str, Any],
    source_status: str,
) -> int | None:
    public_output = public_review_data(confirmed_output)
    changed = changed_fields(model_output, public_output)
    if not changed:
        return None

    timestamp = now_iso()
    supplier_code = str(
        public_output.get("vendor_code")
        or public_output.get("supplier_code")
        or invoice.get("vendor_code")
        or ""
    ).strip()
    supplier_name = str(public_output.get("vendor_name") or invoice.get("vendor_name") or "").strip()
    cur.execute(
        """
        INSERT INTO review_confirmations(
            invoice_id, confirmed_at, source_status, model_output_json,
            user_confirmed_json, fields_changed_json, was_corrected,
            supplier_code, supplier_name, prompt_tag, document_type
        )
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            int(invoice["id"]),
            timestamp,
            source_status,
            json_dumps(model_output or {}),
            json_dumps(public_output),
            json_dumps(changed),
            supplier_code,
            supplier_name,
            str(public_output.get("prompt_tag") or "").strip(),
            str(public_output.get("document_type") or "").strip(),
        ),
    )
    return int(cur.lastrowid)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _without_internal_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(data or {}).items() if key != HITL_MODEL_OUTPUT_KEY}


def _normalized_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    if field == "total_amount":
        text = str(value).strip().replace(",", "").replace("$", "")
        if not text:
            return ""
        try:
            return f"{float(text):.2f}"
        except ValueError:
            return text
    if field == "invoice_date":
        return _normalize_date(str(value))
    if field in {"invoice_number", "PO_number"}:
        return str(value).strip().replace(" ", "").lstrip("0")
    return str(value).strip()


def _normalize_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return text
