from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ..config import DB_PATH
from .base import LLMResponse


logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 365
ERROR_MESSAGE_LIMIT = 500

BUSINESS_METADATA_KEYS = ("supplier_code", "tag", "file_hash", "prompt_version")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def _open(db_path: Path | None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _trim(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return text[:limit]


def _business(metadata: dict[str, Any] | None) -> dict[str, str | None]:
    metadata = metadata or {}
    return {key: (str(metadata.get(key)).strip() or None) if metadata.get(key) is not None else None for key in BUSINESS_METADATA_KEYS}


def record_llm_call(
    response: LLMResponse,
    *,
    stage: str,
    metadata: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> None:
    """Insert a successful call. Failures here are logged, never raised."""
    fields = _business(metadata)
    try:
        with _open(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO llm_calls (
                    ts, request_id, provider, model, stage,
                    input_tokens, output_tokens, total_tokens,
                    cost_usd, latency_ms, success,
                    error_class, error_message,
                    supplier_code, tag, file_hash, prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    response.request_id,
                    response.provider,
                    response.model,
                    stage,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    response.usage.total_tokens,
                    response.cost_usd,
                    response.latency_ms,
                    fields["supplier_code"],
                    fields["tag"],
                    fields["file_hash"],
                    fields["prompt_version"],
                ),
            )
    except Exception as exc:
        logger.warning("llm_calls insert failed (success=1): %s", exc)


def record_llm_failure(
    *,
    request_id: str,
    provider: str,
    model: str,
    stage: str,
    error_class: str,
    error_message: str,
    latency_ms: int,
    metadata: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> None:
    """Insert a failed call (no LLMResponse). Failures here are logged, never raised."""
    fields = _business(metadata)
    try:
        with _open(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO llm_calls (
                    ts, request_id, provider, model, stage,
                    input_tokens, output_tokens, total_tokens,
                    cost_usd, latency_ms, success,
                    error_class, error_message,
                    supplier_code, tag, file_hash, prompt_version
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    request_id,
                    provider,
                    model,
                    stage,
                    latency_ms,
                    error_class,
                    _trim(error_message, ERROR_MESSAGE_LIMIT),
                    fields["supplier_code"],
                    fields["tag"],
                    fields["file_hash"],
                    fields["prompt_version"],
                ),
            )
    except Exception as exc:
        logger.warning("llm_calls insert failed (success=0): %s", exc)


def purge_old_llm_calls(
    retention_days: int = DEFAULT_RETENTION_DAYS,
    *,
    db_path: Path | None = None,
) -> int:
    """Delete rows older than ``retention_days``. Returns number of rows removed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).replace(microsecond=0).isoformat()
    try:
        with _open(db_path) as conn:
            cur = conn.execute("DELETE FROM llm_calls WHERE ts < ?", (cutoff,))
            return cur.rowcount or 0
    except Exception as exc:
        logger.warning("purge_old_llm_calls failed: %s", exc)
        return 0


def total_cost(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    db_path: Path | None = None,
) -> float:
    return _scalar_query(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls",
        start=start,
        end=end,
        db_path=db_path,
        default=0.0,
    )


def cost_by_dimension(
    column: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    if column not in {"model", "provider", "stage", "supplier_code", "tag", "prompt_version"}:
        raise ValueError(f"unsupported dimension: {column}")
    rows = _grouped_query(
        f"""
        SELECT {column} AS dimension,
               COUNT(*) AS request_count,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cost_usd) AS cost_usd,
               AVG(latency_ms) AS latency_ms_avg,
               SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
               SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count
        FROM llm_calls
        """,
        start=start,
        end=end,
        group_by=column,
        order_by="cost_usd DESC",
        db_path=db_path,
    )
    return [
        {
            "dimension": row[0] if row[0] is not None else "",
            "request_count": int(row[1] or 0),
            "input_tokens": int(row[2] or 0),
            "output_tokens": int(row[3] or 0),
            "cost_usd": float(row[4] or 0),
            "latency_ms_avg": float(row[5] or 0),
            "success_count": int(row[6] or 0),
            "failure_count": int(row[7] or 0),
        }
        for row in rows
    ]


def failure_rate(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    db_path: Path | None = None,
) -> float:
    """Fraction of calls that failed in the window. Returns 0.0 when no calls."""
    with _open(db_path) as conn:
        sql = "SELECT COUNT(*), SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) FROM llm_calls"
        sql_with_window, params = _apply_window(sql, start, end)
        row = conn.execute(sql_with_window, params).fetchone()
    total, failed = (row[0] or 0), (row[1] or 0)
    return (failed / total) if total else 0.0


def _scalar_query(
    base_sql: str,
    *,
    start: datetime | None,
    end: datetime | None,
    db_path: Path | None,
    default: float,
) -> float:
    sql, params = _apply_window(base_sql, start, end)
    with _open(db_path) as conn:
        row = conn.execute(sql, params).fetchone()
    if not row:
        return default
    return float(row[0] or default)


def _grouped_query(
    base_sql: str,
    *,
    start: datetime | None,
    end: datetime | None,
    group_by: str,
    order_by: str,
    db_path: Path | None,
) -> list[tuple[Any, ...]]:
    sql, params = _apply_window(base_sql, start, end)
    sql = f"{sql} GROUP BY {group_by} ORDER BY {order_by}"
    with _open(db_path) as conn:
        return list(conn.execute(sql, params).fetchall())


def _apply_window(
    base_sql: str,
    start: datetime | None,
    end: datetime | None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if start is not None:
        clauses.append("ts >= ?")
        params.append(start.astimezone(timezone.utc).replace(microsecond=0).isoformat())
    if end is not None:
        clauses.append("ts < ?")
        params.append(end.astimezone(timezone.utc).replace(microsecond=0).isoformat())
    if not clauses:
        return base_sql, ()
    connector = " AND " if " WHERE " in base_sql.upper() else " WHERE "
    return base_sql + connector + " AND ".join(clauses), tuple(params)
