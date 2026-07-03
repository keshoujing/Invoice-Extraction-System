from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any


def safe_filename(name: str) -> str:
    keep = []
    for char in name:
        if char.isalnum() or char in {" ", ".", "-", "_", "(", ")"}:
            keep.append(char)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip().strip(".")
    return cleaned or "invoice"


INVOICE_DATE_PATTERNS = [
    "%m/%d/%Y",
    "%m%d%Y",
    "%m-%d-%Y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%m-%d-%y",
    "%m.%d.%Y",
    "%m.%d.%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
]


def _parse_date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    normalized = " ".join(text.replace(",", ", ").split())
    for pattern in INVOICE_DATE_PATTERNS:
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def parse_invoice_date(value: Any) -> str:
    parsed = _parse_date_value(value)
    if not parsed:
        return ""
    return parsed.isoformat()


def format_invoice_date(value: Any) -> str:
    text = str(value or "").strip()
    parsed = _parse_date_value(value)
    if not parsed:
        return text
    return parsed.strftime("%m/%d/%Y")


def amount_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return round(float(value), 2)
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def extension_for_path(path: str) -> str:
    suffix = Path(path).suffix
    return suffix if suffix else ".pdf"
