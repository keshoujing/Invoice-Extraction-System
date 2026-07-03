from __future__ import annotations

import json
import logging
import sqlite3
import shutil
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import (
    CONFIRMED_DIR,
    PENDING_DIR,
    ensure_directories,
    frontend_dist_dir,
    hitl_review_enabled,
    load_env_file,
    supplier_confidence_threshold,
    supplier_preview_worker_count,
)
from .database import db_cursor, get_extracted_data, init_db, now_iso, row_to_dict, rows_to_dicts, upsert_extracted_data
from .schemas import (
    ActiveRecognitionOut,
    DeleteInvoiceOut,
    DirectorySelectionOut,
    ExportOut,
    ExportRequest,
    ExportStatsOut,
    InvoiceOut,
    PromptTagCreateRequest,
    PromptTagDeleteOut,
    PromptTagExportSettings,
    PromptTagOut,
    PromptTagSuppliersRequest,
    PromptTagUpdateRequest,
    PromptRulesExportOut,
    PromptRulesImportOut,
    PromptRulesImportRequest,
    PromptRulesAutoArchiveCheckItem,
    PromptRulesSchemeItem,
    PromptRulesStaleConflict,
    PromptRulesSupplierMapItem,
    PromptRulesSupplierSchemeItem,
    PromptRulesSupplierItem,
    PromptRulesSpecialDocumentRuleItem,
    PromptRulesTagItem,
    RecognitionJobOut,
    RecognitionRequest,
    SchemeCreate,
    SchemeOut,
    SchemeUpdate,
    SpecialDocumentRuleCreateRequest,
    SpecialDocumentRuleDeleteOut,
    SpecialDocumentRuleOut,
    SpecialDocumentRuleUpdateRequest,
    SupplierAutoArchiveCheck,
    SupplierAutoArchiveConfigOut,
    SupplierAutoArchiveConfigUpdate,
    SupplierConfirmRequest,
    SupplierCreate,
    SupplierOut,
    SupplierSchemeAssign,
    UpdateExtractedDataRequest,
    UploadPreviewJobOut,
)
from .services.exporter import export_confirmed
from .services.auto_archive import evaluate_auto_archive_checks
from .services.formatters import amount_to_float, format_invoice_date, parse_invoice_date, safe_filename
from .services.few_shot import get_few_shot_examples
from .services.invoice_extractor import (
    DEFAULT_PROMPT_BODY,
    ExtractionError,
    default_field_configs,
    extract_invoice_with_config,
    fixed_values_for_fields,
    is_invoice,
    mime_type_for_path,
    normalize_prompt_body,
    normalize_prompt_fields,
    strip_prompt_output_contract_lines,
    validate_prompt_fields,
)
from .services.llm_response_validation import (
    MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY,
    MANUAL_CONFIRMATION_REQUIRED_KEY,
)
from .review_labels import (
    attach_model_snapshot,
    model_snapshot_from_data,
    record_review_confirmation,
)
from .services.supplier_preview_extractor import SupplierPreviewError, extract_supplier_preview
from .services.supplier_matcher import SupplierMatcher


ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_RECOGNITION_WORKERS = 5
DEFAULT_PROMPT_TAG = "default"
AUTO_ARCHIVE_FAILED_FIELDS_KEY = "_auto_archive_failed_fields"
supplier_matcher = SupplierMatcher()
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Invoice Archive API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    load_env_file()
    ensure_directories()
    init_db()
    _mark_interrupted_jobs_failed()
    _ensure_default_scheme()
    supplier_matcher.reload()
    from .llm.telemetry import purge_old_llm_calls
    purge_old_llm_calls()


INVOICE_DATE_KEYS = ("invoice_date", "Invoice Date")
INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE = "The previous supplier preview was interrupted. Click retry supplier preview."
INTERRUPTED_RECOGNITION_MESSAGE = "The previous recognition job was interrupted. Start recognition again."


def _mark_interrupted_jobs_failed() -> None:
    timestamp = now_iso()
    with db_cursor() as cur:
        interrupted_preview_items = cur.execute(
            """
            SELECT item.invoice_id, data.data_json
            FROM upload_preview_job_items item
            JOIN upload_preview_jobs job ON job.id = item.job_id
            LEFT JOIN extracted_data data ON data.invoice_id = item.invoice_id
            WHERE job.status IN ('queued', 'running')
              AND item.status IN ('queued', 'running')
            """
        ).fetchall()
        for item in interrupted_preview_items:
            data: dict[str, Any] = {}
            raw_json = item["data_json"]
            if raw_json:
                try:
                    parsed = json.loads(raw_json)
                    if isinstance(parsed, dict):
                        data = parsed
                except json.JSONDecodeError:
                    data = {}
            if str(data.get("supplier_stage") or "").strip().lower() == "scanning":
                data.update(
                    {
                        "supplier_stage": "needs_confirmation",
                        "supplier_confirmed": "False",
                        "supplier_needs_confirmation": "True",
                        "supplier_warning": INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE,
                    }
                )
                upsert_extracted_data(cur, int(item["invoice_id"]), data)
            cur.execute(
                """
                UPDATE invoices
                SET error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE, timestamp, int(item["invoice_id"])),
            )

        cur.execute(
            """
            UPDATE upload_preview_job_items
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE status IN ('queued', 'running')
              AND job_id IN (
                SELECT id FROM upload_preview_jobs WHERE status IN ('queued', 'running')
              )
            """,
            (INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE, timestamp),
        )
        cur.execute(
            """
            UPDATE upload_preview_jobs
            SET status = 'failed',
                processed = total,
                failed_count = total - succeeded,
                error_message = ?,
                updated_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (INTERRUPTED_SUPPLIER_PREVIEW_MESSAGE, timestamp),
        )
        cur.execute(
            """
            UPDATE recognition_job_items
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE status IN ('queued', 'running')
              AND job_id IN (
                SELECT id FROM recognition_jobs WHERE status IN ('queued', 'running')
              )
            """,
            (INTERRUPTED_RECOGNITION_MESSAGE, timestamp),
        )
        cur.execute(
            """
            UPDATE recognition_jobs
            SET status = 'failed',
                processed = total,
                failed_count = total - succeeded,
                error_message = ?,
                updated_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (INTERRUPTED_RECOGNITION_MESSAGE, timestamp),
        )


def _is_default_tag_name(tag_name: str) -> bool:
    return str(tag_name or "").strip().lower() == DEFAULT_PROMPT_TAG


def _normalize_tag_name(tag_name: str) -> str:
    value = str(tag_name or "").strip()
    if not value:
        raise ValueError("tag cannot be blank")
    if len(value) > 40:
        raise ValueError("tag cannot exceed 40 characters")
    if any(ch in value for ch in ("\r", "\n", "\t")):
        raise ValueError("tag cannot contain newlines or tabs")
    if _is_default_tag_name(value):
        return DEFAULT_PROMPT_TAG
    return value


def _normalize_vendor_codes(vendor_codes: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for code in vendor_codes:
        text = str(code or "").strip()
        if not text:
            continue
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(text)
    return normalized


def _serialize_prompt_fields(fields: list[dict[str, Any]]) -> str:
    normalized = validate_prompt_fields(fields)
    return json.dumps(normalized, ensure_ascii=False)


def _deserialize_prompt_fields(fields_json: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(fields_json)
    except json.JSONDecodeError:
        return default_field_configs()
    return normalize_prompt_fields(raw)


def _serialize_export_settings(settings: PromptTagExportSettings | None) -> str:
    if settings is None:
        return ""
    return json.dumps(settings.model_dump(), ensure_ascii=False)


def _deserialize_export_settings(settings_json: str) -> PromptTagExportSettings:
    if not str(settings_json or "").strip():
        return PromptTagExportSettings()
    try:
        raw = json.loads(settings_json)
        if isinstance(raw, dict):
            return PromptTagExportSettings.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    return PromptTagExportSettings()


def _ensure_prompt_tag_defaults() -> None:
    timestamp = now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompt_tags(tag_name, prompt_body, fields_json, is_default, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(tag_name) DO NOTHING
            """,
            (
                DEFAULT_PROMPT_TAG,
                DEFAULT_PROMPT_BODY,
                json.dumps(default_field_configs(), ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        cur.execute(
            """
            UPDATE prompt_tags
            SET is_default = CASE WHEN lower(tag_name) = ? THEN 1 ELSE 0 END
            """,
            (DEFAULT_PROMPT_TAG,),
        )


def _ensure_default_scheme() -> None:
    timestamp = now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO schemes(name, preview_prompt_body, preview_prompt_enabled,
                                prompt_body, fields_json, export_settings_json,
                                is_default, created_at, updated_at)
            VALUES (?, '', 0, ?, ?, '', 1, ?, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (
                DEFAULT_PROMPT_TAG,
                DEFAULT_PROMPT_BODY,
                json.dumps(default_field_configs(), ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        cur.execute(
            """
            UPDATE schemes
            SET is_default = CASE WHEN lower(name) = ? THEN 1 ELSE 0 END
            """,
            (DEFAULT_PROMPT_TAG,),
        )


def _get_scheme_row(name: str) -> dict[str, Any] | None:
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT name, preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json, is_default, updated_at
            FROM schemes
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
    return row_to_dict(row)


def _scheme_supplier_counts() -> dict[str, int]:
    with db_cursor() as cur:
        rows = cur.execute(
            "SELECT scheme_name, COUNT(*) AS n FROM supplier_scheme_map GROUP BY scheme_name"
        ).fetchall()
    return {str(row["scheme_name"]): int(row["n"]) for row in rows}


def _scheme_row_to_out(row: dict[str, Any], supplier_count: int = 0) -> SchemeOut:
    return SchemeOut(
        name=str(row.get("name") or ""),
        preview_prompt_body=strip_prompt_output_contract_lines(row.get("preview_prompt_body")),
        preview_prompt_enabled=_to_bool(row.get("preview_prompt_enabled")),
        prompt_body=strip_prompt_output_contract_lines(row.get("prompt_body")),
        fields=_deserialize_prompt_fields(str(row.get("fields_json") or "")),
        export_settings=_deserialize_export_settings(str(row.get("export_settings_json") or "")),
        is_default=bool(int(row.get("is_default") or 0)),
        supplier_count=supplier_count,
        updated_at=str(row.get("updated_at") or ""),
    )


def _prompt_rules_scheme_item(row: dict[str, Any]) -> PromptRulesSchemeItem:
    return PromptRulesSchemeItem(
        name=str(row.get("name") or ""),
        preview_prompt_body=strip_prompt_output_contract_lines(row.get("preview_prompt_body")),
        preview_prompt_enabled=_to_bool(row.get("preview_prompt_enabled")),
        prompt_body=strip_prompt_output_contract_lines(row.get("prompt_body")),
        fields=_deserialize_prompt_fields(str(row.get("fields_json") or "")),
        export_settings=_deserialize_export_settings(str(row.get("export_settings_json") or "")),
        is_default=bool(int(row.get("is_default") or 0)),
        updated_at=str(row.get("updated_at") or ""),
    )


def _get_prompt_tag_row(tag_name: str) -> dict[str, Any] | None:
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT tag_name, prompt_body, fields_json, export_settings_json, is_default, updated_at
            FROM prompt_tags
            WHERE tag_name = ?
            """,
            (tag_name,),
        ).fetchone()
    return row_to_dict(row)


def _get_special_document_rule_row(vendor_code: str) -> dict[str, Any] | None:
    code = str(vendor_code or "").strip()
    if not code:
        return None
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT vendor_code, vendor_name, prompt_body, fields_json, is_active, created_at, updated_at
            FROM special_document_rules
            WHERE vendor_code = ?
            """,
            (code,),
        ).fetchone()
    return row_to_dict(row)


def _require_prompt_tag(tag_name: str) -> dict[str, Any]:
    try:
        tag = _normalize_tag_name(tag_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = _get_prompt_tag_row(tag)
    if not row:
        raise HTTPException(status_code=404, detail=f"tag does not exist: {tag}")
    return row


def _require_special_document_rule(vendor_code: str) -> dict[str, Any]:
    code = str(vendor_code or "").strip()
    row = _get_special_document_rule_row(code)
    if not row:
        raise HTTPException(status_code=404, detail=f"Special document rule does not exist: {code}")
    return row


def _supplier_tag_map() -> dict[str, str]:
    with db_cursor() as cur:
        rows = cur.execute("SELECT vendor_code, tag_name FROM supplier_tag_map").fetchall()
    mapping: dict[str, str] = {}
    for row in rows_to_dicts(rows):
        code = str(row.get("vendor_code") or "").strip()
        tag = str(row.get("tag_name") or "").strip()
        if code and tag:
            mapping[code] = tag
    return mapping


def _default_special_document_template() -> tuple[str, list[dict[str, Any]]]:
    row = _get_prompt_tag_row(DEFAULT_PROMPT_TAG)
    if not row:
        return DEFAULT_PROMPT_BODY, default_field_configs()
    prompt_body = strip_prompt_output_contract_lines(row.get("prompt_body")) or DEFAULT_PROMPT_BODY
    fields = _deserialize_prompt_fields(str(row.get("fields_json") or ""))
    return prompt_body, fields


def _special_document_rule_out(row: dict[str, Any]) -> SpecialDocumentRuleOut:
    return SpecialDocumentRuleOut(
        vendor_code=str(row.get("vendor_code") or ""),
        vendor_name=str(row.get("vendor_name") or ""),
        prompt_body=strip_prompt_output_contract_lines(row.get("prompt_body")),
        fields=_deserialize_prompt_fields(str(row.get("fields_json") or "")),
        is_active=bool(int(row.get("is_active") or 0)),
        updated_at=str(row.get("updated_at") or ""),
    )


def _active_special_document_rules() -> list[dict[str, Any]]:
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT vendor_code, vendor_name, prompt_body, fields_json, is_active, created_at, updated_at
            FROM special_document_rules
            WHERE is_active = 1
            ORDER BY vendor_name COLLATE NOCASE ASC, vendor_code COLLATE NOCASE ASC
            """
        ).fetchall()
    return rows_to_dicts(rows)


def _special_document_preview_rules() -> list[dict[str, str]]:
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT m.vendor_code, s.name AS vendor_name, m.scheme_name,
                   sc.preview_prompt_body
            FROM supplier_scheme_map m
            INNER JOIN suppliers s ON s.code = m.vendor_code
            INNER JOIN schemes sc ON sc.name = m.scheme_name
            WHERE sc.preview_prompt_enabled = 1
              AND TRIM(COALESCE(sc.preview_prompt_body, '')) <> ''
            ORDER BY sc.name COLLATE NOCASE ASC, s.name COLLATE NOCASE ASC
            """
        ).fetchall()
    rules: list[dict[str, str]] = []
    for row in rows_to_dicts(rows):
        code = str(row.get("vendor_code") or "").strip()
        name = str(row.get("vendor_name") or "").strip()
        prompt = strip_prompt_output_contract_lines(row.get("preview_prompt_body"))
        if not code or not name or not prompt:
            continue
        rules.append(
            {
                "vendor_code": code,
                "vendor_name": name,
                "scheme_name": str(row.get("scheme_name") or "").strip(),
                "prompt_body": prompt,
            }
        )
    return rules


def _special_document_rule_for_supplier(vendor_code: str) -> tuple[dict[str, Any], str, list[dict[str, Any]]] | None:
    return None


def _combine_recognition_prompt(
    tag_name: str,
    tag_prompt_body: str,
    special_prompt_body: str = "",
) -> str:
    special = str(special_prompt_body or "").strip()
    if not special:
        return tag_prompt_body
    if _is_default_tag_name(tag_name):
        return special
    return (
        f"{tag_prompt_body.rstrip()}\n\n"
        "Special document guidance for this supplier:\n"
        f"{special}"
    )


def _prompt_tag_supplier_count(tag_name: str, mapping: dict[str, str]) -> int:
    suppliers = supplier_matcher.list()
    all_codes = [item.code for item in suppliers]
    if _is_default_tag_name(tag_name):
        assigned_to_custom = {
            code
            for code, mapped_tag in mapping.items()
            if code in all_codes and not _is_default_tag_name(mapped_tag)
        }
        return max(0, len(all_codes) - len(assigned_to_custom))
    return sum(
        1 for code, mapped_tag in mapping.items() if code in all_codes and mapped_tag == tag_name
    )


def _prompt_tag_out(row: dict[str, Any], supplier_count: int) -> PromptTagOut:
    fields = _deserialize_prompt_fields(str(row.get("fields_json") or ""))
    export_settings = _deserialize_export_settings(str(row.get("export_settings_json") or ""))
    return PromptTagOut(
        tag=str(row.get("tag_name") or ""),
        prompt_body=strip_prompt_output_contract_lines(row.get("prompt_body")),
        fields=fields,
        export_settings=export_settings,
        is_default=bool(int(row.get("is_default") or 0)),
        supplier_count=supplier_count,
        updated_at=str(row.get("updated_at") or ""),
    )


def _prompt_rules_tag_item(row: dict[str, Any]) -> PromptRulesTagItem:
    return PromptRulesTagItem(
        tag=str(row.get("tag_name") or ""),
        prompt_body=strip_prompt_output_contract_lines(row.get("prompt_body")),
        fields=_deserialize_prompt_fields(str(row.get("fields_json") or "")),
        export_settings=_deserialize_export_settings(str(row.get("export_settings_json") or "")),
        is_default=bool(int(row.get("is_default") or 0)),
        updated_at=str(row.get("updated_at") or ""),
    )


def _normalize_import_rule_tags(items: list[PromptRulesTagItem]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for item in items:
        tag = _normalize_tag_name(item.tag)
        if item.is_default and not _is_default_tag_name(tag):
            raise ValueError("Only default can be marked as the default tag in the import file")
        fields_payload = [field.model_dump() for field in item.fields] if item.fields else default_field_configs()
        normalized[tag] = {
            "tag_name": tag,
            "prompt_body": strip_prompt_output_contract_lines(item.prompt_body),
            "fields_json": _serialize_prompt_fields(fields_payload),
            "export_settings_json": _serialize_export_settings(item.export_settings),
            "is_default": 1 if _is_default_tag_name(tag) else 0,
            "updated_at": str(item.updated_at or "").strip(),
        }
    return normalized


def _normalize_import_supplier_mappings(
    items: list[PromptRulesSupplierMapItem],
    available_tags: set[str],
) -> tuple[dict[str, dict[str, str]], list[str], list[str]]:
    supplier_codes = {item.code for item in supplier_matcher.list()}
    mappings: dict[str, dict[str, str]] = {}
    skipped_supplier_codes: list[str] = []
    skipped_mappings: list[str] = []
    skipped_code_set: set[str] = set()

    for item in items:
        code = str(item.vendor_code or "").strip()
        if not code:
            continue
        if code not in supplier_codes:
            if code.lower() not in skipped_code_set:
                skipped_code_set.add(code.lower())
                skipped_supplier_codes.append(code)
            continue
        try:
            tag = _normalize_tag_name(item.tag)
        except ValueError as exc:
            skipped_mappings.append(f"{code}: {exc}")
            continue
        if tag not in available_tags:
            skipped_mappings.append(f"{code}: tag does not exist: {tag}")
            continue
        mappings[code] = {
            "vendor_code": code,
            "tag_name": tag,
            "updated_at": str(item.updated_at or "").strip(),
        }

    return mappings, skipped_supplier_codes, skipped_mappings


def _normalize_import_special_document_rules(
    items: list[PromptRulesSpecialDocumentRuleItem],
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    suppliers_by_code = {item.code: item for item in supplier_matcher.list()}
    normalized: dict[str, dict[str, Any]] = {}
    skipped_supplier_codes: list[str] = []
    skipped_mappings: list[str] = []
    skipped_code_set: set[str] = set()

    for item in items:
        code = str(item.vendor_code or "").strip()
        if not code:
            continue
        supplier = suppliers_by_code.get(code)
        if not supplier:
            if code.lower() not in skipped_code_set:
                skipped_code_set.add(code.lower())
                skipped_supplier_codes.append(code)
            continue
        fields_payload = [field.model_dump() for field in item.fields] if item.fields else default_field_configs()
        try:
            fields_json = _serialize_prompt_fields(fields_payload)
        except ValueError as exc:
            skipped_mappings.append(f"{code}: {exc}")
            continue
        normalized[code] = {
            "vendor_code": supplier.code,
            "vendor_name": supplier.name,
            "prompt_body": strip_prompt_output_contract_lines(item.prompt_body),
            "fields_json": fields_json,
            "is_active": 1 if item.is_active else 0,
            "updated_at": str(item.updated_at or "").strip(),
        }

    return normalized, skipped_supplier_codes, skipped_mappings


def _normalize_import_rule_schemes(items: list[PromptRulesSchemeItem]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for item in items:
        name = _normalize_tag_name(item.name)
        if item.is_default and not _is_default_tag_name(name):
            raise ValueError("Only default can be marked as the default scheme in the import file")
        fields_payload = [field.model_dump() for field in item.fields] if item.fields else default_field_configs()
        normalized[name] = {
            "name": name,
            "preview_prompt_body": strip_prompt_output_contract_lines(item.preview_prompt_body),
            "preview_prompt_enabled": 1 if item.preview_prompt_enabled else 0,
            "prompt_body": strip_prompt_output_contract_lines(item.prompt_body),
            "fields_json": _serialize_prompt_fields(fields_payload),
            "export_settings_json": _serialize_export_settings(item.export_settings),
            "is_default": 1 if _is_default_tag_name(name) else 0,
            "updated_at": str(item.updated_at or "").strip(),
        }
    return normalized


def _normalize_import_suppliers(items: list[PromptRulesSupplierItem]) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for item in items:
        code = str(item.code or "").strip()
        name = str(item.name or "").strip()
        if not code or not name:
            continue
        normalized[code] = {
            "code": code,
            "name": name,
            "updated_at": str(item.updated_at or "").strip(),
        }
    return normalized


def _normalize_import_supplier_scheme_mappings(
    items: list[PromptRulesSupplierSchemeItem],
    available_schemes: set[str],
    available_supplier_codes: set[str] | None = None,
) -> tuple[dict[str, dict[str, str]], list[str], list[str]]:
    if available_supplier_codes is None:
        with db_cursor() as cur:
            supplier_codes = {
                str(row["code"] or "").strip()
                for row in cur.execute("SELECT code FROM suppliers").fetchall()
            }
    else:
        supplier_codes = {str(code or "").strip() for code in available_supplier_codes}
    mappings: dict[str, dict[str, str]] = {}
    skipped_supplier_codes: list[str] = []
    skipped_mappings: list[str] = []
    skipped_code_set: set[str] = set()

    for item in items:
        code = str(item.vendor_code or "").strip()
        if not code:
            continue
        if code not in supplier_codes:
            if code.lower() not in skipped_code_set:
                skipped_code_set.add(code.lower())
                skipped_supplier_codes.append(code)
            continue
        try:
            scheme_name = _normalize_tag_name(item.scheme_name)
        except ValueError as exc:
            skipped_mappings.append(f"{code}: {exc}")
            continue
        if scheme_name not in available_schemes:
            skipped_mappings.append(f"{code}: scheme does not exist: {scheme_name}")
            continue
        mappings[code] = {
            "vendor_code": code,
            "scheme_name": scheme_name,
            "updated_at": str(item.updated_at or "").strip(),
        }

    return mappings, skipped_supplier_codes, skipped_mappings


def _normalize_import_auto_archive_checks(
    items: list[PromptRulesAutoArchiveCheckItem],
) -> dict[tuple[str, str], dict[str, Any]]:
    normalized: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        code = str(item.vendor_code or "").strip()
        field_key = str(item.field_key or "").strip()
        if not code or not field_key:
            continue
        normalized[(code, field_key.lower())] = {
            "vendor_code": code,
            "field_key": field_key,
            "enabled": 1 if item.enabled else 0,
            "baseline_value": str(item.baseline_value or "").strip(),
            "tolerance_percent": str(item.tolerance_percent or "").strip(),
            "updated_at": str(item.updated_at or "").strip(),
        }
    return normalized


def _unique_scheme_name(base_name: str, existing_names: set[str], vendor_code: str) -> str:
    candidate = base_name.strip() or vendor_code
    suffix = 1
    while candidate in existing_names:
        candidate = f"{base_name} ({vendor_code})" if suffix == 1 else f"{base_name} ({vendor_code})#{suffix}"
        suffix += 1
    existing_names.add(candidate)
    return candidate


def _legacy_special_rules_to_schemes_and_mappings(
    items: list[PromptRulesSpecialDocumentRuleItem],
    existing_names: set[str],
    supplier_names: dict[str, str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]], list[str], list[str]]:
    if supplier_names is None:
        with db_cursor() as cur:
            suppliers_by_code = {
                str(row["code"] or "").strip(): str(row["name"] or "").strip()
                for row in cur.execute("SELECT code, name FROM suppliers").fetchall()
            }
    else:
        suppliers_by_code = {str(code or "").strip(): str(name or "").strip() for code, name in supplier_names.items()}
    schemes: dict[str, dict[str, Any]] = {}
    mappings: dict[str, dict[str, str]] = {}
    skipped_supplier_codes: list[str] = []
    skipped_mappings: list[str] = []
    skipped_code_set: set[str] = set()

    for item in items:
        code = str(item.vendor_code or "").strip()
        if not code or not item.is_active:
            continue
        supplier_name = suppliers_by_code.get(code)
        if not supplier_name:
            if code.lower() not in skipped_code_set:
                skipped_code_set.add(code.lower())
                skipped_supplier_codes.append(code)
            continue
        base_name = str(item.vendor_name or "").strip() or supplier_name or code
        scheme_name = _unique_scheme_name(base_name, existing_names, code)
        fields_payload = [field.model_dump() for field in item.fields] if item.fields else default_field_configs()
        try:
            fields_json = _serialize_prompt_fields(fields_payload)
        except ValueError as exc:
            skipped_mappings.append(f"{code}: {exc}")
            continue
        updated_at = str(item.updated_at or "").strip()
        schemes[scheme_name] = {
            "name": scheme_name,
            "preview_prompt_body": "",
            "preview_prompt_enabled": 0,
            "prompt_body": strip_prompt_output_contract_lines(item.prompt_body),
            "fields_json": fields_json,
            "export_settings_json": "",
            "is_default": 0,
            "updated_at": updated_at,
        }
        mappings[code] = {
            "vendor_code": code,
            "scheme_name": scheme_name,
            "updated_at": updated_at,
        }

    return schemes, mappings, skipped_supplier_codes, skipped_mappings


def _is_import_stale(import_updated_at: str, local_updated_at: str) -> bool:
    local_value = str(local_updated_at or "").strip()
    import_value = str(import_updated_at or "").strip()
    if not local_value:
        return False
    if not import_value:
        return True
    return import_value < local_value


def _stale_conflict(
    kind: str,
    key: str,
    import_updated_at: str,
    local_updated_at: str,
) -> PromptRulesStaleConflict:
    return PromptRulesStaleConflict(
        kind=kind,  # type: ignore[arg-type]
        key=key,
        import_updated_at=str(import_updated_at or ""),
        local_updated_at=str(local_updated_at or ""),
    )


def _resolve_prompt_for_supplier(vendor_code: str) -> tuple[str, str, list[dict[str, Any]]]:
    clean_code = str(vendor_code or "").strip()
    with db_cursor() as cur:
        mapped = (
            cur.execute(
                "SELECT scheme_name FROM supplier_scheme_map WHERE vendor_code = ?",
                (clean_code,),
            ).fetchone()
            if clean_code
            else None
        )
    mapped_scheme = str(mapped["scheme_name"]).strip() if mapped and mapped["scheme_name"] is not None else ""
    target_scheme = _normalize_tag_name(mapped_scheme) if mapped_scheme else DEFAULT_PROMPT_TAG

    row = _get_scheme_row(target_scheme)
    if not row and target_scheme != DEFAULT_PROMPT_TAG:
        row = _get_scheme_row(DEFAULT_PROMPT_TAG)
        target_scheme = DEFAULT_PROMPT_TAG
    if not row:
        return DEFAULT_PROMPT_TAG, DEFAULT_PROMPT_BODY, default_field_configs()
    fields = _deserialize_prompt_fields(str(row.get("fields_json") or ""))
    prompt_body = normalize_prompt_body(row.get("prompt_body"))
    return target_scheme, prompt_body, fields


def _prompt_tag_name_for_supplier(vendor_code: str) -> str:
    tag_name, _prompt_body, _fields = _resolve_prompt_for_supplier(vendor_code)
    return tag_name


def _value_field_keys(fields: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for field in fields:
        key = str(field.get("key") or "").strip()
        field_type = str(field.get("type") or "")
        if not key:
            continue
        if field_type == "value":
            dedupe_key = key.lower()
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                keys.append(key)
        elif field_type == "array":
            for child in field.get("children") or []:
                child_key = str(child.get("key") or "").strip()
                if not child_key or str(child.get("type") or "") != "value":
                    continue
                composite = f"{key}.{child_key}"
                dedupe_key = composite.lower()
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    keys.append(composite)
    return keys


def _supplier_auto_archive_checks(vendor_code: str) -> list[dict[str, Any]]:
    code = str(vendor_code or "").strip()
    if not code:
        return []
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT field_key, enabled, baseline_value, tolerance_percent
            FROM supplier_auto_archive_checks
            WHERE vendor_code = ?
            ORDER BY field_key COLLATE NOCASE ASC
            """,
            (code,),
        ).fetchall()
    return rows_to_dicts(rows)


def _auto_archive_fields_for_supplier(
    supplier_code: str,
    effective_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed_by_lower = {key.lower(): key for key in _value_field_keys(effective_fields)}
    fields: list[dict[str, Any]] = []
    for check in _supplier_auto_archive_checks(supplier_code):
        if not _to_bool(check.get("enabled")):
            continue
        field_key = str(check.get("field_key") or "").strip()
        canonical_key = allowed_by_lower.get(field_key.lower())
        if not canonical_key:
            continue
        fields.append({
            "key": canonical_key,
            "type": "value",
            "auto_archive_check": {
                "enabled": True,
                "baseline_value": str(check.get("baseline_value") or "").strip(),
                "tolerance_percent": str(check.get("tolerance_percent") or "").strip(),
            },
        })
    return fields


def _fixed_values_for_prompt_tag(tag_name: str) -> dict[str, Any]:
    tag = str(tag_name or "").strip()
    if not tag:
        return {}
    row = _get_scheme_row(tag)
    if not row and tag != DEFAULT_PROMPT_TAG:
        row = _get_scheme_row(DEFAULT_PROMPT_TAG)
    if not row:
        return {}
    fields = _deserialize_prompt_fields(str(row.get("fields_json") or ""))
    return fixed_values_for_fields(fields)


def _with_fixed_prompt_values(data: dict[str, Any]) -> dict[str, Any]:
    tag_name = str(data.get("prompt_tag") or "").strip()
    if not tag_name:
        vendor_code = str(data.get("vendor_code") or data.get("supplier_code") or data.get("Vendor Code") or "").strip()
        tag_name = _prompt_tag_name_for_supplier(vendor_code) if vendor_code else DEFAULT_PROMPT_TAG
    fixed_values = _fixed_values_for_prompt_tag(tag_name)
    if not fixed_values:
        return data
    return {**data, **fixed_values}


def _invoice_category_from_data(data: dict[str, Any]) -> str:
    return str(data.get("invoice_category") or data.get("Invoice Category") or "").strip()


def _sync_invoice_categories_for_tag(tag_name: str) -> None:
    tag = str(tag_name or "").strip()
    if not tag:
        return
    with db_cursor() as cur:
        rows = cur.execute("SELECT invoice_id, data_json FROM extracted_data").fetchall()
        timestamp = now_iso()
        for row in rows:
            try:
                data = json.loads(row["data_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or str(data.get("prompt_tag") or "").strip() != tag:
                continue
            next_data = _with_fixed_prompt_values(data)
            category = _invoice_category_from_data(next_data)
            cur.execute(
                """
                UPDATE extracted_data
                SET data_json = ?, updated_at = ?
                WHERE invoice_id = ?
                """,
                (json.dumps(next_data, ensure_ascii=False), timestamp, row["invoice_id"]),
            )
            cur.execute(
                """
                UPDATE invoices
                SET invoice_category = ?, updated_at = ?
                WHERE id = ?
                """,
                (category, timestamp, row["invoice_id"]),
            )


def _sync_extracted_prompt_tag_name(old_tag: str, new_tag: str) -> None:
    old_value = str(old_tag or "").strip()
    new_value = str(new_tag or "").strip()
    if not old_value or not new_value or old_value == new_value:
        return
    with db_cursor() as cur:
        rows = cur.execute("SELECT invoice_id, data_json FROM extracted_data").fetchall()
        timestamp = now_iso()
        for row in rows:
            try:
                data = json.loads(row["data_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or str(data.get("prompt_tag") or "").strip() != old_value:
                continue
            data["prompt_tag"] = new_value
            cur.execute(
                """
                UPDATE extracted_data
                SET data_json = ?, updated_at = ?
                WHERE invoice_id = ?
                """,
                (json.dumps(data, ensure_ascii=False), timestamp, row["invoice_id"]),
            )


def _suppliers_for_tag(tag_name: str) -> list[SupplierOut]:
    suppliers = supplier_matcher.list()
    mapping = _supplier_tag_map()
    tag = _normalize_tag_name(tag_name)
    if _is_default_tag_name(tag):
        return [
            SupplierOut(code=item.code, name=item.name)
            for item in suppliers
            if _is_default_tag_name(mapping.get(item.code, DEFAULT_PROMPT_TAG))
        ]
    return [
        SupplierOut(code=item.code, name=item.name)
        for item in suppliers
        if mapping.get(item.code) == tag
    ]


def _date_value_from_data(data: dict[str, Any]) -> str:
    for key in INVOICE_DATE_KEYS:
        value = data.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _with_normalized_invoice_date(data: dict[str, Any], invoice_date: str) -> dict[str, Any]:
    if not data:
        return data
    normalized = format_invoice_date(invoice_date or _date_value_from_data(data))
    if not normalized:
        return data
    next_data = dict(data)
    existing_key = next((key for key in INVOICE_DATE_KEYS if key in next_data), "invoice_date")
    next_data[existing_key] = normalized
    return next_data


def _invoice_out(row: dict[str, Any]) -> InvoiceOut:
    row = dict(row)
    row["invoice_date"] = format_invoice_date(row.get("invoice_date_iso") or row.get("invoice_date") or "")
    data = get_extracted_data(row["id"])
    data = _with_normalized_invoice_date(data, row["invoice_date"])
    return InvoiceOut(**row, extracted_data=data)


def _get_invoice(invoice_id: int) -> dict[str, Any]:
    with db_cursor() as cur:
        row = cur.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    invoice = row_to_dict(row)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice does not exist")
    return invoice


def _standard_columns_from_data(
    data: dict[str, Any],
    expense_type: str = "",
    validate_supplier: bool = False,
) -> dict[str, Any]:
    vendor_name = str(data.get("vendor_name") or data.get("Vendor Name") or "").strip()
    vendor_code = str(data.get("vendor_code") or data.get("supplier_code") or data.get("Vendor Code") or "").strip()
    if validate_supplier:
        supplier = supplier_matcher.resolve_exact(vendor_code, vendor_name)
        if supplier:
            vendor_code = supplier.code
            vendor_name = supplier.name
    po_number = str(data.get("PO_number") or data.get("po_number") or data.get("PO") or "").strip()
    invoice_number = str(data.get("invoice_number") or data.get("Invoice Number") or "").strip()
    raw_invoice_date = _date_value_from_data(data)
    invoice_date_iso = parse_invoice_date(raw_invoice_date)
    invoice_date = format_invoice_date(invoice_date_iso or raw_invoice_date)
    total_amount = amount_to_float(data.get("total_amount", data.get("Amount", 0)))
    invoice_category = _invoice_category_from_data(data)
    return {
        "vendor_code": vendor_code,
        "vendor_name": vendor_name,
        "po_number": po_number,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "invoice_date_iso": invoice_date_iso,
        "total_amount": total_amount,
        "expense_type": expense_type,
        "invoice_category": invoice_category,
    }


def _expense_type_from_supplier_history(cur: sqlite3.Cursor, vendor_code: str, invoice_id: int) -> str:
    clean_code = str(vendor_code or "").strip()
    if not clean_code:
        return ""
    rows = cur.execute(
        """
        SELECT expense_type
        FROM supplier_expense_type_history
        WHERE vendor_code = ?
            AND invoice_id <> ?
            AND TRIM(COALESCE(expense_type, '')) <> ''
        ORDER BY selected_at DESC, invoice_id DESC
        LIMIT 3
        """,
        (clean_code, invoice_id),
    ).fetchall()
    recent = [str(row["expense_type"] or "").strip() for row in rows if str(row["expense_type"] or "").strip()]
    if not recent:
        return ""

    counts: dict[str, int] = {}
    for value in recent:
        counts[value] = counts.get(value, 0) + 1
    top_count = max(counts.values())
    winners = [value for value, count in counts.items() if count == top_count]
    if len(winners) != 1:
        return ""
    if top_count == len(recent) or (len(recent) == 3 and top_count >= 2):
        return winners[0]
    return ""


def _sync_supplier_expense_type_history(
    cur: sqlite3.Cursor,
    invoice_id: int,
    vendor_code: str,
    expense_type: str,
) -> None:
    clean_code = str(vendor_code or "").strip()
    clean_type = str(expense_type or "").strip()
    if not clean_code or not clean_type:
        cur.execute("DELETE FROM supplier_expense_type_history WHERE invoice_id = ?", (invoice_id,))
        return

    timestamp = now_iso()
    cur.execute(
        """
        INSERT INTO supplier_expense_type_history(invoice_id, vendor_code, expense_type, source, selected_at)
        VALUES (?, ?, ?, 'manual', ?)
        ON CONFLICT(invoice_id) DO UPDATE SET
            vendor_code = excluded.vendor_code,
            expense_type = excluded.expense_type,
            source = excluded.source,
            selected_at = excluded.selected_at
        """,
        (invoice_id, clean_code, clean_type, timestamp),
    )


def _save_extracted(
    invoice_id: int,
    data: dict[str, Any],
    expense_type: str,
    validate_supplier: bool = False,
    record_expense_history: bool = False,
    allow_expense_autofill: bool = True,
) -> None:
    data = _with_fixed_prompt_values(data)
    requested_expense_type = str(expense_type or "").strip()
    columns = _standard_columns_from_data(data, requested_expense_type, validate_supplier)
    if validate_supplier:
        data = dict(data)
        data["vendor_code"] = columns["vendor_code"]
        data["vendor_name"] = columns["vendor_name"]
    data = _with_normalized_invoice_date(data, columns["invoice_date"])
    with db_cursor() as cur:
        if not requested_expense_type and allow_expense_autofill:
            columns["expense_type"] = _expense_type_from_supplier_history(cur, columns["vendor_code"], invoice_id)
        upsert_extracted_data(cur, invoice_id, data)
        cur.execute(
            """
            UPDATE invoices
            SET vendor_code = ?, vendor_name = ?, po_number = ?, invoice_number = ?,
                invoice_date = ?, invoice_date_iso = ?, total_amount = ?,
                expense_type = ?, invoice_category = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                columns["vendor_code"],
                columns["vendor_name"],
                columns["po_number"],
                columns["invoice_number"],
                columns["invoice_date"],
                columns["invoice_date_iso"],
                columns["total_amount"],
                columns["expense_type"],
                columns["invoice_category"],
                now_iso(),
                invoice_id,
            ),
        )
        if record_expense_history:
            _sync_supplier_expense_type_history(cur, invoice_id, columns["vendor_code"], columns["expense_type"])


def _mark_job_item(job_id: str, invoice_id: int, status: str, error: str = "", result: dict[str, Any] | None = None) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE recognition_job_items
            SET status = ?, error_message = ?, result_json = ?, updated_at = ?
            WHERE job_id = ? AND invoice_id = ?
            """,
            (
                status,
                error,
                json.dumps(result or {}, ensure_ascii=False),
                now_iso(),
                job_id,
                invoice_id,
            ),
        )


def _auto_archive_job_summary(job_id: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT result_json
            FROM recognition_job_items
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchall()
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            result = json.loads(row["result_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(result, dict) or not _to_bool(result.get("auto_archived")):
            continue
        code = str(result.get("vendor_code") or "").strip()
        name = str(result.get("vendor_name") or "").strip()
        key = code or name
        if not key:
            continue
        item = summary.setdefault(key, {"vendor_code": code, "vendor_name": name, "count": 0})
        item["count"] += 1
        if code and not item.get("vendor_code"):
            item["vendor_code"] = code
        if name and not item.get("vendor_name"):
            item["vendor_name"] = name
    return sorted(summary.values(), key=lambda item: (str(item.get("vendor_name") or ""), str(item.get("vendor_code") or "")))


def _increment_job(job_id: str, succeeded: bool) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE recognition_jobs
            SET processed = processed + 1,
                succeeded = succeeded + ?,
                failed_count = failed_count + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (1 if succeeded else 0, 0 if succeeded else 1, now_iso(), job_id),
        )


def _mark_recognition_failed(job_id: str, invoice_id: int, message: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE invoices
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (message, now_iso(), invoice_id),
        )
    _mark_job_item(job_id, invoice_id, "failed", message)
    _increment_job(job_id, False)


def _supplier_confidence(data: dict[str, Any]) -> float:
    raw = data.get("vendor_match_confidence", 0)
    try:
        confidence = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return confidence


def _is_vendor_matched(data: dict[str, Any]) -> bool:
    value = str(data.get("vendor_matched", "False")).strip().lower()
    return value in {"true", "1", "yes", "\u662f"}


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "\u662f"}


def _manual_confirmation_required_fields(data: dict[str, Any]) -> list[str]:
    raw = data.get(MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY)
    if not isinstance(raw, list):
        return []
    fields: list[str] = []
    seen: set[str] = set()
    for item in raw:
        field = str(item or "").strip()
        if field and field not in seen:
            seen.add(field)
            fields.append(field)
    return fields


def _assert_no_unresolved_llm_fields(data: dict[str, Any]) -> None:
    fields = _manual_confirmation_required_fields(data)
    if not fields and not _to_bool(data.get(MANUAL_CONFIRMATION_REQUIRED_KEY)):
        return
    detail = "The following fields were marked by response validation as requiring manual confirmation. Fix them first: " + ", ".join(fields or ["unknown field"])
    raise HTTPException(status_code=400, detail=detail)


def _document_type_value(data: dict[str, Any]) -> str:
    value = str(data.get("document_type") or "").strip()
    if not value:
        return "unknown"
    normalized = value.lower().replace("-", "_").replace(" ", "_")
    normalized = "".join(ch for ch in normalized if ch.isalnum() or ch == "_")
    return normalized or "unknown"


def _document_type_label(data: dict[str, Any]) -> str:
    doc_type = _document_type_value(data)
    labels = {
        "invoice": "invoice",
        "statement": "statement",
        "purchase_order": "PO",
        "po": "PO",
        "remittance": "remittance",
        "receipt": "receipt",
        "credit_memo": "credit memo",
        "special_document": "Special Document",
        "other": "other",
        "unknown": "unknown",
    }
    return labels.get(doc_type, doc_type or "unknown")


def _is_document_invoice(data: dict[str, Any]) -> bool:
    if "document_is_invoice" in data and str(data.get("document_is_invoice") or "").strip() != "":
        return _to_bool(data.get("document_is_invoice"))
    if "Is_Invoice" in data and str(data.get("Is_Invoice") or "").strip() != "":
        return _to_bool(data.get("Is_Invoice"))
    return _document_type_value(data) == "invoice"


def _is_supplier_confirmed(data: dict[str, Any], threshold: float) -> bool:
    if _to_bool(data.get("supplier_confirmed")):
        return True
    code = str(data.get("vendor_code") or data.get("supplier_code") or data.get("Vendor Code") or "").strip()
    name = str(data.get("vendor_name") or data.get("Vendor Name") or "").strip()
    return bool(code and name and _is_vendor_matched(data) and _supplier_confidence(data) >= threshold)


def _candidate_list(data: dict[str, Any]) -> list[str]:
    raw = data.get("supplier_raw_candidates")
    values: list[Any]
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        values = [raw]
    else:
        values = []
    cleaned = [str(item or "").strip() for item in values]
    return [item for item in cleaned if item][:3]


def _top_option_text(data: dict[str, Any]) -> str:
    raw = data.get("supplier_top_options")
    if not isinstance(raw, list):
        return ""
    items: list[str] = []
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        score = item.get("score", 0)
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = 0.0
        if code or name:
            items.append(f"{code}/{name}({confidence:.2f})")
    return " | ".join(items)


def _log_supplier_preview(invoice_id: int, file_path: str, data: dict[str, Any], threshold: float) -> None:
    filename = Path(file_path).name
    candidates = _candidate_list(data)
    candidates_text = " | ".join(candidates) if candidates else "(none)"
    top_options = _top_option_text(data) or "(none)"
    doc_type = _document_type_label(data)
    is_invoice_doc = _is_document_invoice(data)
    code = str(data.get("vendor_code") or "").strip()
    name = str(data.get("vendor_name") or "").strip()
    matched = _is_vendor_matched(data)
    confidence = _supplier_confidence(data)
    method = str(data.get("vendor_match_method") or "").strip() or "none"
    confirmed = _to_bool(data.get("supplier_confirmed"))
    warning = str(data.get("supplier_warning") or "").strip()

    logger.info(
        "[SupplierPreview] invoice_id=%s file=%s supplier candidates 1-3=%s",
        invoice_id,
        filename,
        candidates_text,
    )
    logger.info(
        "[SupplierPreview] invoice_id=%s file=%s top match=%s",
        invoice_id,
        filename,
        top_options,
    )
    logger.info(
        "[SupplierPreview] invoice_id=%s file=%s document_type=%s is_invoice=%s",
        invoice_id,
        filename,
        doc_type,
        is_invoice_doc,
    )
    logger.info(
        "[SupplierPreview] invoice_id=%s file=%s match result matched=%s confirmed=%s threshold=%.2f confidence=%.2f method=%s supplier=%s/%s",
        invoice_id,
        filename,
        matched,
        confirmed,
        threshold,
        confidence,
        method,
        code,
        name,
    )
    if warning:
        logger.warning(
            "[SupplierPreview] invoice_id=%s file=%s warning=%s",
            invoice_id,
            filename,
            warning,
        )


def _supplier_preview(
    file_path: str,
    invoice_id: int | None = None,
    on_retry: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    threshold = supplier_confidence_threshold()
    data = extract_supplier_preview(
        file_path,
        supplier_matcher,
        special_document_rules=_special_document_preview_rules(),
        on_retry=on_retry,
        trace_metadata={
            "invoice_id": invoice_id,
            "file_name": Path(file_path).name,
        },
    )
    data = dict(data)
    is_invoice_doc = _is_document_invoice(data)
    data["document_is_invoice"] = "True" if is_invoice_doc else "False"
    data["document_type"] = _document_type_value(data)
    data["Is_Invoice"] = "True" if is_invoice_doc else "False"

    confirmed = _is_supplier_confirmed(data, threshold) if is_invoice_doc else False
    data["supplier_confirmed"] = "True" if confirmed else "False"
    data["supplier_needs_confirmation"] = "False" if confirmed else "True"
    data["supplier_stage"] = "ready" if confirmed else "needs_confirmation"

    if not confirmed:
        warning = str(data.get("supplier_warning") or "").strip()
        if not is_invoice_doc:
            doc_type = _document_type_label(data)
            reason = str(data.get("document_type_reason") or "").strip()
            warning = f"Document type was recognized as {doc_type}; it is not an invoice. Please confirm manually"
            if reason:
                warning = f"{warning} (reason: {reason[:100]})"
        elif not warning:
            confidence = _supplier_confidence(data)
            if _is_vendor_matched(data) and confidence > 0:
                warning = (
                    f"Supplier match confidence {(confidence * 100):.0f}% "
                    f"is below threshold {(threshold * 100):.0f}%. Please confirm manually"
                )
            else:
                warning = "No reliable supplier was recognized. Please confirm manually"
        data["supplier_warning"] = warning
    else:
        data["supplier_warning"] = ""
        code = str(data.get("vendor_code") or data.get("supplier_code") or "").strip()
        if code:
            data["prompt_tag"] = _prompt_tag_name_for_supplier(code)
    return data


def _mark_supplier_retry_progress(invoice_id: int, attempt: int, max_attempts: int) -> None:
    """Surface auto-retry progress on the invoice while it stays in the scanning state.

    Called from the supplier-preview retry loop (background worker thread). It only
    merges progress fields into the existing extracted_data so the pending row keeps
    its spinner and can show "Retry N/M"; the final result later overwrites these.
    """
    try:
        data = get_extracted_data(invoice_id) or {}
        data["supplier_stage"] = "scanning"
        data["supplier_retry_attempt"] = attempt
        data["supplier_retry_max"] = max_attempts
        data["supplier_warning"] = f"Supplier preview retry in progress ({attempt}/{max_attempts})..."
        with db_cursor() as cur:
            upsert_extracted_data(cur, invoice_id, data)
    except Exception:  # pragma: no cover - progress reporting must never break extraction
        logger.exception("[SupplierPreview] invoice_id=%s failed to write retry progress", invoice_id)


def _prepare_supplier_on_upload(
    invoice_id: int,
    file_path: str,
    expense_type: str = "",
    on_retry: Callable[[int, int], None] | None = None,
) -> bool:
    threshold = supplier_confidence_threshold()
    succeeded = True
    try:
        data = _supplier_preview(file_path, invoice_id=invoice_id, on_retry=on_retry)
    except Exception as exc:
        succeeded = False
        warning = str(exc).strip() or "Supplier preview failed. Please confirm manually"
        data = {
            "Is_Invoice": "False",
            "document_type": "unknown",
            "document_is_invoice": "False",
            "document_type_reason": "",
            "vendor_name": "",
            "vendor_code": "",
            "vendor_matched": "False",
            "vendor_match_confidence": 0.0,
            "supplier_confirmed": "False",
            "supplier_needs_confirmation": "True",
            "supplier_stage": "needs_confirmation",
            "parse_mode": "supplier_preview_failed",
            "parse_excerpt": "",
            "supplier_warning": warning,
        }
        logger.exception(
            "[SupplierPreview] invoice_id=%s file=%s recognition failed: %s",
            invoice_id,
            Path(file_path).name,
            warning,
        )
    else:
        _log_supplier_preview(invoice_id, file_path, data, threshold)
    _save_extracted(invoice_id, data, expense_type)
    return succeeded


def _mark_upload_preview_item(job_id: str, invoice_id: int, status: str, error: str = "") -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE upload_preview_job_items
            SET status = ?, error_message = ?, updated_at = ?
            WHERE job_id = ? AND invoice_id = ?
            """,
            (status, error or None, now_iso(), job_id, invoice_id),
        )


def _increment_upload_preview_job(job_id: str, succeeded: bool) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE upload_preview_jobs
            SET processed = processed + 1,
                succeeded = succeeded + ?,
                failed_count = failed_count + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (1 if succeeded else 0, 0 if succeeded else 1, now_iso(), job_id),
        )


def _mark_upload_preview_failed(job_id: str, invoice_id: int, message: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE invoices
            SET error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (message, now_iso(), invoice_id),
        )
    _mark_upload_preview_item(job_id, invoice_id, "failed", message)
    _increment_upload_preview_job(job_id, False)


def _process_upload_preview_invoice(job_id: str, invoice_id: int) -> None:
    try:
        invoice = _get_invoice(invoice_id)
        _mark_upload_preview_item(job_id, invoice_id, "running")
        succeeded = _prepare_supplier_on_upload(
            invoice_id,
            invoice["file_path"],
            invoice.get("expense_type") or "",
            on_retry=lambda attempt, max_attempts: _mark_supplier_retry_progress(
                invoice_id, attempt, max_attempts
            ),
        )
        if succeeded:
            _mark_upload_preview_item(job_id, invoice_id, "succeeded")
            _increment_upload_preview_job(job_id, True)
        else:
            _mark_upload_preview_item(job_id, invoice_id, "failed", "Supplier preview failed. Please confirm manually")
            _increment_upload_preview_job(job_id, False)
    except Exception as exc:  # pragma: no cover - defensive guard for worker threads
        logger.exception("[SupplierPreview] invoice_id=%s background preview error", invoice_id)
        _mark_upload_preview_failed(job_id, invoice_id, f"Supplier preview error: {exc}")


def run_upload_preview_job(job_id: str, invoice_ids: list[int]) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE upload_preview_jobs SET status = ?, updated_at = ? WHERE id = ?",
            ("running", now_iso(), job_id),
        )

    worker_count = min(supplier_preview_worker_count(), max(1, len(invoice_ids)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_process_upload_preview_invoice, job_id, invoice_id) for invoice_id in invoice_ids]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                logger.exception("[SupplierPreview] job_id=%s worker thread terminated unexpectedly", job_id)

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT processed, total FROM upload_preview_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        status = "completed" if row and row["processed"] >= row["total"] else "failed"
        cur.execute(
            "UPDATE upload_preview_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), job_id),
        )


def get_upload_preview_job(job_id: str) -> UploadPreviewJobOut:
    with db_cursor() as cur:
        row = cur.execute("SELECT * FROM upload_preview_jobs WHERE id = ?", (job_id,)).fetchone()
        item_rows = cur.execute(
            """
            SELECT invoice_id
            FROM upload_preview_job_items
            WHERE job_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (job_id,),
        ).fetchall()
    job = row_to_dict(row)
    if not job:
        raise HTTPException(status_code=404, detail="Upload preview job does not exist")
    invoices = [_invoice_out(_get_invoice(int(item["invoice_id"]))) for item in item_rows]
    return UploadPreviewJobOut(**job, invoices=invoices)


def _assert_supplier_ready(
    invoice_id: int,
    filename: str = "",
    expense_type: str = "",
    file_path: str = "",
) -> None:
    threshold = supplier_confidence_threshold()
    data = get_extracted_data(invoice_id)
    if not data and file_path:
        _prepare_supplier_on_upload(invoice_id, file_path, expense_type)
        data = get_extracted_data(invoice_id)
    if not data:
        raise HTTPException(status_code=400, detail=f"Invoice {filename or invoice_id} has not completed supplier recognition. Confirm the supplier first.")
    if not _is_document_invoice(data):
        doc_type = _document_type_label(data)
        raise HTTPException(
            status_code=400,
            detail=f"Invoice {filename or invoice_id} document type is {doc_type}; it is not an invoice. Confirm it manually first",
        )
    if not _is_supplier_confirmed(data, threshold):
        raise HTTPException(
            status_code=400,
            detail=f"Invoice {filename or invoice_id} supplier is not confirmed. Confirm the supplier in Pending before recognition.",
        )
    # Ensure code and name are normalized to supplier.txt before entering LLM stage.
    try:
        _save_extracted(invoice_id, data, expense_type, validate_supplier=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _try_auto_archive_after_recognition(
    invoice_id: int,
    data: dict[str, Any],
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    next_data = dict(data)
    next_data.pop(AUTO_ARCHIVE_FAILED_FIELDS_KEY, None)
    evaluation = evaluate_auto_archive_checks(fields, next_data)
    if not evaluation.has_checks:
        return {"auto_archive_checked": False, "auto_archived": False}

    if not evaluation.passed:
        next_data[AUTO_ARCHIVE_FAILED_FIELDS_KEY] = evaluation.failed_fields
        with db_cursor() as cur:
            upsert_extracted_data(cur, invoice_id, next_data)
        return {
            "auto_archive_checked": True,
            "auto_archived": False,
            "auto_archive_failed_fields": evaluation.failed_fields,
        }

    if _manual_confirmation_required_fields(next_data) or _to_bool(next_data.get(MANUAL_CONFIRMATION_REQUIRED_KEY)):
        with db_cursor() as cur:
            upsert_extracted_data(cur, invoice_id, next_data)
        return {
            "auto_archive_checked": True,
            "auto_archived": False,
            "auto_archive_failed_fields": [],
        }

    confirmed = _confirm_invoice_record(invoice_id, record_hitl=False, auto_archived=True)
    return {
        "auto_archive_checked": True,
        "auto_archived": True,
        "vendor_code": confirmed.vendor_code,
        "vendor_name": confirmed.vendor_name,
    }


def _process_recognition_invoice(job_id: str, invoice_id: int) -> None:
    try:
        invoice = _get_invoice(invoice_id)
        _mark_job_item(job_id, invoice_id, "running")
        _assert_supplier_ready(
            invoice_id,
            invoice["original_filename"],
            invoice.get("expense_type") or "",
            invoice.get("file_path") or "",
        )
        seeded = get_extracted_data(invoice_id)
        # Lock vendor fields to the already confirmed supplier before LLM stage.
        supplier_code = str(seeded.get("vendor_code") or seeded.get("supplier_code") or "").strip()
        supplier_name = str(seeded.get("vendor_name") or "").strip()
        tag_name, tag_prompt_body, tag_fields = _resolve_prompt_for_supplier(supplier_code)
        special_rule = (
            _special_document_rule_for_supplier(supplier_code)
            if _to_bool(seeded.get("special_document_matched"))
            else None
        )
        if special_rule:
            special_row, special_prompt_body, special_fields = special_rule
            prompt_body = _combine_recognition_prompt(tag_name, tag_prompt_body, special_prompt_body)
            field_configs = special_fields
        else:
            special_row = None
            prompt_body = tag_prompt_body
            field_configs = tag_fields
        few_shot_examples = get_few_shot_examples(supplier_code) if supplier_code else []
        data = extract_invoice_with_config(
            invoice["file_path"],
            prompt_body,
            field_configs,
            confirmed_vendor_name=supplier_name,
            confirmed_vendor_code=supplier_code,
            trace_metadata={
                "invoice_id": invoice_id,
                "file_name": invoice["original_filename"],
                "prompt_tag": tag_name,
                "vendor_code": supplier_code,
                "special_document_vendor_code": str(special_row.get("vendor_code") or "") if special_row else "",
                "few_shot_count": len(few_shot_examples),
            },
            few_shot_examples=few_shot_examples,
        )
        logger.info(
            "[Recognition] invoice_id=%s file=%s using supplier=%s/%s tag=%s",
            invoice_id,
            invoice["original_filename"],
            supplier_code,
            supplier_name,
            tag_name,
        )
        data["vendor_code"] = supplier_code
        data["vendor_name"] = supplier_name
        data["supplier_confirmed"] = "True"
        data["supplier_needs_confirmation"] = "False"
        data["supplier_stage"] = "ready"
        data["prompt_tag"] = tag_name
        if special_row:
            data["Is_Invoice"] = "True"
            data["document_is_invoice"] = "True"
            data["document_type"] = str(seeded.get("document_type") or "special_document").strip() or "special_document"
            data["special_document_matched"] = "True"
            data["special_document_vendor_code"] = str(special_row.get("vendor_code") or "")
            data["special_document_vendor_name"] = str(special_row.get("vendor_name") or "")
            data["special_document_reason"] = str(seeded.get("special_document_reason") or "")
        else:
            data = _with_fixed_prompt_values(data)

        columns = _standard_columns_from_data(data, invoice.get("expense_type") or "")
        data = _with_normalized_invoice_date(data, columns["invoice_date"])

        if not is_invoice(data):
            status = "failed"
            error = "Not recognized as a valid invoice. Please confirm manually."
            succeeded = False
        else:
            status = "recognized"
            error = ""
            succeeded = True

        if hitl_review_enabled():
            data = attach_model_snapshot(data)

        with db_cursor() as cur:
            upsert_extracted_data(cur, invoice_id, data)
            cur.execute(
                """
                UPDATE invoices
                SET status = ?, recognized_at = ?, updated_at = ?, error_message = ?,
                    vendor_code = ?, vendor_name = ?, po_number = ?, invoice_number = ?,
                    invoice_date = ?, invoice_date_iso = ?, total_amount = ?, invoice_category = ?
                WHERE id = ?
                """,
                (
                    status,
                    now_iso(),
                    now_iso(),
                    error or None,
                    columns["vendor_code"],
                    columns["vendor_name"],
                    columns["po_number"],
                    columns["invoice_number"],
                    columns["invoice_date"],
                    columns["invoice_date_iso"],
                    columns["total_amount"],
                    columns["invoice_category"],
                    invoice_id,
                ),
            )
        job_result = dict(data)
        if succeeded:
            auto_archive_fields = _auto_archive_fields_for_supplier(supplier_code, field_configs)
            auto_archive_result = _try_auto_archive_after_recognition(invoice_id, data, auto_archive_fields)
            job_result.update(auto_archive_result)
        _mark_job_item(job_id, invoice_id, "succeeded" if succeeded else "failed", error, job_result)
        _increment_job(job_id, succeeded)
    except (ExtractionError, SupplierPreviewError, HTTPException, OSError, ValueError) as exc:
        _mark_recognition_failed(job_id, invoice_id, str(exc))
    except Exception as exc:  # pragma: no cover - defensive guard for worker threads
        logger.exception("[Recognition] invoice_id=%s processing error", invoice_id)
        _mark_recognition_failed(job_id, invoice_id, f"recognition job error: {exc}")


def run_recognition_job(job_id: str, invoice_ids: list[int]) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE recognition_jobs SET status = ?, updated_at = ? WHERE id = ?",
            ("running", now_iso(), job_id),
        )

    worker_count = min(MAX_RECOGNITION_WORKERS, max(1, len(invoice_ids)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_process_recognition_invoice, job_id, invoice_id) for invoice_id in invoice_ids]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                logger.exception("[Recognition] job_id=%s worker thread terminated unexpectedly", job_id)

    with db_cursor() as cur:
        row = cur.execute(
            "SELECT processed, total FROM recognition_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        status = "completed" if row and row["processed"] >= row["total"] else "failed"
        cur.execute(
            "UPDATE recognition_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), job_id),
        )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    q: str = Query(default=""),
    limit: int = Query(default=5000, ge=1, le=5000),
) -> list[SupplierOut]:
    supplier_matcher.reload()
    return [SupplierOut(code=item.code, name=item.name) for item in supplier_matcher.search(q, limit)]


@app.get("/api/suppliers/auto-archive-active", response_model=list[str])
def list_auto_archive_active_suppliers() -> list[str]:
    with db_cursor() as cur:
        rows = cur.execute(
            "SELECT DISTINCT vendor_code FROM supplier_auto_archive_checks WHERE enabled = 1"
        ).fetchall()
    return [str(row["vendor_code"]) for row in rows]


@app.post("/api/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierCreate) -> SupplierOut:
    code = payload.code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(status_code=422, detail="code and name cannot both be blank")
    timestamp = now_iso()
    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO suppliers(code, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (code, name, timestamp, timestamp),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Supplier code already exists: {code}") from exc
    supplier_matcher.reload()
    return SupplierOut(code=code, name=name)


@app.delete("/api/suppliers/{code}")
def delete_supplier(code: str) -> dict[str, Any]:
    clean_code = str(code or "").strip()
    with db_cursor() as cur:
        existing = cur.execute("SELECT code FROM suppliers WHERE code = ?", (clean_code,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f"Supplier not found: {clean_code}")
        cur.execute("DELETE FROM supplier_expense_type_history WHERE vendor_code = ?", (clean_code,))
        cur.execute("DELETE FROM llm_calls WHERE supplier_code = ?", (clean_code,))
        cur.execute("DELETE FROM suppliers WHERE code = ?", (clean_code,))
    supplier_matcher.reload()
    return {"code": clean_code, "deleted": True}


@app.get("/api/suppliers/{code}/auto-archive-checks", response_model=SupplierAutoArchiveConfigOut)
def get_supplier_auto_archive_checks(code: str) -> SupplierAutoArchiveConfigOut:
    clean_code = str(code or "").strip()
    with db_cursor() as cur:
        supplier = cur.execute("SELECT code, name FROM suppliers WHERE code = ?", (clean_code,)).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail=f"Supplier not found: {clean_code}")
    scheme_name, _prompt_body, fields = _resolve_prompt_for_supplier(clean_code)
    checks = [
        SupplierAutoArchiveCheck(
            field_key=str(row.get("field_key") or "").strip(),
            enabled=_to_bool(row.get("enabled")),
            baseline_value=str(row.get("baseline_value") or "").strip(),
            tolerance_percent=str(row.get("tolerance_percent") or "").strip(),
        )
        for row in _supplier_auto_archive_checks(clean_code)
        if str(row.get("field_key") or "").strip().lower() in {key.lower() for key in _value_field_keys(fields)}
    ]
    return SupplierAutoArchiveConfigOut(
        vendor_code=str(supplier["code"] or ""),
        vendor_name=str(supplier["name"] or ""),
        scheme_name=scheme_name,
        available_fields=_value_field_keys(fields),
        checks=checks,
    )


@app.put("/api/suppliers/{code}/auto-archive-checks", response_model=SupplierAutoArchiveConfigOut)
def update_supplier_auto_archive_checks(
    code: str,
    payload: SupplierAutoArchiveConfigUpdate,
) -> SupplierAutoArchiveConfigOut:
    clean_code = str(code or "").strip()
    with db_cursor() as cur:
        supplier = cur.execute("SELECT code FROM suppliers WHERE code = ?", (clean_code,)).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail=f"Supplier not found: {clean_code}")

    _scheme_name, _prompt_body, fields = _resolve_prompt_for_supplier(clean_code)
    available_by_lower = {key.lower(): key for key in _value_field_keys(fields)}
    normalized: dict[str, SupplierAutoArchiveCheck] = {}
    for item in payload.checks:
        field_key = str(item.field_key or "").strip()
        canonical_key = available_by_lower.get(field_key.lower())
        if not canonical_key:
            raise HTTPException(status_code=400, detail=f"Auto-archive field must be a value field in the current scheme: {field_key}")
        baseline = str(item.baseline_value or "").strip()
        tolerance = str(item.tolerance_percent or "").strip()
        if item.enabled and (not baseline or not tolerance):
            raise HTTPException(status_code=400, detail=f"Please enter {canonical_key} baseline and tolerance")
        if not item.enabled:
            continue
        normalized[canonical_key.lower()] = SupplierAutoArchiveCheck(
            field_key=canonical_key,
            enabled=True,
            baseline_value=baseline,
            tolerance_percent=tolerance,
        )

    timestamp = now_iso()
    with db_cursor() as cur:
        cur.execute("DELETE FROM supplier_auto_archive_checks WHERE vendor_code = ?", (clean_code,))
        for item in normalized.values():
            cur.execute(
                """
                INSERT INTO supplier_auto_archive_checks(
                    vendor_code, field_key, enabled, baseline_value, tolerance_percent, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_code,
                    item.field_key,
                    1 if item.enabled else 0,
                    item.baseline_value,
                    item.tolerance_percent,
                    timestamp,
                ),
            )
    return get_supplier_auto_archive_checks(clean_code)


@app.get("/api/schemes", response_model=list[SchemeOut])
def list_schemes() -> list[SchemeOut]:
    _ensure_default_scheme()
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT name, preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json, is_default, updated_at
            FROM schemes
            ORDER BY is_default DESC, name COLLATE NOCASE ASC
            """
        ).fetchall()
    counts = _scheme_supplier_counts()
    return [_scheme_row_to_out(row, counts.get(str(row["name"]), 0)) for row in rows_to_dicts(rows)]


@app.post("/api/schemes", response_model=SchemeOut, status_code=201)
def create_scheme(payload: SchemeCreate) -> SchemeOut:
    _ensure_default_scheme()
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Scheme name cannot be blank")
    if _is_default_tag_name(name):
        raise HTTPException(status_code=409, detail="default already exists")
    parent = payload.inherit_from.strip() or DEFAULT_PROMPT_TAG
    with db_cursor() as cur:
        parent_row = cur.execute(
            """
            SELECT preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json
            FROM schemes
            WHERE name = ?
            """,
            (parent,),
        ).fetchone()
        if not parent_row:
            raise HTTPException(status_code=404, detail=f"Parent scheme not found: {parent}")
        timestamp = now_iso()
        try:
            cur.execute(
                """
                INSERT INTO schemes(name, preview_prompt_body, preview_prompt_enabled,
                                    prompt_body, fields_json, export_settings_json,
                                    is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    name,
                    parent_row["preview_prompt_body"],
                    parent_row["preview_prompt_enabled"],
                    parent_row["prompt_body"],
                    parent_row["fields_json"],
                    parent_row["export_settings_json"],
                    timestamp,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"Scheme name already exists: {name}") from exc
        row = cur.execute(
            """
            SELECT name, preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json, is_default, updated_at
            FROM schemes
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
    return _scheme_row_to_out(dict(row), 0)


@app.put("/api/schemes/{name}", response_model=SchemeOut)
def update_scheme(name: str, payload: SchemeUpdate) -> SchemeOut:
    _ensure_default_scheme()
    with db_cursor() as cur:
        existing = cur.execute(
            """
            SELECT name, preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json, is_default
            FROM schemes
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f"Scheme not found: {name}")
        new_name = (payload.name or "").strip() or name
        if new_name != name and bool(int(existing["is_default"] or 0)):
            raise HTTPException(status_code=400, detail="The default scheme cannot be renamed")
        preview_prompt_body = (
            payload.preview_prompt_body
            if payload.preview_prompt_body is not None
            else existing["preview_prompt_body"]
        )
        if payload.preview_prompt_enabled is None:
            preview_prompt_enabled = int(existing["preview_prompt_enabled"] or 0)
        else:
            preview_prompt_enabled = 1 if payload.preview_prompt_enabled else 0
        prompt_body = payload.prompt_body if payload.prompt_body is not None else existing["prompt_body"]
        fields_json = (
            _serialize_prompt_fields([field.model_dump() for field in payload.fields])
            if payload.fields is not None
            else existing["fields_json"]
        )
        export_settings_json = (
            _serialize_export_settings(payload.export_settings)
            if payload.export_settings is not None
            else existing["export_settings_json"]
        )
        timestamp = now_iso()
        try:
            cur.execute(
                """
                UPDATE schemes
                SET name = ?, preview_prompt_body = ?, preview_prompt_enabled = ?,
                    prompt_body = ?, fields_json = ?, export_settings_json = ?, updated_at = ?
                WHERE name = ?
                """,
                (
                    new_name,
                    preview_prompt_body,
                    preview_prompt_enabled,
                    prompt_body,
                    fields_json,
                    export_settings_json,
                    timestamp,
                    name,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"Scheme name already exists: {new_name}") from exc
        row = cur.execute(
            """
            SELECT name, preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json, is_default, updated_at
            FROM schemes
            WHERE name = ?
            """,
            (new_name,),
        ).fetchone()
    counts = _scheme_supplier_counts()
    return _scheme_row_to_out(dict(row), counts.get(new_name, 0))


@app.delete("/api/schemes/{name}")
def delete_scheme(name: str) -> dict[str, Any]:
    _ensure_default_scheme()
    with db_cursor() as cur:
        row = cur.execute("SELECT is_default FROM schemes WHERE name = ?", (name,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Scheme not found: {name}")
        if bool(int(row["is_default"] or 0)):
            raise HTTPException(status_code=400, detail="The default scheme cannot be deleted")
        cur.execute("DELETE FROM schemes WHERE name = ?", (name,))
    return {"name": name, "deleted": True}


@app.get("/api/supplier-scheme-map", response_model=dict[str, str])
def list_supplier_scheme_map() -> dict[str, str]:
    with db_cursor() as cur:
        rows = cur.execute("SELECT vendor_code, scheme_name FROM supplier_scheme_map").fetchall()
    return {str(row["vendor_code"]): str(row["scheme_name"]) for row in rows}


@app.put("/api/supplier-scheme-map/{code}")
def set_supplier_scheme(code: str, payload: SupplierSchemeAssign) -> dict[str, str]:
    clean_code = str(code or "").strip()
    scheme_name = payload.scheme_name.strip()
    with db_cursor() as cur:
        supplier = cur.execute("SELECT code FROM suppliers WHERE code = ?", (clean_code,)).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail=f"Supplier not found: {clean_code}")
        scheme = cur.execute("SELECT name FROM schemes WHERE name = ?", (scheme_name,)).fetchone()
        if not scheme:
            raise HTTPException(status_code=404, detail=f"Scheme not found: {scheme_name}")
        cur.execute(
            """
            INSERT INTO supplier_scheme_map(vendor_code, scheme_name, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(vendor_code) DO UPDATE SET
                scheme_name = excluded.scheme_name,
                updated_at = excluded.updated_at
            """,
            (clean_code, scheme_name, now_iso()),
        )
    return {"vendor_code": clean_code, "scheme_name": scheme_name}


@app.delete("/api/supplier-scheme-map/{code}")
def clear_supplier_scheme(code: str) -> dict[str, Any]:
    clean_code = str(code or "").strip()
    with db_cursor() as cur:
        cur.execute("DELETE FROM supplier_scheme_map WHERE vendor_code = ?", (clean_code,))
    return {"vendor_code": clean_code, "cleared": True}


@app.get("/api/prompt-rules/export", response_model=PromptRulesExportOut)
def export_prompt_rules() -> PromptRulesExportOut:
    _ensure_default_scheme()
    with db_cursor() as cur:
        supplier_rows = cur.execute(
            """
            SELECT code, name, updated_at
            FROM suppliers
            ORDER BY code COLLATE NOCASE ASC
            """
        ).fetchall()
        scheme_rows = cur.execute(
            """
            SELECT name, preview_prompt_body, preview_prompt_enabled,
                   prompt_body, fields_json, export_settings_json, is_default, updated_at
            FROM schemes
            ORDER BY is_default DESC, name COLLATE NOCASE ASC
            """
        ).fetchall()
        mapping_rows = cur.execute(
            """
            SELECT m.vendor_code, m.scheme_name, m.updated_at
            FROM supplier_scheme_map m
            INNER JOIN schemes s ON s.name = m.scheme_name
            ORDER BY m.vendor_code COLLATE NOCASE ASC
            """
        ).fetchall()
        auto_archive_rows = cur.execute(
            """
            SELECT a.vendor_code, a.field_key, a.enabled, a.baseline_value,
                   a.tolerance_percent, a.updated_at
            FROM supplier_auto_archive_checks a
            INNER JOIN suppliers s ON s.code = a.vendor_code
            ORDER BY a.vendor_code COLLATE NOCASE ASC, a.field_key COLLATE NOCASE ASC
            """
        ).fetchall()

    return PromptRulesExportOut(
        exported_at=now_iso(),
        suppliers=[
            PromptRulesSupplierItem(
                code=str(row["code"] or "").strip(),
                name=str(row["name"] or "").strip(),
                updated_at=str(row["updated_at"] or ""),
            )
            for row in supplier_rows
            if str(row["code"] or "").strip() and str(row["name"] or "").strip()
        ],
        schemes=[_prompt_rules_scheme_item(row) for row in rows_to_dicts(scheme_rows)],
        supplier_scheme_map=[
            PromptRulesSupplierSchemeItem(
                vendor_code=str(row["vendor_code"] or "").strip(),
                scheme_name=str(row["scheme_name"] or "").strip(),
                updated_at=str(row["updated_at"] or ""),
            )
            for row in mapping_rows
            if str(row["vendor_code"] or "").strip() and str(row["scheme_name"] or "").strip()
        ],
        auto_archive_checks=[
            PromptRulesAutoArchiveCheckItem(
                vendor_code=str(row["vendor_code"] or "").strip(),
                field_key=str(row["field_key"] or "").strip(),
                enabled=_to_bool(row["enabled"]),
                baseline_value=str(row["baseline_value"] or "").strip(),
                tolerance_percent=str(row["tolerance_percent"] or "").strip(),
                updated_at=str(row["updated_at"] or ""),
            )
            for row in auto_archive_rows
            if str(row["vendor_code"] or "").strip() and str(row["field_key"] or "").strip()
        ],
        tags=[],
        supplier_tag_map=[],
        special_document_rules=[],
    )


@app.post("/api/prompt-rules/import", response_model=PromptRulesImportOut)
def import_prompt_rules(request: PromptRulesImportRequest) -> PromptRulesImportOut:
    _ensure_default_scheme()
    try:
        scheme_items = list(request.payload.schemes)
        scheme_items.extend(
            PromptRulesSchemeItem(
                name=item.tag,
                prompt_body=item.prompt_body,
                fields=item.fields,
                export_settings=item.export_settings,
                is_default=item.is_default,
                updated_at=item.updated_at,
            )
            for item in request.payload.tags
        )
        incoming_schemes = _normalize_import_rule_schemes(scheme_items)
        incoming_suppliers = _normalize_import_suppliers(list(request.payload.suppliers))
        incoming_auto_archive_checks = _normalize_import_auto_archive_checks(list(request.payload.auto_archive_checks))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db_cursor() as cur:
        current_supplier_rows = cur.execute("SELECT code, name, updated_at FROM suppliers").fetchall()
        current_supplier_codes = {str(row["code"] or "").strip() for row in current_supplier_rows}
        current_supplier_names = {
            str(row["code"] or "").strip(): str(row["name"] or "").strip()
            for row in current_supplier_rows
        }
        current_supplier_updated_at = {
            str(row["code"] or "").strip(): str(row["updated_at"] or "")
            for row in current_supplier_rows
        }
        current_rows = cur.execute("SELECT name, updated_at FROM schemes").fetchall()
        current_schemes = {str(row["name"] or "").strip() for row in current_rows}
        current_scheme_updated_at = {
            str(row["name"] or "").strip(): str(row["updated_at"] or "")
            for row in current_rows
        }
        available_schemes = set(incoming_schemes) | current_schemes | {DEFAULT_PROMPT_TAG}

        timestamp = now_iso()
        suppliers_created = 0
        suppliers_updated = 0
        tags_created = 0
        tags_updated = 0
        supplier_mappings_removed = 0
        special_document_rules_created = 0
        special_document_rules_updated = 0
        auto_archive_checks_imported = 0
        stale_conflicts: list[PromptRulesStaleConflict] = []
        stale_conflicts_skipped = 0

        for code, item in incoming_suppliers.items():
            exists = code in current_supplier_codes
            import_updated_at = str(item.get("updated_at") or "").strip()
            if exists and _is_import_stale(import_updated_at, current_supplier_updated_at.get(code, "")):
                conflict = _stale_conflict(
                    "supplier",
                    code,
                    import_updated_at,
                    current_supplier_updated_at.get(code, ""),
                )
                stale_conflicts.append(conflict)
                if not request.override_stale:
                    stale_conflicts_skipped += 1
                    continue
            if exists:
                suppliers_updated += 1
            else:
                suppliers_created += 1
            effective_updated_at = import_updated_at or timestamp
            cur.execute(
                """
                INSERT INTO suppliers(code, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (code, item["name"], effective_updated_at, effective_updated_at),
            )
            current_supplier_codes.add(code)
            current_supplier_names[code] = item["name"]

        mapping_items = list(request.payload.supplier_scheme_map)
        mapping_items.extend(
            PromptRulesSupplierSchemeItem(
                vendor_code=item.vendor_code,
                scheme_name=item.tag,
                updated_at=item.updated_at,
            )
            for item in request.payload.supplier_tag_map
        )
        special_schemes, special_mappings, skipped_special_codes, skipped_special_mappings = (
            _legacy_special_rules_to_schemes_and_mappings(
                request.payload.special_document_rules,
                set(available_schemes),
                current_supplier_names,
            )
        )
        incoming_schemes.update(special_schemes)
        available_schemes.update(special_schemes)
        mapping_items.extend(
            PromptRulesSupplierSchemeItem(
                vendor_code=item["vendor_code"],
                scheme_name=item["scheme_name"],
                updated_at=item.get("updated_at", ""),
            )
            for item in special_mappings.values()
        )

        mappings, skipped_supplier_codes, skipped_mappings = _normalize_import_supplier_scheme_mappings(
            mapping_items,
            available_schemes,
            current_supplier_codes,
        )
        skipped_supplier_codes.extend(code for code in skipped_special_codes if code not in skipped_supplier_codes)
        skipped_mappings.extend(skipped_special_mappings)

        existing_mapping_rows = cur.execute("SELECT vendor_code, updated_at FROM supplier_scheme_map").fetchall()
        existing_mapping_updated_at = {
            str(row["vendor_code"] or "").strip(): str(row["updated_at"] or "")
            for row in existing_mapping_rows
        }

        for scheme_name, item in incoming_schemes.items():
            exists = scheme_name in current_schemes
            import_updated_at = str(item.get("updated_at") or "").strip()
            if exists and _is_import_stale(import_updated_at, current_scheme_updated_at.get(scheme_name, "")):
                conflict = _stale_conflict(
                    "scheme",
                    scheme_name,
                    import_updated_at,
                    current_scheme_updated_at.get(scheme_name, ""),
                )
                stale_conflicts.append(conflict)
                if not request.override_stale:
                    stale_conflicts_skipped += 1
                    continue
            if exists:
                tags_updated += 1
            else:
                tags_created += 1
            effective_updated_at = import_updated_at or timestamp
            cur.execute(
                """
                INSERT INTO schemes(
                    name, preview_prompt_body, preview_prompt_enabled,
                    prompt_body, fields_json, export_settings_json,
                    is_default, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    preview_prompt_body = excluded.preview_prompt_body,
                    preview_prompt_enabled = excluded.preview_prompt_enabled,
                    prompt_body = excluded.prompt_body,
                    fields_json = excluded.fields_json,
                    export_settings_json = excluded.export_settings_json,
                    is_default = excluded.is_default,
                    updated_at = excluded.updated_at
                """,
                (
                    scheme_name,
                    item["preview_prompt_body"],
                    item["preview_prompt_enabled"],
                    item["prompt_body"],
                    item["fields_json"],
                    item["export_settings_json"],
                    item["is_default"],
                    effective_updated_at,
                    effective_updated_at,
                ),
            )

        cur.execute(
            """
            UPDATE schemes
            SET is_default = CASE WHEN lower(name) = ? THEN 1 ELSE 0 END
            """,
            (DEFAULT_PROMPT_TAG,),
        )

        supplier_mappings_imported = 0
        for code, item in mappings.items():
            scheme_name = item["scheme_name"]
            import_updated_at = str(item.get("updated_at") or "").strip()
            if code in existing_mapping_updated_at and _is_import_stale(
                import_updated_at,
                existing_mapping_updated_at.get(code, ""),
            ):
                conflict = _stale_conflict(
                    "supplier_scheme_mapping",
                    code,
                    import_updated_at,
                    existing_mapping_updated_at.get(code, ""),
                )
                stale_conflicts.append(conflict)
                if not request.override_stale:
                    stale_conflicts_skipped += 1
                    continue
            effective_updated_at = import_updated_at or timestamp
            if _is_default_tag_name(scheme_name):
                deleted = cur.execute("DELETE FROM supplier_scheme_map WHERE vendor_code = ?", (code,)).rowcount
                supplier_mappings_removed += deleted
                supplier_mappings_imported += 1
                continue
            cur.execute(
                """
                INSERT INTO supplier_scheme_map(vendor_code, scheme_name, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(vendor_code) DO UPDATE SET
                    scheme_name = excluded.scheme_name,
                    updated_at = excluded.updated_at
                """,
                (code, scheme_name, effective_updated_at),
            )
            supplier_mappings_imported += 1

        existing_auto_rows = cur.execute(
            "SELECT vendor_code, field_key, updated_at FROM supplier_auto_archive_checks"
        ).fetchall()
        existing_auto_updated_at = {
            (str(row["vendor_code"] or "").strip(), str(row["field_key"] or "").strip().lower()): str(
                row["updated_at"] or ""
            )
            for row in existing_auto_rows
        }

        skipped_auto_codes: set[str] = {code.lower() for code in skipped_supplier_codes}
        for (code, field_lower), item in incoming_auto_archive_checks.items():
            if code not in current_supplier_codes:
                if code.lower() not in skipped_auto_codes:
                    skipped_auto_codes.add(code.lower())
                    skipped_supplier_codes.append(code)
                continue

            mapping_row = cur.execute(
                "SELECT scheme_name FROM supplier_scheme_map WHERE vendor_code = ?",
                (code,),
            ).fetchone()
            scheme_name = str(mapping_row["scheme_name"] or "").strip() if mapping_row else DEFAULT_PROMPT_TAG
            scheme_row = cur.execute(
                "SELECT fields_json FROM schemes WHERE name = ?",
                (scheme_name,),
            ).fetchone()
            if not scheme_row and not _is_default_tag_name(scheme_name):
                scheme_row = cur.execute(
                    "SELECT fields_json FROM schemes WHERE name = ?",
                    (DEFAULT_PROMPT_TAG,),
                ).fetchone()
            available_by_lower = {
                key.lower(): key
                for key in _value_field_keys(
                    _deserialize_prompt_fields(str(scheme_row["fields_json"] or "")) if scheme_row else []
                )
            }
            canonical_key = available_by_lower.get(field_lower)
            if not canonical_key:
                skipped_mappings.append(f"{code}: Auto-archive field is not a value field in the current scheme: {item['field_key']}")
                continue
            if item["enabled"] and (not item["baseline_value"] or not item["tolerance_percent"]):
                skipped_mappings.append(f"{code}: Auto-archive field is missing baseline or tolerance: {canonical_key}")
                continue

            import_updated_at = str(item.get("updated_at") or "").strip()
            existing_key = (code, canonical_key.lower())
            if existing_key in existing_auto_updated_at and _is_import_stale(
                import_updated_at,
                existing_auto_updated_at.get(existing_key, ""),
            ):
                conflict = _stale_conflict(
                    "auto_archive_check",
                    f"{code}:{canonical_key}",
                    import_updated_at,
                    existing_auto_updated_at.get(existing_key, ""),
                )
                stale_conflicts.append(conflict)
                if not request.override_stale:
                    stale_conflicts_skipped += 1
                    continue

            effective_updated_at = import_updated_at or timestamp
            cur.execute(
                """
                INSERT INTO supplier_auto_archive_checks(
                    vendor_code, field_key, enabled, baseline_value, tolerance_percent, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(vendor_code, field_key) DO UPDATE SET
                    enabled = excluded.enabled,
                    baseline_value = excluded.baseline_value,
                    tolerance_percent = excluded.tolerance_percent,
                    updated_at = excluded.updated_at
                """,
                (
                    code,
                    canonical_key,
                    item["enabled"],
                    item["baseline_value"],
                    item["tolerance_percent"],
                    effective_updated_at,
                ),
            )
            auto_archive_checks_imported += 1

    supplier_matcher.reload()
    return PromptRulesImportOut(
        suppliers_created=suppliers_created,
        suppliers_updated=suppliers_updated,
        tags_created=tags_created,
        tags_updated=tags_updated,
        supplier_mappings_imported=supplier_mappings_imported,
        supplier_mappings_removed=supplier_mappings_removed,
        auto_archive_checks_imported=auto_archive_checks_imported,
        special_document_rules_created=special_document_rules_created,
        special_document_rules_updated=special_document_rules_updated,
        skipped_supplier_codes=skipped_supplier_codes,
        skipped_mappings=skipped_mappings,
        stale_conflicts=stale_conflicts,
        stale_conflicts_skipped=stale_conflicts_skipped,
    )


@app.post("/api/system/select-directory", response_model=DirectorySelectionOut)
def select_directory() -> DirectorySelectionOut:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to open folder picker: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(title="Choose Export Destination Folder", mustexist=True)
    finally:
        root.destroy()

    if not selected:
        return DirectorySelectionOut(canceled=True)
    return DirectorySelectionOut(path=str(Path(selected).expanduser().resolve()))


@app.post("/api/invoices/upload", response_model=UploadPreviewJobOut)
async def upload_invoices(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> UploadPreviewJobOut:
    if not files:
        raise HTTPException(status_code=400, detail="Please select invoices")
    for upload in files:
        original_name = upload.filename or "invoice"
        safe_name = safe_filename(original_name)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {original_name}")

    created_ids: list[int] = []
    for upload in files:
        original_name = upload.filename or "invoice"
        safe_name = safe_filename(original_name)
        stored_filename = f"{uuid.uuid4().hex}_{safe_name}"
        target = PENDING_DIR / stored_filename
        with target.open("wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)
        mime_type = mime_type_for_path(target)
        created_at = now_iso()
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO invoices(
                    original_filename, stored_filename, file_path, mime_type, status,
                    uploaded_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (original_name, stored_filename, str(target), mime_type, created_at, created_at),
            )
            invoice_id = cur.lastrowid
            upsert_extracted_data(
                cur,
                int(invoice_id),
                {
                    "document_type": "unknown",
                    "document_is_invoice": "",
                    "Is_Invoice": "",
                    "vendor_name": "",
                    "vendor_code": "",
                    "vendor_matched": "False",
                    "vendor_match_confidence": 0.0,
                    "supplier_confirmed": "False",
                    "supplier_needs_confirmation": "True",
                    "supplier_stage": "scanning",
                    "supplier_warning": "Supplier preview in progress...",
                },
            )
        created_ids.append(int(invoice_id))

    job_id = uuid.uuid4().hex
    created_at = now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO upload_preview_jobs(id, status, total, processed, succeeded, failed_count, created_at, updated_at)
            VALUES (?, 'queued', ?, 0, 0, 0, ?, ?)
            """,
            (job_id, len(created_ids), created_at, created_at),
        )
        for invoice_id in created_ids:
            cur.execute(
                """
                INSERT INTO upload_preview_job_items(job_id, invoice_id, status, created_at, updated_at)
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (job_id, invoice_id, created_at, created_at),
            )
    background_tasks.add_task(run_upload_preview_job, job_id, created_ids)
    return get_upload_preview_job(job_id)


@app.get("/api/upload-preview/active", response_model=UploadPreviewJobOut | None)
def get_active_upload_preview() -> UploadPreviewJobOut | None:
    """Latest active supplier-preview job so the UI can resume its scanning state after a remount."""
    with db_cursor() as cur:
        row = cur.execute(
            """
            SELECT id FROM upload_preview_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return None
    return get_upload_preview_job(str(row["id"]))


@app.get("/api/upload-preview/jobs/{job_id}", response_model=UploadPreviewJobOut)
def read_upload_preview_job(job_id: str) -> UploadPreviewJobOut:
    return get_upload_preview_job(job_id)


@app.post("/api/invoices/{invoice_id}/supplier-preview/retry", response_model=InvoiceOut)
def retry_supplier_preview(invoice_id: int) -> InvoiceOut:
    invoice = _get_invoice(invoice_id)
    if invoice["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending invoices can retry supplier preview")
    _prepare_supplier_on_upload(
        invoice_id,
        invoice.get("file_path") or "",
        invoice.get("expense_type") or "",
    )
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE invoices
            SET error_message = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), invoice_id),
        )
    return _invoice_out(_get_invoice(invoice_id))


@app.get("/api/invoices", response_model=list[InvoiceOut])
def list_invoices(
    status: str | None = Query(default=None),
    export_status: str | None = Query(default=None),
    supplier: str | None = Query(default=None),
    expense_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    vendor_code: str | None = Query(default=None),
    vendor_name: str | None = Query(default=None),
    po_number: str | None = Query(default=None),
    invoice_number: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    day: str | None = Query(default=None),
    confirmed_from: str | None = Query(default=None),
    confirmed_to: str | None = Query(default=None),
    amount_min: float | None = Query(default=None),
    amount_max: float | None = Query(default=None),
) -> list[InvoiceOut]:
    params: list[Any] = []
    clauses: list[str] = []
    if status == "review":
        clauses.append("status IN ('recognized', 'failed')")
    elif status:
        clauses.append("status = ?")
        params.append(status)
    if export_status == "unexported":
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM export_items
                WHERE export_items.invoice_id = invoices.id
            )
            """
        )
    elif export_status == "exported":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM export_items
                WHERE export_items.invoice_id = invoices.id
            )
            """
        )
    if supplier:
        clauses.append("(vendor_name LIKE ? OR vendor_code LIKE ?)")
        needle = f"%{supplier}%"
        params.extend([needle, needle])
    if expense_type:
        if expense_type == "__empty__":
            clauses.append("COALESCE(expense_type, '') = ''")
        else:
            clauses.append("expense_type = ?")
            params.append(expense_type)
    if category:
        clauses.append("invoice_category = ?")
        params.append(category)
    if vendor_code:
        clauses.append("vendor_code LIKE ?")
        params.append(f"%{vendor_code}%")
    if vendor_name:
        clauses.append("vendor_name LIKE ?")
        params.append(f"%{vendor_name}%")
    if po_number:
        clauses.append("po_number LIKE ?")
        params.append(f"%{po_number}%")
    if invoice_number:
        clauses.append("invoice_number LIKE ?")
        params.append(f"%{invoice_number}%")
    if day:
        clauses.append("invoice_date_iso = ?")
        params.append(day)
    if date_from:
        clauses.append("invoice_date_iso >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("invoice_date_iso <= ?")
        params.append(date_to)
    if confirmed_from:
        clauses.append("confirmed_at >= ?")
        params.append(confirmed_from)
    if confirmed_to:
        clauses.append("confirmed_at <= ?")
        params.append(confirmed_to)
    if amount_min is not None:
        clauses.append("total_amount >= ?")
        params.append(amount_min)
    if amount_max is not None:
        clauses.append("total_amount <= ?")
        params.append(amount_max)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ORDER BY uploaded_at DESC, id DESC"
    if status == "review":
        order = "ORDER BY CASE status WHEN 'recognized' THEN 0 ELSE 1 END, recognized_at DESC, id DESC"
    if status == "confirmed":
        order = "ORDER BY confirmed_at DESC, id DESC"
    with db_cursor() as cur:
        rows = cur.execute(
            f"""
            SELECT invoices.*,
                (
                    SELECT export_items.archive_number
                    FROM export_items
                    WHERE export_items.invoice_id = invoices.id
                    ORDER BY export_items.created_at DESC, export_items.id DESC
                    LIMIT 1
                ) AS archive_number,
                (
                    SELECT export_items.exported_filename
                    FROM export_items
                    WHERE export_items.invoice_id = invoices.id
                    ORDER BY export_items.created_at DESC, export_items.id DESC
                    LIMIT 1
                ) AS exported_filename,
                (
                    SELECT export_items.exported_path
                    FROM export_items
                    WHERE export_items.invoice_id = invoices.id
                    ORDER BY export_items.created_at DESC, export_items.id DESC
                    LIMIT 1
                ) AS exported_path,
                (
                    SELECT export_items.batch_id
                    FROM export_items
                    WHERE export_items.invoice_id = invoices.id
                    ORDER BY export_items.created_at DESC, export_items.id DESC
                    LIMIT 1
                ) AS export_batch_id,
                (
                    SELECT export_batches.created_at
                    FROM export_items
                    JOIN export_batches ON export_items.batch_id = export_batches.id
                    WHERE export_items.invoice_id = invoices.id
                    ORDER BY export_items.created_at DESC, export_items.id DESC
                    LIMIT 1
                ) AS exported_at
            FROM invoices
            {where}
            {order}
            """,
            params,
        ).fetchall()
    return [_invoice_out(row) for row in rows_to_dicts(rows)]


@app.get("/api/invoice-categories", response_model=list[str])
def list_invoice_categories() -> list[str]:
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT DISTINCT invoice_category
            FROM invoices
            WHERE TRIM(COALESCE(invoice_category, '')) <> ''
            ORDER BY invoice_category COLLATE NOCASE
            """
        ).fetchall()
    return [str(row["invoice_category"]) for row in rows]


@app.get("/api/export-stats", response_model=ExportStatsOut)
def export_stats() -> ExportStatsOut:
    with db_cursor() as cur:
        confirmed_count = cur.execute(
            "SELECT COUNT(*) AS count FROM invoices WHERE status = 'confirmed'"
        ).fetchone()["count"]
        exported_count = cur.execute(
            """
            SELECT COUNT(DISTINCT invoices.id) AS count
            FROM invoices
            WHERE status = 'confirmed'
                AND EXISTS (
                    SELECT 1 FROM export_items
                    WHERE export_items.invoice_id = invoices.id
                )
            """
        ).fetchone()["count"]
    return ExportStatsOut(
        confirmed_count=int(confirmed_count or 0),
        exported_count=int(exported_count or 0),
        unexported_count=max(int(confirmed_count or 0) - int(exported_count or 0), 0),
    )


@app.get("/api/invoices/{invoice_id}/file")
def get_invoice_file(invoice_id: int) -> FileResponse:
    invoice = _get_invoice(invoice_id)
    path = Path(invoice["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File does not exist")
    return FileResponse(
        path,
        media_type=invoice["mime_type"],
        filename=invoice["original_filename"],
        content_disposition_type="inline",
    )


def _active_recognition_invoice_ids() -> list[int]:
    """Invoice ids currently queued/running in an active recognition job (server truth)."""
    with db_cursor() as cur:
        rows = cur.execute(
            """
            SELECT DISTINCT item.invoice_id
            FROM recognition_job_items item
            JOIN recognition_jobs job ON job.id = item.job_id
            WHERE job.status IN ('queued', 'running')
              AND item.status IN ('queued', 'running')
            """
        ).fetchall()
    return [int(row["invoice_id"]) for row in rows]


@app.post("/api/recognition/jobs", response_model=RecognitionJobOut)
def start_recognition_job(request: RecognitionRequest, background_tasks: BackgroundTasks) -> RecognitionJobOut:
    invoice_ids = list(dict.fromkeys(request.invoice_ids))
    if not invoice_ids:
        raise HTTPException(status_code=400, detail="Please select invoices")

    busy_ids = set(_active_recognition_invoice_ids())
    if any(invoice_id in busy_ids for invoice_id in invoice_ids):
        raise HTTPException(status_code=409, detail="Some invoices are being recognized. Wait for the current recognition to finish and try again.")

    for invoice_id in invoice_ids:
        invoice = _get_invoice(invoice_id)
        if invoice["status"] == "confirmed":
            raise HTTPException(status_code=400, detail=f"Invoice {invoice['original_filename']} has already been archived and cannot be recognized again")
        _assert_supplier_ready(
            invoice_id,
            invoice["original_filename"],
            invoice.get("expense_type") or "",
            invoice.get("file_path") or "",
        )

    job_id = uuid.uuid4().hex
    created_at = now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO recognition_jobs(id, status, total, processed, succeeded, failed_count, created_at, updated_at)
            VALUES (?, 'queued', ?, 0, 0, 0, ?, ?)
            """,
            (job_id, len(invoice_ids), created_at, created_at),
        )
        for invoice_id in invoice_ids:
            cur.execute(
                """
                INSERT INTO recognition_job_items(job_id, invoice_id, status, created_at, updated_at)
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (job_id, invoice_id, created_at, created_at),
            )
    background_tasks.add_task(run_recognition_job, job_id, invoice_ids)
    return get_recognition_job(job_id)


@app.get("/api/recognition/active", response_model=ActiveRecognitionOut)
def get_active_recognition() -> ActiveRecognitionOut:
    """Active recognition state so the UI can restore locks/spinners after a remount or reload."""
    with db_cursor() as cur:
        job_row = cur.execute(
            """
            SELECT * FROM recognition_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
    job = None
    if job_row:
        job_dict = row_to_dict(job_row)
        job_dict["auto_archived_by_supplier"] = _auto_archive_job_summary(job_dict["id"])
        job = RecognitionJobOut(**job_dict)
    return ActiveRecognitionOut(job=job, invoice_ids=_active_recognition_invoice_ids())


@app.get("/api/recognition/jobs/{job_id}", response_model=RecognitionJobOut)
def get_recognition_job(job_id: str) -> RecognitionJobOut:
    with db_cursor() as cur:
        row = cur.execute("SELECT * FROM recognition_jobs WHERE id = ?", (job_id,)).fetchone()
    job = row_to_dict(row)
    if not job:
        raise HTTPException(status_code=404, detail="Job does not exist")
    job["auto_archived_by_supplier"] = _auto_archive_job_summary(job_id)
    return RecognitionJobOut(**job)


@app.post("/api/invoices/{invoice_id}/retry", response_model=RecognitionJobOut)
def retry_invoice(invoice_id: int, background_tasks: BackgroundTasks) -> RecognitionJobOut:
    invoice = _get_invoice(invoice_id)
    if invoice["status"] == "confirmed":
        raise HTTPException(status_code=400, detail="Confirmed and archived invoices cannot be retried")
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE invoices
            SET status = 'pending',
                error_message = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), invoice_id),
        )
    return start_recognition_job(RecognitionRequest(invoice_ids=[invoice_id]), background_tasks)


@app.delete("/api/invoices/{invoice_id}", response_model=DeleteInvoiceOut)
def delete_review_invoice(invoice_id: int) -> DeleteInvoiceOut:
    invoice = _get_invoice(invoice_id)
    if invoice["status"] not in {"pending", "recognized", "failed"}:
        raise HTTPException(status_code=400, detail="Only pending or review records can be deleted")

    deleted_file = False
    path = Path(invoice["file_path"])
    try:
        if path.exists():
            if not path.is_file():
                raise HTTPException(status_code=400, detail=f"Target is not a file; deletion stopped: {path}")
            path.unlink()
            deleted_file = True
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"File deletion failed: {exc}") from exc

    with db_cursor() as cur:
        cur.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    return DeleteInvoiceOut(id=invoice_id, deleted_file=deleted_file)


@app.patch("/api/invoices/{invoice_id}/extracted-data", response_model=InvoiceOut)
def update_extracted_data(invoice_id: int, request: UpdateExtractedDataRequest) -> InvoiceOut:
    _get_invoice(invoice_id)
    _save_extracted(
        invoice_id,
        request.extracted_data,
        request.expense_type,
        record_expense_history=True,
        allow_expense_autofill=False,
    )
    return _invoice_out(_get_invoice(invoice_id))


@app.post("/api/invoices/{invoice_id}/supplier-confirm", response_model=InvoiceOut)
def confirm_pending_supplier(invoice_id: int, request: SupplierConfirmRequest) -> InvoiceOut:
    invoice = _get_invoice(invoice_id)
    if invoice["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending invoices can confirm suppliers")

    code = str(request.vendor_code or "").strip()
    name = str(request.vendor_name or "").strip()
    if not code and not name:
        raise HTTPException(status_code=400, detail="Please enter vendor code or vendor name")

    supplier_matcher.reload()
    try:
        supplier = supplier_matcher.resolve_exact(code, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not supplier:
        raise HTTPException(status_code=400, detail="No supplier matched. Check the input.")

    data = get_extracted_data(invoice_id)
    next_data = dict(data)
    next_data["vendor_code"] = supplier.code
    next_data["vendor_name"] = supplier.name
    next_data["vendor_matched"] = "True"
    next_data["vendor_match_confidence"] = 1.0
    next_data["vendor_match_method"] = "manual"
    next_data["vendor_match_query"] = name or code
    next_data["prompt_tag"] = _prompt_tag_name_for_supplier(supplier.code)
    is_invoice_doc = _is_document_invoice(next_data)
    next_data["Is_Invoice"] = "True" if is_invoice_doc else "False"
    next_data["document_is_invoice"] = "True" if is_invoice_doc else "False"
    if is_invoice_doc:
        next_data["supplier_confirmed"] = "True"
        next_data["supplier_needs_confirmation"] = "False"
        next_data["supplier_stage"] = "ready"
        next_data["supplier_warning"] = ""
    else:
        doc_type = _document_type_label(next_data)
        next_data["supplier_confirmed"] = "False"
        next_data["supplier_needs_confirmation"] = "True"
        next_data["supplier_stage"] = "needs_confirmation"
        next_data["supplier_warning"] = f"Document type was recognized as {doc_type}; it is not an invoice. Please confirm manually"

    _save_extracted(invoice_id, next_data, invoice.get("expense_type") or "", validate_supplier=True)
    logger.info(
        "[SupplierConfirm] invoice_id=%s file=%s manual confirmation supplier=%s/%s is_invoice=%s doc_type=%s",
        invoice_id,
        invoice["original_filename"],
        supplier.code,
        supplier.name,
        _is_document_invoice(next_data),
        _document_type_label(next_data),
    )
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE invoices
            SET error_message = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), invoice_id),
        )
    return _invoice_out(_get_invoice(invoice_id))


@app.post("/api/invoices/{invoice_id}/manual-entry", response_model=InvoiceOut)
def save_manual_entry(invoice_id: int, request: UpdateExtractedDataRequest) -> InvoiceOut:
    invoice = _get_invoice(invoice_id)
    if invoice["status"] == "confirmed":
        raise HTTPException(status_code=400, detail="Confirmed and archived invoices cannot be manually entered")
    if invoice["status"] not in {"failed", "recognized"}:
        raise HTTPException(status_code=400, detail="Only review records can be manually entered")

    try:
        _save_extracted(
            invoice_id,
            request.extracted_data,
            request.expense_type,
            validate_supplier=True,
            record_expense_history=True,
            allow_expense_autofill=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    timestamp = now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE invoices
            SET status = 'recognized',
                recognized_at = COALESCE(recognized_at, ?),
                error_message = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, invoice_id),
        )
    return _invoice_out(_get_invoice(invoice_id))


def _confirm_invoice_record(
    invoice_id: int,
    *,
    record_hitl: bool,
    auto_archived: bool = False,
) -> InvoiceOut:
    invoice = _get_invoice(invoice_id)
    if invoice["status"] == "confirmed":
        return _invoice_out(invoice)
    if invoice["status"] != "recognized":
        raise HTTPException(status_code=400, detail="Only successfully recognized invoices can be confirmed")

    source = Path(invoice["file_path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="File does not exist")
    data = get_extracted_data(invoice_id)
    if not any(key in data for key in ("vendor_code", "supplier_code", "Vendor Code")) and invoice.get("vendor_code"):
        data["vendor_code"] = invoice["vendor_code"]
    if not any(key in data for key in ("vendor_name", "Vendor Name")) and invoice.get("vendor_name"):
        data["vendor_name"] = invoice["vendor_name"]
    _assert_no_unresolved_llm_fields(data)
    try:
        _save_extracted(
            invoice_id,
            data,
            invoice.get("expense_type") or "",
            validate_supplier=True,
            record_expense_history=True,
            allow_expense_autofill=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invoice = _get_invoice(invoice_id)

    target = CONFIRMED_DIR / invoice["stored_filename"]
    if target.exists():
        target = CONFIRMED_DIR / f"{uuid.uuid4().hex}_{invoice['stored_filename']}"
    shutil.move(str(source), str(target))
    confirmed_at = now_iso()
    with db_cursor() as cur:
        if record_hitl and hitl_review_enabled():
            model_output = model_snapshot_from_data(data)
            if model_output:
                record_review_confirmation(
                    cur,
                    invoice=invoice,
                    model_output=model_output,
                    confirmed_output=data,
                    source_status=str(invoice.get("status") or "recognized"),
                )
        cur.execute(
            """
            UPDATE invoices
            SET status = 'confirmed', file_path = ?, confirmed_at = ?, updated_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (str(target), confirmed_at, confirmed_at, invoice_id),
        )
    return _invoice_out(_get_invoice(invoice_id))


@app.post("/api/invoices/{invoice_id}/confirm", response_model=InvoiceOut)
def confirm_invoice(invoice_id: int) -> InvoiceOut:
    return _confirm_invoice_record(invoice_id, record_hitl=True)


@app.post("/api/exports/excel", response_model=ExportOut)
def export_excel(request: ExportRequest) -> ExportOut:
    try:
        result = export_confirmed(
            request.destination_dir,
            request.prefix,
            request.start_number,
            request.filters,
            request.invoice_ids,
            request.create_new_folder,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExportOut(**result)


# ---------------------------------------------------------------------------
# Serve the built frontend (single-port / packaged deployment).
#
# When ``frontend/dist`` exists (a production build, or bundled into the exe),
# mount the UI at ``/`` so it shares one origin and one port with the ``/api``
# routes — no Node, no Vite dev server, no CORS at runtime. This catch-all is
# registered last, so all ``/api/...`` routes above still match first. In dev
# without a build it is skipped and Vite (:5173) proxies ``/api`` as before.
# ---------------------------------------------------------------------------
_FRONTEND_DIST = frontend_dist_dir()
if _FRONTEND_DIST is not None:
    _FRONTEND_DIST = _FRONTEND_DIST.resolve()
    _INDEX_HTML = _FRONTEND_DIST / "index.html"

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def serve_frontend(full_path: str, request: Request) -> FileResponse:
        # Only GET/HEAD on non-/api paths serve the SPA. Accepting the other
        # methods here (rather than a GET-only route) keeps unknown /api routes
        # returning a genuine 404 instead of a misleading 405 Method Not Allowed.
        if request.method not in ("GET", "HEAD") or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (_FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and _FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)  # real asset (js/css/img/favicon)
        return FileResponse(_INDEX_HTML)  # SPA fallback
