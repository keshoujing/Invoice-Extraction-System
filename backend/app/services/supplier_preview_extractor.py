from __future__ import annotations

import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Callable

from ..config import (
    MODEL_ID,
    llm_timeout_seconds,
    supplier_confidence_threshold,
    supplier_preview_retry_attempts,
    supplier_preview_retry_delay_seconds,
)
from ..llm import BytesPart, GeminiClient, LLMTimeoutError, TextPart
from ..llm.base import LLMClient, LLMError, LLMRateLimitError, LLMValidationError
from .invoice_extractor import ExtractionError, mime_type_for_path
from .llm_response_validation import (
    SupplierCandidateResponse,
    SupplierDisambiguationResponse,
)
from .supplier_matcher import SupplierMatcher, normalize_str


logger = logging.getLogger("uvicorn.error")

# Maximum wait for a single exponential-backoff retry, preventing oversized base delays from stretching retries indefinitely.
_MAX_RETRY_DELAY_SECONDS = 30.0


SUPPLIER_CANDIDATE_PROMPT = """Classify document type and extract issuer / supplier identity.
Use semantic understanding of document roles, not keyword matching.
Primary heuristic: the issuer name is usually shown in the top header area
(letterhead / logo area / company block near the top).
Return ONLY JSON:
{
  "document_type": "invoice|statement|purchase_order|remittance|receipt|credit_memo|other|unknown",
  "document_is_invoice": true,
  "document_type_reason": "short reason",
  "special_document_matched": false,
  "special_document_vendor_code": "",
  "special_document_vendor_name": "",
  "special_document_reason": "",
  "vendor_name_candidates": ["candidate 1", "candidate 2", "candidate 3"],
  "evidence": "short phrase or line that supports the supplier"
}
Rules:
- At most 3 candidates.
- Prefer names from top section and issuer-style company blocks.
- If a logo/header parent company differs from a clearly labeled Remit To, Payee,
  or payment recipient legal entity, prefer the Remit To / Payee entity as the
  supplier for this workflow.
- Do not include addresses or phone numbers.
- `document_is_invoice` must be true for actual invoices and invoice-like credit/debit memos
  that should continue into invoice recognition.
- For statement, PO, remittance advice, customs/tax/broker forms etc., set
  `document_is_invoice=false`.
- If a configured special supplier document rule below matches the document,
  treat that document as invoice-like for this workflow: set `document_is_invoice=true`,
  set `special_document_matched=true`, return that rule's vendor code and vendor name,
  and include the supplier name in `vendor_name_candidates`.
- Even when non-invoice, still return the entity that issued the document or should be paid.
- If unsure, return empty array and empty evidence.
"""

SUPPLIER_DISAMBIGUATION_PROMPT = """You must choose one supplier from fixed options.
Only select from the provided options. Never invent new names.
Use semantic role understanding. Prefer the invoice issuer/payee side.
Primary heuristic: issuer usually appears in the top header area.
Return ONLY JSON:
{
  "vendor_code": "one option code or empty",
  "vendor_name": "one option name or empty",
  "decision": "option|unknown",
  "reason": "very short reason"
}
"""

DEFAULT_PREVIEW: dict[str, Any] = {
    "Is_Invoice": "False",
    "document_type": "unknown",
    "document_is_invoice": "False",
    "document_type_reason": "",
    "vendor_name": "",
    "vendor_code": "",
    "vendor_matched": "False",
    "vendor_match_confidence": 0.0,
    "vendor_match_method": "none",
    "vendor_match_query": "",
    "special_document_matched": "False",
    "special_document_vendor_code": "",
    "special_document_vendor_name": "",
    "special_document_reason": "",
    "parse_mode": "gemini_supplier_preview",
    "parse_excerpt": "",
}

INVOICE_LIKE_DOCUMENT_TYPES = {"invoice", "credit_memo"}


class SupplierPreviewError(RuntimeError):
    pass


def _build_supplier_candidate_prompt(special_document_rules: list[dict[str, str]] | None = None) -> str:
    rules = special_document_rules or []
    if not rules:
        return SUPPLIER_CANDIDATE_PROMPT

    lines = [
        SUPPLIER_CANDIDATE_PROMPT.rstrip(),
        "",
        "Configured supplier preview rules:",
        "Use these short rules only when the document visibly matches the rule text.",
        "They help decide whether the document is invoice-like for this workflow and which supplier it belongs to.",
    ]
    for index, rule in enumerate(rules[:30], 1):
        code = normalize_str(str(rule.get("vendor_code") or ""))
        name = normalize_str(str(rule.get("vendor_name") or ""))
        prompt = normalize_str(str(rule.get("prompt_body") or ""))[:1200]
        scheme = normalize_str(str(rule.get("scheme_name") or ""))
        if not code or not name or not prompt:
            continue
        lines.extend(
            [
                f"{index}. vendor_code={code} | vendor_name={name}"
                + (f" | scheme={scheme}" if scheme else ""),
                prompt,
            ]
        )
    return "\n".join(lines)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else minimum


def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


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


def _pdf_first_page_is_text_pdf(path: Path) -> tuple[bool, int]:
    try:
        import fitz
    except Exception as exc:
        raise SupplierPreviewError("Missing pymupdf dependency; cannot crop PDF") from exc

    min_chars = _env_int("SUPPLIER_TEXT_PDF_MIN_CHARS", 80, minimum=20)
    with fitz.open(path) as doc:
        if doc.page_count <= 0:
            raise SupplierPreviewError("PDF file is empty; cannot recognize supplier")
        text = doc.load_page(0).get_text("text") or ""
    visible_chars = len(re.sub(r"\s+", "", text))
    return visible_chars >= min_chars, visible_chars


def _build_pdf_input(path: Path) -> tuple[bytes, str, int]:
    try:
        import fitz
    except Exception as exc:
        raise SupplierPreviewError("Missing pymupdf dependency; cannot crop PDF") from exc

    is_text_pdf, text_chars = _pdf_first_page_is_text_pdf(path)
    with fitz.open(path) as src:
        if src.page_count <= 0:
            raise SupplierPreviewError("PDF file is empty; cannot recognize supplier")
        first = src.load_page(0)
        page_rect = first.rect
        if is_text_pdf:
            clip = fitz.Rect(0, 0, page_rect.width, page_rect.height * 0.5)
            mode = "pdf_page1_top_half"
        else:
            clip = fitz.Rect(0, 0, page_rect.width, page_rect.height)
            mode = "pdf_page1_full"

        out = fitz.open()
        try:
            dst = out.new_page(width=clip.width, height=clip.height)
            dst.show_pdf_page(dst.rect, src, 0, clip=clip)
            payload = out.tobytes(garbage=4, deflate=True)
        finally:
            out.close()
    return payload, mode, text_chars


def _build_model_input(path: Path) -> tuple[bytes, str, str, int]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        payload, mode, text_chars = _build_pdf_input(path)
        return payload, "application/pdf", mode, text_chars
    if suffix in {".png", ".jpg", ".jpeg"}:
        return path.read_bytes(), mime_type_for_path(path), "image_full", 0
    raise SupplierPreviewError(f"Unsupported file type: {suffix}")


def _generate_json(
    system_prompt: str,
    source_bytes: bytes,
    mime_type: str,
    schema: type[SupplierCandidateResponse | SupplierDisambiguationResponse],
    user_text: str = "",
    trace_stage: str = "supplier_candidate",
    trace_metadata: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    on_retry: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    contents: list[Any] = []
    if user_text:
        contents.append(TextPart(text=user_text))
    contents.append(BytesPart(data=source_bytes, mime_type=mime_type))

    runner = client or _shared_client()
    attempts = supplier_preview_retry_attempts()
    retry_delay = supplier_preview_retry_delay_seconds()
    metadata = {
        "mime_type": mime_type,
        "input_byte_count": len(source_bytes),
        "has_user_text": bool(user_text),
        **(trace_metadata or {}),
    }
    response = None
    for attempt in range(1, attempts + 1):
        try:
            response = runner.generate(
                system=system_prompt,
                contents=contents,
                schema=schema,
                stage=trace_stage,
                metadata={**metadata, "attempt": attempt, "max_attempts": attempts},
            )
            break
        except LLMValidationError as exc:
            raise SupplierPreviewError(str(exc)) from exc
        except (LLMTimeoutError, LLMError) as exc:
            if not _is_retryable_llm_error(exc) or attempt >= attempts:
                raise SupplierPreviewError(str(exc)) from exc
            # Exponential backoff plus jitter: failure N waits delay * 2**(N-1), capped and then jittered,
            # to avoid concurrent tasks retrying at the same instant and worsening rate limits (429 / resource_exhausted).
            backoff = min(retry_delay * (2 ** (attempt - 1)), _MAX_RETRY_DELAY_SECONDS)
            sleep_for = backoff + random.uniform(0, retry_delay)
            logger.warning(
                "[SupplierPreview] stage=%s attempt=%s/%s temporary failure; retrying in %.1f seconds: %s",
                trace_stage,
                attempt,
                attempts,
                sleep_for,
                exc,
            )
            if on_retry is not None:
                # Progress callbacks only inform the frontend; callback failure must not affect the retry itself.
                try:
                    on_retry(attempt, attempts)
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception("[SupplierPreview] stage=%s retry progress callback error", trace_stage)
            if sleep_for > 0:
                time.sleep(sleep_for)

    if response is None or response.parsed is None:
        raise SupplierPreviewError("Model returned no structured result")
    return response.parsed.model_dump()


def _is_retryable_llm_error(exc: LLMError) -> bool:
    if isinstance(exc, (LLMTimeoutError, LLMRateLimitError)):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "gemini transient error",
            "gemini rate limit",
            "429",
            "499",
            "500",
            "502",
            "503",
            "504",
            "resource_exhausted",
            "rate limit",
            "rate_limit",
            "ratelimit",
            "too many requests",
            "quota",
            "cancelled",
            "deadline_exceeded",
            "internal",
            "temporarily unavailable",
            "service unavailable",
        )
    )


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "\u662f"}


def _normalize_document_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    aliases = {
        "invoice_document": "invoice",
        "tax_invoice": "invoice",
        "commercial_invoice": "invoice",
        "statement_of_account": "statement",
        "account_statement": "statement",
        "po": "purchase_order",
        "purchaseorder": "purchase_order",
        "po_document": "purchase_order",
        "payment_advice": "remittance",
        "remittance_advice": "remittance",
        "remittance_notice": "remittance",
        "creditmemo": "credit_memo",
    }
    return aliases.get(text, text or "unknown")


def _extract_document_type(payload: dict[str, Any]) -> tuple[str, bool, str]:
    doc_type = _normalize_document_type(payload.get("document_type"))
    reason = normalize_str(str(payload.get("document_type_reason") or ""))
    has_flag = "document_is_invoice" in payload and str(payload.get("document_is_invoice")).strip() != ""
    if has_flag:
        is_invoice = _to_bool(payload.get("document_is_invoice"))
    else:
        is_invoice = doc_type in INVOICE_LIKE_DOCUMENT_TYPES
    if not doc_type or doc_type == "unknown":
        doc_type = "invoice" if is_invoice else "unknown"
    if doc_type in INVOICE_LIKE_DOCUMENT_TYPES:
        is_invoice = True
    if doc_type == "invoice" and not is_invoice:
        doc_type = "other"
    return doc_type, is_invoice, reason[:280]


def _collect_candidates(payload: dict[str, Any]) -> list[str]:
    raw_candidates = payload.get("vendor_name_candidates")
    values: list[Any]
    if isinstance(raw_candidates, list):
        values = raw_candidates
    elif isinstance(raw_candidates, str):
        values = [raw_candidates]
    else:
        fallback = payload.get("vendor_name")
        values = [fallback] if isinstance(fallback, str) else []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = normalize_str(str(item or ""))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text[:120])
        if len(cleaned) >= 3:
            break
    return cleaned


def _build_supplier_options(candidates: list[str], supplier_matcher: SupplierMatcher) -> list[dict[str, Any]]:
    top_per_candidate = _env_int("SUPPLIER_LOCAL_TOP_PER_CANDIDATE", 3, minimum=1)
    keep_limit = _env_int("SUPPLIER_LOCAL_OPTIONS_LIMIT", 5, minimum=1)
    by_code: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        matches = supplier_matcher.top_matches(candidate, limit=top_per_candidate)
        for match in matches:
            if not match.code:
                continue
            current = by_code.get(match.code)
            if current and float(current["score"]) >= float(match.confidence):
                continue
            by_code[match.code] = {
                "code": match.code,
                "name": match.name,
                "score": round(float(match.confidence), 4),
                "source_candidate": candidate,
                "source_method": match.method,
            }

    options = sorted(by_code.values(), key=lambda item: float(item["score"]), reverse=True)
    return options[:keep_limit]


def _special_rule_supplier_from_payload(
    payload: dict[str, Any],
    special_document_rules: list[dict[str, str]] | None,
    supplier_matcher: SupplierMatcher,
) -> tuple[str, str] | None:
    if not _to_bool(payload.get("special_document_matched")):
        return None
    rules = special_document_rules or []
    if not rules:
        return None

    code = normalize_str(str(payload.get("special_document_vendor_code") or ""))
    name = normalize_str(str(payload.get("special_document_vendor_name") or ""))
    try:
        supplier = supplier_matcher.resolve_exact(code, name)
    except ValueError:
        supplier = None
    if supplier and any(rule.get("vendor_code") == supplier.code for rule in rules):
        return supplier.code, supplier.name

    for rule in rules:
        rule_code = normalize_str(str(rule.get("vendor_code") or ""))
        rule_name = normalize_str(str(rule.get("vendor_name") or ""))
        if code and rule_code and code.lower() == rule_code.lower():
            return rule_code, rule_name
        if name and rule_name and name.lower() == rule_name.lower():
            return rule_code, rule_name
    return None


def _needs_llm_disambiguation(options: list[dict[str, Any]], threshold: float) -> bool:
    if len(options) < 2:
        return False
    margin = _env_float("SUPPLIER_DISAMBIGUATION_MARGIN", 0.05, minimum=0.0, maximum=1.0)
    top = float(options[0]["score"])
    second = float(options[1]["score"])
    if top >= threshold and (top - second) >= margin:
        return False
    return True


def _preferred_option_by_candidate_order(
    candidates: list[str],
    options: list[dict[str, Any]],
    threshold: float,
) -> dict[str, Any] | None:
    for candidate in candidates:
        ranked = [
            item
            for item in options
            if normalize_str(str(item.get("source_candidate") or "")).lower()
            == normalize_str(candidate).lower()
        ]
        if not ranked:
            continue
        best = max(ranked, key=lambda item: float(item.get("score") or 0.0))
        if float(best.get("score") or 0.0) >= threshold:
            return best
    return None


def _select_option_by_llm(
    source_bytes: bytes,
    mime_type: str,
    candidates: list[str],
    options: list[dict[str, Any]],
    supplier_matcher: SupplierMatcher,
    trace_metadata: dict[str, Any] | None = None,
    on_retry: Callable[[int, int], None] | None = None,
) -> tuple[str, str] | None:
    option_lines = [
        f"{idx}. code={item['code']} | name={item['name']} | score={item['score']:.4f}"
        for idx, item in enumerate(options, 1)
    ]
    candidate_text = ", ".join(candidates) if candidates else "(none)"
    user_text = (
        f"Candidates: {candidate_text}\n"
        f"Options:\n" + "\n".join(option_lines) + "\n"
        "Choose one option, or unknown."
    )

    payload = _generate_json(
        system_prompt=SUPPLIER_DISAMBIGUATION_PROMPT,
        source_bytes=source_bytes,
        mime_type=mime_type,
        user_text=user_text,
        schema=SupplierDisambiguationResponse,
        on_retry=on_retry,
        trace_stage="supplier_disambiguation",
        trace_metadata={
            "candidate_count": len(candidates),
            "option_count": len(options),
            **(trace_metadata or {}),
        },
    )
    decision = str(payload.get("decision") or "").strip().lower()
    code = normalize_str(str(payload.get("vendor_code") or ""))
    name = normalize_str(str(payload.get("vendor_name") or ""))
    if decision == "unknown":
        return None

    try:
        supplier = supplier_matcher.resolve_exact(code, name)
    except ValueError:
        supplier = None
    if supplier:
        return supplier.code, supplier.name

    for item in options:
        if code and normalize_str(item["code"]).lower() == code.lower():
            return str(item["code"]), str(item["name"])
        if name and normalize_str(item["name"]).lower() == name.lower():
            return str(item["code"]), str(item["name"])
    return None


def extract_supplier_preview(
    file_path: str | Path,
    supplier_matcher: SupplierMatcher,
    special_document_rules: list[dict[str, str]] | None = None,
    trace_metadata: dict[str, Any] | None = None,
    on_retry: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise SupplierPreviewError(f"File does not exist: {path}")

    source_bytes, mime_type, input_mode, text_chars = _build_model_input(path)
    raw_payload = _generate_json(
        system_prompt=_build_supplier_candidate_prompt(special_document_rules),
        source_bytes=source_bytes,
        mime_type=mime_type,
        schema=SupplierCandidateResponse,
        on_retry=on_retry,
        trace_stage="supplier_candidate",
        trace_metadata={
            "file_name": path.name,
            "supplier_input_mode": input_mode,
            "supplier_text_page1_chars": text_chars,
            "special_document_rule_count": len(special_document_rules or []),
            **(trace_metadata or {}),
        },
    )
    special_supplier = _special_rule_supplier_from_payload(raw_payload, special_document_rules, supplier_matcher)
    document_type, document_is_invoice, document_reason = _extract_document_type(raw_payload)
    candidates = _collect_candidates(raw_payload)
    if special_supplier and special_supplier[1] not in candidates:
        candidates = [special_supplier[1], *candidates][:3]
    options = _build_supplier_options(candidates, supplier_matcher)
    threshold = supplier_confidence_threshold()

    selected: dict[str, Any] | None = (
        _preferred_option_by_candidate_order(candidates, options, threshold)
        or (options[0] if options else None)
    )
    method = selected.get("source_method", "none") if selected else "none"
    used_disambiguation = False
    special_document_matched = False
    special_document_reason = normalize_str(str(raw_payload.get("special_document_reason") or ""))

    if special_supplier:
        code, name = special_supplier
        selected = {
            "code": code,
            "name": name,
            "score": 1.0,
            "source_candidate": name,
            "source_method": "special_document_rule",
        }
        method = "special_document_rule"
        document_is_invoice = True
        if document_type in {"other", "unknown"}:
            document_type = "special_document"
        special_document_matched = True

    if selected and not special_document_matched and _needs_llm_disambiguation(options, threshold):
        picked = _select_option_by_llm(
            source_bytes,
            mime_type,
            candidates,
            options[:3],
            supplier_matcher,
            on_retry=on_retry,
            trace_metadata={
                "file_name": path.name,
                "supplier_input_mode": input_mode,
                "supplier_text_page1_chars": text_chars,
                **(trace_metadata or {}),
            },
        )
        if picked:
            code, name = picked
            picked_option = next((item for item in options if item["code"] == code), None)
            if picked_option:
                selected = picked_option
            else:
                selected = {
                    "code": code,
                    "name": name,
                    "score": selected["score"],
                    "source_candidate": "",
                    "source_method": "llm_disambiguation",
                }
            method = "llm_disambiguation"
            used_disambiguation = True

    evidence = normalize_str(str(raw_payload.get("evidence") or ""))
    query = " | ".join(candidates[:3])
    confidence = round(float(selected["score"]), 4) if selected else 0.0

    data = dict(DEFAULT_PREVIEW)
    data.update(
        {
            "Is_Invoice": "True" if document_is_invoice else "False",
            "document_type": document_type,
            "document_is_invoice": "True" if document_is_invoice else "False",
            "document_type_reason": document_reason,
            "vendor_name": str(selected["name"]) if selected else "",
            "vendor_code": str(selected["code"]) if selected else "",
            "vendor_matched": "True" if selected else "False",
            "vendor_match_confidence": confidence,
            "vendor_match_method": method,
            "vendor_match_query": query,
            "special_document_matched": "True" if special_document_matched else "False",
            "special_document_vendor_code": str(selected["code"]) if special_document_matched and selected else "",
            "special_document_vendor_name": str(selected["name"]) if special_document_matched and selected else "",
            "special_document_reason": special_document_reason[:280],
            "supplier_input_mode": input_mode,
            "supplier_text_page1_chars": text_chars,
            "supplier_raw_candidates": candidates,
            "supplier_top_options": options[:3],
            "supplier_disambiguation_used": "True" if used_disambiguation else "False",
            "parse_excerpt": evidence[:280],
        }
    )
    return data
