from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field


MANUAL_CONFIRMATION_REQUIRED_FIELDS_KEY = "_manual_confirmation_required_fields"
MANUAL_CONFIRMATION_REQUIRED_KEY = "_manual_confirmation_required"


class SupplierCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_type: str = "unknown"
    document_is_invoice: bool = False
    document_type_reason: str = ""
    special_document_matched: bool = False
    special_document_vendor_code: str = ""
    special_document_vendor_name: str = ""
    special_document_reason: str = ""
    vendor_name_candidates: list[str] = Field(default_factory=list)
    evidence: str = ""


class SupplierDisambiguationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vendor_code: str = ""
    vendor_name: str = ""
    decision: str = "unknown"
    reason: str = ""


def extract_json_object_text(raw: str) -> str:
    """Best-effort recovery of a JSON object from free-form LLM output.

    Kept around for legacy text-mode responses and tests; structured-output
    paths use ``schema.model_validate_json(...)`` directly.
    """
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return text
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return candidate
        except json.JSONDecodeError:
            pass
    raise ValueError("Model output is not parseable JSON object")


def validate_supplier_candidate_response(raw: str) -> SupplierCandidateResponse:
    return SupplierCandidateResponse.model_validate_json(extract_json_object_text(raw))


def validate_supplier_disambiguation_response(raw: str) -> SupplierDisambiguationResponse:
    return SupplierDisambiguationResponse.model_validate_json(extract_json_object_text(raw))
