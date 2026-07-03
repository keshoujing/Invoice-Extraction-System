from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class AutoArchiveFieldResult:
    key: str
    value: Decimal | None
    baseline: Decimal | None
    tolerance_percent: Decimal | None
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class AutoArchiveEvaluation:
    has_checks: bool
    passed: bool
    field_results: list[AutoArchiveFieldResult] = field(default_factory=list)

    @property
    def failed_fields(self) -> list[str]:
        return [item.key for item in self.field_results if not item.passed]


def evaluate_auto_archive_checks(
    fields: list[dict[str, Any]],
    extracted_data: dict[str, Any],
) -> AutoArchiveEvaluation:
    results: list[AutoArchiveFieldResult] = []
    for field_config in fields:
        key = str(field_config.get("key") or "").strip()
        check = field_config.get("auto_archive_check")
        if not key or str(field_config.get("type") or "") != "value" or not isinstance(check, dict):
            continue
        if not _truthy(check.get("enabled")):
            continue

        baseline = _decimal(check.get("baseline_value"))
        tolerance = _decimal(check.get("tolerance_percent"))
        if baseline is None or baseline == 0 or tolerance is None or tolerance < 0:
            results.append(AutoArchiveFieldResult(key, None, baseline, tolerance, False, "invalid_config"))
            continue

        # Array child field: "array_key.child_key" — every item must pass
        if "." in key:
            array_key, child_key = key.split(".", 1)
            raw = extracted_data.get(array_key)
            items = raw if isinstance(raw, list) else []
            if not items:
                results.append(AutoArchiveFieldResult(key, None, baseline, tolerance, False, "empty_array"))
                continue
            all_passed = True
            for item in items:
                if not isinstance(item, dict):
                    all_passed = False
                    break
                value = _decimal(item.get(child_key))
                if value is None:
                    all_passed = False
                    break
                delta = abs(value - baseline)
                allowed = abs(baseline) * tolerance / Decimal("100")
                if delta > allowed:
                    all_passed = False
                    break
            results.append(AutoArchiveFieldResult(
                key, None, baseline, tolerance, all_passed,
                "" if all_passed else "out_of_tolerance",
            ))
            continue

        # Scalar value field
        value = _decimal(extracted_data.get(key))
        if value is None:
            results.append(AutoArchiveFieldResult(key, value, baseline, tolerance, False, "invalid_value"))
            continue

        delta = abs(value - baseline)
        allowed = abs(baseline) * tolerance / Decimal("100")
        passed = delta <= allowed
        results.append(
            AutoArchiveFieldResult(
                key,
                value,
                baseline,
                tolerance,
                passed,
                "" if passed else "out_of_tolerance",
            )
        )

    return AutoArchiveEvaluation(
        has_checks=bool(results),
        passed=bool(results) and all(item.passed for item in results),
        field_results=results,
    )


def _decimal(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "\u662f"}
