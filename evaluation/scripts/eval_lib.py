"""Shared helpers for the headless demo eval.

Kept dependency-free (stdlib only) so the scoring logic is easy to read and
test in isolation from the extraction pipeline.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

# Fields we score on the synthetic katanaml set. vendor_name is reported
# separately (ground truth bundles name + address), and PO_number / vendor_code
# do not exist on synthetic invoices.
SCORED_FIELDS = ("invoice_number", "invoice_date", "total_amount")


def flatten_gt(gt_parse: dict[str, Any]) -> dict[str, Any]:
    """Merge scalar fields from gt_parse and its one-level nested dicts.

    The dataset is inconsistent: fields live under `header`/`summary`, flat on
    gt_parse, or under a stray `"None"` key. List values (line items) are ignored.
    """
    merged: dict[str, Any] = {}
    for key, value in gt_parse.items():
        if isinstance(value, dict):
            for inner_key, inner_value in value.items():
                merged.setdefault(inner_key, inner_value)
        else:
            merged.setdefault(key, value)
    return merged


def map_ground_truth(gt_parse: dict[str, Any]) -> dict[str, str]:
    """Map the Donut-format ground truth to our extraction schema."""
    flat = flatten_gt(gt_parse)

    def get(key: str) -> str:
        return str(flat.get(key, "") or "")

    return {
        "invoice_number": get("invoice_no"),
        "invoice_date": get("invoice_date"),
        "vendor_name": get("seller"),
        "total_amount": get("total_gross_worth"),
    }


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(text, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return text


def parse_money(value: Any) -> float | None:
    """Parse a monetary string into a float, tolerant of US and EU formats.

    Handles "$ 978,12" (EU decimal comma) and "$9,952.80" (US thousands comma).
    """
    s = re.sub(r"[^0-9.,-]", "", str(value or "").strip())
    if not s or s in {"-", ".", ","}:
        return None
    if "," in s and "." in s:
        # The right-most separator is the decimal point.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) in (1, 2):  # trailing 1-2 digits -> decimal comma
            s = "".join(parts[:-1]) + "." + parts[-1]
        else:  # thousands separators
            s = "".join(parts)
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _strip_id(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def compare_field(field: str, expected: Any, actual: Any) -> bool:
    exp, act = str(expected or "").strip(), str(actual or "").strip()
    if field == "total_amount":
        e, a = parse_money(exp), parse_money(act)
        return e is not None and a is not None and e == a
    if field == "invoice_date":
        return bool(exp) and normalize_date(exp) == normalize_date(act)
    # invoice_number: case/space tolerant exact match
    return bool(exp) and _strip_id(exp) == _strip_id(act)


def vendor_contains(expected_seller: Any, actual_vendor: Any) -> bool:
    """Soft check: does the ground-truth seller string contain the model's
    vendor_name? (GT seller = name + address, model returns the name only.)"""
    exp = str(expected_seller or "").strip().lower()
    act = str(actual_vendor or "").strip().lower()
    return bool(act) and act in exp


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))
