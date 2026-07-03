"""Per-supplier few-shot examples for the invoice extraction prompt.

Pulls the most recent human-confirmed extractions for the same vendor from
``review_confirmations`` and renders them as in-context examples. New / cold
suppliers (history below ``MIN_HISTORY``) fall back to the baseline prompt by
returning an empty list.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..config import DB_PATH
from ..review_labels import CORE_REVIEW_FIELDS, canonical_review_field


DEFAULT_K = 3
MIN_HISTORY = 3


def _normalize_example(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, value in data.items():
        canonical = canonical_review_field(raw_key)
        if canonical in CORE_REVIEW_FIELDS and canonical not in result:
            result[canonical] = value
    return result


def fetch_supplier_examples(
    cur: sqlite3.Cursor,
    vendor_code: str,
    *,
    k: int = DEFAULT_K,
    min_history: int = MIN_HISTORY,
) -> list[dict[str, Any]]:
    code = (vendor_code or "").strip()
    if not code:
        return []

    target = max(k, min_history)
    rows = cur.execute(
        """
        SELECT user_confirmed_json
        FROM review_confirmations
        WHERE supplier_code = ?
        ORDER BY confirmed_at DESC, id DESC
        LIMIT ?
        """,
        (code, target + 5),
    ).fetchall()

    parsed: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row["user_confirmed_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        normalized = _normalize_example(data)
        if normalized:
            parsed.append(normalized)

    if len(parsed) < min_history:
        return []
    return parsed[:k]


def get_few_shot_examples(
    vendor_code: str,
    *,
    db_path: str | Path | None = None,
    k: int = DEFAULT_K,
    min_history: int = MIN_HISTORY,
) -> list[dict[str, Any]]:
    code = (vendor_code or "").strip()
    if not code:
        return []

    target_path = Path(db_path) if db_path is not None else DB_PATH
    if not Path(target_path).exists():
        return []

    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    try:
        return fetch_supplier_examples(conn.cursor(), code, k=k, min_history=min_history)
    finally:
        conn.close()


def format_few_shot_block(
    examples: Iterable[dict[str, Any]] | None,
    vendor_code: str,
) -> str:
    listed = list(examples or ())
    if not listed:
        return ""

    code = (vendor_code or "").strip() or "(unknown)"
    header = (
        f"Reference: {len(listed)} recent human-confirmed extractions from this same supplier "
        f"(vendor_code={code})."
    )
    guidance = (
        "Use them as guidance for this supplier's typical formatting (PO prefixes, "
        "invoice number patterns, vendor name spelling, amount magnitude)."
    )
    safety = (
        "These are NOT the answer to this new invoice; extract the actual values from "
        "the document below."
    )

    lines: list[str] = [header, guidance, safety, ""]
    for index, example in enumerate(listed, start=1):
        compact = json.dumps(example, ensure_ascii=False, sort_keys=True)
        lines.append(f"Example {index}: {compact}")
    return "\n".join(lines)
