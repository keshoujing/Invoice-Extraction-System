"""Generate eval manifests from corrected HITL review confirmations.

Examples:
    cd backend
    python -m evals.refresh_from_review_labels --split mini --limit 50
    python -m evals.refresh_from_review_labels --split main --limit 300
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import DB_PATH  # noqa: E402


EXTRACTION_FIELDS = ("PO_number", "invoice_number", "invoice_date", "total_amount")
MANIFEST_COLUMNS = [
    "dataset",
    "document_no",
    "expense_type",
    "vendor_code",
    "vendor_name",
    "po_number",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "file_path",
    "expected_document_type",
    "expected_is_invoice",
    "expected_special_document_matched",
]

GENERATED_DIR = REPO_ROOT / "evaluation" / "generated"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _json_dict(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _field_value(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in data:
            return _text(data.get(key))
    return ""


def _has_field(data: dict[str, Any], *keys: str) -> bool:
    return any(key in data for key in keys)


def _manifest_file_path(raw_path: str) -> str:
    path = Path(raw_path)
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _candidate_confirmation_rows(db_path: Path) -> list[sqlite3.Row]:
    with _connect(db_path) as conn:
        return conn.execute(
            """
            SELECT
                i.id AS invoice_id,
                i.file_path,
                i.expense_type,
                i.vendor_code AS invoice_vendor_code,
                i.vendor_name AS invoice_vendor_name,
                c.id AS confirmation_id,
                c.user_confirmed_json,
                c.document_type,
                c.confirmed_at
            FROM review_confirmations c
            JOIN invoices i ON i.id = c.invoice_id
            WHERE c.was_corrected = 1
                AND TRIM(COALESCE(i.file_path, '')) <> ''
            ORDER BY c.confirmed_at DESC, c.id DESC
            """
        ).fetchall()


def _row_from_confirmation(row: sqlite3.Row, *, dataset: str) -> dict[str, str] | None:
    data = _json_dict(row["user_confirmed_json"])
    if not all(
        (
            _has_field(data, "PO_number", "po_number"),
            _has_field(data, "invoice_number"),
            _has_field(data, "invoice_date"),
            _has_field(data, "total_amount"),
        )
    ):
        return None

    vendor_code = _field_value(data, "vendor_code", "supplier_code") or _text(row["invoice_vendor_code"])
    vendor_name = _field_value(data, "vendor_name", "supplier_name") or _text(row["invoice_vendor_name"])
    document_type = _field_value(data, "document_type") or _text(row["document_type"]) or "invoice"
    special_matched = _field_value(data, "special_document_matched")

    return {
        "dataset": dataset,
        "document_no": f"review-{int(row['confirmation_id'])}",
        "expense_type": _field_value(data, "expense_type") or _text(row["expense_type"]),
        "vendor_code": vendor_code,
        "vendor_name": vendor_name,
        "po_number": _field_value(data, "PO_number", "po_number"),
        "invoice_number": _field_value(data, "invoice_number"),
        "invoice_date": _field_value(data, "invoice_date"),
        "total_amount": _field_value(data, "total_amount"),
        "file_path": _manifest_file_path(_text(row["file_path"])),
        "expected_document_type": document_type,
        "expected_is_invoice": "True",
        "expected_special_document_matched": "True" if special_matched.lower() == "true" else "False",
    }


def build_manifest_rows(
    *,
    db_path: Path = DB_PATH,
    limit: int = 50,
    dataset: str = "HITL Review",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for candidate in _candidate_confirmation_rows(db_path):
        row = _row_from_confirmation(candidate, dataset=dataset)
        if row is not None:
            rows.append(row)
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def write_manifest(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("mini", "main"), default="mini")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--seed", type=int, default=7, help=argparse.SUPPRESS)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    output = args.output or GENERATED_DIR / f"review_golden_{args.split}.tsv"
    rows = build_manifest_rows(
        db_path=args.db_path,
        limit=args.limit,
        dataset=f"HITL Review {args.split}",
    )
    write_manifest(rows, output)
    rendered_output = output.relative_to(REPO_ROOT) if output.is_relative_to(REPO_ROOT) else output
    print(f"wrote {len(rows)} corrected rows -> {rendered_output}")
    if args.limit > 0 and len(rows) < args.limit:
        print("corrected review confirmations were fewer than the requested limit; no unchanged rows were added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
