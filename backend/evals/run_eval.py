"""Minimal eval runner for invoice extraction and supplier preview.

Reads evaluation/eval_manifest.tsv and writes per-row TSV reports.

Examples:
    cd backend
    python -m evals.run_eval                       # extraction, first 10 rows
    python -m evals.run_eval --stage supplier      # supplier preview, first 10 rows
    python -m evals.run_eval --stage both --full   # both stages, all rows
    python -m evals.run_eval --limit 20
    python -m evals.run_eval --only K260699
    python -m evals.run_eval --dataset "MRO Eval Set"
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.database import init_db  # noqa: E402
from app.main import (  # noqa: E402
    _combine_recognition_prompt,
    _ensure_prompt_tag_defaults,
    _resolve_prompt_for_supplier,
    _special_document_preview_rules,
    _special_document_rule_for_supplier,
    supplier_matcher,
)
from app.services.invoice_extractor import extract_invoice_with_config  # noqa: E402
from app.services.supplier_preview_extractor import extract_supplier_preview  # noqa: E402


MANIFEST_PATH = REPO_ROOT / "evaluation" / "eval_manifest.tsv"
RUNS_DIR = REPO_ROOT / "evaluation" / "runs"

FIELDS = ("PO_number", "invoice_number", "invoice_date", "total_amount")
SUPPLIER_FIELDS = ("vendor_code", "document_is_invoice", "special_document_matched", "document_type")
TRUTHY = {"1", "true", "yes", "y", "yes"}


@dataclass
class Row:
    dataset: str
    document_no: str
    expense_type: str
    vendor_code: str
    vendor_name: str
    file_path: Path
    expected_document_type: str
    expected_is_invoice: str
    expected_special_document_matched: str
    expected: dict[str, str]


def load_manifest(path: Path = MANIFEST_PATH) -> list[Row]:
    rows: list[Row] = []
    with path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        required_columns = {"dataset", "document_no", "vendor_code", "vendor_name", "file_path"}
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(required_columns - fieldnames)
        if missing:
            actual = ", ".join(reader.fieldnames or [])
            raise ValueError(f"manifest missing columns: {', '.join(missing)}; actual columns: {actual}")
        for item in reader:
            rows.append(
                Row(
                    dataset=item["dataset"],
                    document_no=item["document_no"],
                    expense_type=item.get("expense_type", ""),
                    vendor_code=item["vendor_code"],
                    vendor_name=item["vendor_name"],
                    file_path=REPO_ROOT / item["file_path"],
                    expected_document_type=item.get("expected_document_type") or "invoice",
                    expected_is_invoice=item.get("expected_is_invoice") or "True",
                    expected_special_document_matched=item.get("expected_special_document_matched") or "False",
                    expected={
                        "PO_number": item.get("po_number", ""),
                        "invoice_number": item.get("invoice_number", ""),
                        "invoice_date": item.get("invoice_date", ""),
                        "total_amount": item.get("total_amount", ""),
                    },
                )
            )
    return rows


def normalize_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return text


def normalize_amount(value: Any) -> str:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return ""
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return text


def normalize_bool(value: Any) -> str:
    return "True" if str(value or "").strip().lower() in TRUTHY else "False"


def normalize_document_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text.replace("-", "_").replace(" ", "_")


def _json_cell(value: Any) -> str:
    if value in (None, ""):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _strip_id(value: str) -> str:
    # Excel auto-strips leading zeros on numeric IDs, so manifest values like
    # "561197" should match model output "0561197". Spaces also vary.
    return str(value or "").strip().replace(" ", "").lstrip("0")


def compare(field: str, expected: str, actual: Any) -> bool:
    exp = str(expected or "").strip()
    act = str(actual or "").strip()
    if field == "total_amount":
        return normalize_amount(exp) == normalize_amount(act) and exp != ""
    if field == "invoice_date":
        return normalize_date(exp) == normalize_date(act) and exp != ""
    # PO_number / invoice_number: leading-zero / space tolerant. Empty
    # expected counts as pass only if actual is also empty (e.g. invoices
    # without PO).
    return _strip_id(exp) == _strip_id(act)


def compare_supplier(field: str, row: Row, actual: dict[str, Any]) -> bool:
    if field == "vendor_code":
        return str(row.vendor_code or "").strip() == str(actual.get("vendor_code") or "").strip()
    if field == "document_is_invoice":
        return normalize_bool(row.expected_is_invoice) == normalize_bool(
            actual.get("document_is_invoice", actual.get("Is_Invoice"))
        )
    if field == "special_document_matched":
        return normalize_bool(row.expected_special_document_matched) == normalize_bool(
            actual.get("special_document_matched")
        )
    if field == "document_type":
        expected = normalize_document_type(row.expected_document_type)
        if not expected:
            return True
        return expected == normalize_document_type(actual.get("document_type"))
    raise ValueError(f"unknown supplier field: {field}")


def run_extraction_one(row: Row) -> dict[str, Any]:
    if not row.file_path.exists():
        return {"error": f"file missing: {row.file_path}", "actual": {}}
    tag_name, tag_prompt_body, tag_fields = _resolve_prompt_for_supplier(row.vendor_code)
    # Mirror production: if the vendor has an active special document rule,
    # apply it. Production only triggers via the upload-stage preview flag,
    # but the eval skips preview, so we apply whenever the rule exists.
    special_rule = _special_document_rule_for_supplier(row.vendor_code)
    if special_rule:
        _, special_prompt_body, special_fields = special_rule
        prompt_body = _combine_recognition_prompt(tag_name, tag_prompt_body, special_prompt_body)
        field_configs = special_fields
        effective_tag = f"{tag_name}+special"
    else:
        prompt_body = tag_prompt_body
        field_configs = tag_fields
        effective_tag = tag_name
    try:
        data = extract_invoice_with_config(
            row.file_path,
            prompt_body,
            field_configs,
            confirmed_vendor_name=row.vendor_name,
            confirmed_vendor_code=row.vendor_code,
            trace_metadata={"eval_document_no": row.document_no, "prompt_tag": effective_tag},
        )
    except Exception as exc:  # noqa: BLE001 - eval should not crash mid-run
        return {"error": f"{type(exc).__name__}: {exc}", "actual": {}, "tag": effective_tag}
    return {"error": "", "actual": data, "tag": effective_tag}


def run_supplier_one(row: Row) -> dict[str, Any]:
    if not row.file_path.exists():
        return {"error": f"file missing: {row.file_path}", "actual": {}}
    try:
        data = extract_supplier_preview(
            row.file_path,
            supplier_matcher,
            special_document_rules=_special_document_preview_rules(),
            trace_metadata={"eval_document_no": row.document_no, "eval_stage": "supplier_preview"},
        )
    except Exception as exc:  # noqa: BLE001 - eval should not crash mid-run
        return {"error": f"{type(exc).__name__}: {exc}", "actual": {}}
    return {"error": "", "actual": data}


def write_extraction_row(writer: csv.writer, row: Row, result: dict[str, Any]) -> dict[str, bool]:
    actual = result["actual"]
    flags: dict[str, bool] = {}
    cells = [row.document_no, row.dataset, row.vendor_code, result.get("tag", "")]
    for field in FIELDS:
        exp = row.expected[field]
        act = actual.get(field, "") if not result["error"] else ""
        ok = False if result["error"] else compare(field, exp, act)
        flags[field] = ok
        cells.extend([exp, str(act), "1" if ok else "0"])
    overall = all(flags.values()) and not result["error"]
    cells.extend(["1" if overall else "0", result["error"]])
    writer.writerow(cells)
    return flags


def write_supplier_row(writer: csv.writer, row: Row, result: dict[str, Any]) -> dict[str, bool]:
    actual = result["actual"]
    flags: dict[str, bool] = {}
    cells = [row.document_no, row.dataset, row.expense_type]
    expected_values = {
        "vendor_code": row.vendor_code,
        "document_is_invoice": normalize_bool(row.expected_is_invoice),
        "special_document_matched": normalize_bool(row.expected_special_document_matched),
        "document_type": row.expected_document_type,
    }
    actual_values = {
        "vendor_code": actual.get("vendor_code", ""),
        "document_is_invoice": normalize_bool(actual.get("document_is_invoice", actual.get("Is_Invoice"))),
        "special_document_matched": normalize_bool(actual.get("special_document_matched")),
        "document_type": actual.get("document_type", ""),
    }
    for field in SUPPLIER_FIELDS:
        ok = False if result["error"] else compare_supplier(field, row, actual)
        flags[field] = ok
        cells.extend([expected_values[field], str(actual_values[field]), "1" if ok else "0"])

    supplier_overall = (
        flags["vendor_code"]
        and flags["document_is_invoice"]
        and flags["special_document_matched"]
        and not result["error"]
    )
    cells.extend(
        [
            row.vendor_name,
            str(actual.get("vendor_name", "")) if not result["error"] else "",
            str(actual.get("vendor_matched", "")) if not result["error"] else "",
            str(actual.get("vendor_match_confidence", "")) if not result["error"] else "",
            str(actual.get("vendor_match_method", "")) if not result["error"] else "",
            _json_cell(actual.get("supplier_raw_candidates")) if not result["error"] else "",
            _json_cell(actual.get("supplier_top_options")) if not result["error"] else "",
            "1" if supplier_overall else "0",
            result["error"],
        ]
    )
    writer.writerow(cells)
    return flags


def filter_rows(rows: list[Row], args: argparse.Namespace) -> list[Row]:
    if args.only:
        rows = [r for r in rows if r.document_no == args.only]
    if args.dataset:
        rows = [r for r in rows if r.dataset == args.dataset]
    if args.vendor:
        rows = [r for r in rows if r.vendor_code == args.vendor]
    if not args.full:
        rows = rows[: args.limit]
    return rows


def _pct(count: int, total: int) -> str:
    return f" ({count / total * 100:.1f}%)" if total else ""


def _run_extraction(rows: list[Row], timestamp: str, suffix: str = "") -> bool:
    out_path = RUNS_DIR / f"{timestamp}{suffix}.tsv"
    field_pass = {f: 0 for f in FIELDS}
    overall_pass = 0
    errors = 0

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        header = ["document_no", "dataset", "vendor_code", "tag"]
        for f in FIELDS:
            header.extend([f"{f}_expected", f"{f}_actual", f"{f}_ok"])
        header.extend(["overall_ok", "error"])
        writer.writerow(header)

        for idx, row in enumerate(rows, 1):
            print(f"[extraction {idx}/{len(rows)}] {row.document_no} {row.vendor_code}", flush=True)
            try:
                result = run_extraction_one(row)
            except Exception:  # noqa: BLE001
                result = {"error": traceback.format_exc(limit=1).strip(), "actual": {}}
            if result["error"]:
                errors += 1
            flags = write_extraction_row(writer, row, result)
            for f, ok in flags.items():
                field_pass[f] += int(ok)
            if all(flags.values()) and not result["error"]:
                overall_pass += 1

    total = len(rows)
    print()
    print(f"extraction results -> {out_path.relative_to(REPO_ROOT)}")
    print(f"total: {total}  pass: {overall_pass}{_pct(overall_pass, total)}  errors: {errors}")
    for f in FIELDS:
        print(f"  {f:<16} {field_pass[f]}/{total}{_pct(field_pass[f], total)}")
    return overall_pass == total


def _run_supplier(rows: list[Row], timestamp: str, suffix: str = "_supplier") -> bool:
    out_path = RUNS_DIR / f"{timestamp}{suffix}.tsv"
    field_pass = {f: 0 for f in SUPPLIER_FIELDS}
    overall_pass = 0
    errors = 0

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        header = ["document_no", "dataset", "expense_type"]
        for f in SUPPLIER_FIELDS:
            header.extend([f"{f}_expected", f"{f}_actual", f"{f}_ok"])
        header.extend(
            [
                "vendor_name_expected",
                "vendor_name_actual",
                "vendor_matched",
                "vendor_match_confidence",
                "vendor_match_method",
                "supplier_raw_candidates",
                "supplier_top_options",
                "supplier_overall_ok",
                "error",
            ]
        )
        writer.writerow(header)

        for idx, row in enumerate(rows, 1):
            print(f"[supplier {idx}/{len(rows)}] {row.document_no} {row.vendor_code}", flush=True)
            try:
                result = run_supplier_one(row)
            except Exception:  # noqa: BLE001
                result = {"error": traceback.format_exc(limit=1).strip(), "actual": {}}
            if result["error"]:
                errors += 1
            flags = write_supplier_row(writer, row, result)
            for f, ok in flags.items():
                field_pass[f] += int(ok)
            if (
                flags["vendor_code"]
                and flags["document_is_invoice"]
                and flags["special_document_matched"]
                and not result["error"]
            ):
                overall_pass += 1

    total = len(rows)
    print()
    print(f"supplier results -> {out_path.relative_to(REPO_ROOT)}")
    print(f"total: {total}  pass: {overall_pass}{_pct(overall_pass, total)}  errors: {errors}")
    for f in SUPPLIER_FIELDS:
        print(f"  {f:<26} {field_pass[f]}/{total}{_pct(field_pass[f], total)}")
    return overall_pass == total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=("extraction", "supplier", "both"),
        default="extraction",
        help="eval stage to run",
    )
    parser.add_argument("--full", action="store_true", help="run all rows in manifest")
    parser.add_argument("--limit", type=int, default=10, help="row limit when --full not set")
    parser.add_argument("--only", help="single document_no")
    parser.add_argument("--dataset", help='filter by manifest "dataset" column')
    parser.add_argument("--vendor", help="filter by vendor_code")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="path to eval manifest TSV")
    args = parser.parse_args()

    init_db()
    _ensure_prompt_tag_defaults()
    rows = filter_rows(load_manifest(args.manifest), args)
    if not rows:
        print("no rows match the filter")
        return 1

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ok = True
    if args.stage in {"supplier", "both"}:
        ok = _run_supplier(rows, timestamp) and ok
    if args.stage in {"extraction", "both"}:
        suffix = "_extraction" if args.stage == "both" else ""
        ok = _run_extraction(rows, timestamp, suffix=suffix) and ok
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
