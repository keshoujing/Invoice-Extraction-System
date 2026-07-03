from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.llm.base import LLMResponse, Usage
from app.llm.telemetry import (
    cost_by_dimension,
    failure_rate,
    purge_old_llm_calls,
    record_llm_call,
    record_llm_failure,
    total_cost,
)


SCHEMA_SQL = """
CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL,
    error_class TEXT,
    error_message TEXT,
    supplier_code TEXT,
    tag TEXT,
    file_hash TEXT,
    prompt_version TEXT
);
CREATE INDEX idx_llm_calls_ts ON llm_calls(ts);
"""


def _make_response(*, request_id: str = "req-1", model: str = "gemini-2.5-flash", cost: float = 0.001) -> LLMResponse:
    return LLMResponse(
        text="ok",
        parsed=None,
        usage=Usage(input_tokens=100, output_tokens=20, total_tokens=120),
        latency_ms=512,
        cost_usd=cost,
        model=model,
        provider="gemini",
        request_id=request_id,
        raw_response=None,
    )


def _override_ts(db_path: Path, request_id: str, ts_iso: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("UPDATE llm_calls SET ts = ? WHERE request_id = ?", (ts_iso, request_id))
        conn.commit()


class TelemetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _row_count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0])

    def test_record_llm_call_inserts_success_row(self) -> None:
        record_llm_call(
            _make_response(request_id="r1"),
            stage="invoice_extraction",
            metadata={"supplier_code": "10001234", "tag": "default", "file_hash": "abc", "prompt_version": "v3"},
            db_path=self.db_path,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM llm_calls").fetchone()
        self.assertEqual(row["request_id"], "r1")
        self.assertEqual(row["provider"], "gemini")
        self.assertEqual(row["stage"], "invoice_extraction")
        self.assertEqual(row["input_tokens"], 100)
        self.assertEqual(row["output_tokens"], 20)
        self.assertEqual(row["total_tokens"], 120)
        self.assertAlmostEqual(row["cost_usd"], 0.001)
        self.assertEqual(row["latency_ms"], 512)
        self.assertEqual(row["success"], 1)
        self.assertEqual(row["supplier_code"], "10001234")
        self.assertEqual(row["tag"], "default")

    def test_record_llm_failure_inserts_failure_row(self) -> None:
        record_llm_failure(
            request_id="r-fail",
            provider="litellm",
            model="gpt-4o",
            stage="invoice_extraction",
            error_class="LLMRateLimitError",
            error_message="rate limited",
            latency_ms=812,
            metadata={"supplier_code": "10001234"},
            db_path=self.db_path,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM llm_calls").fetchone()
        self.assertEqual(row["success"], 0)
        self.assertEqual(row["error_class"], "LLMRateLimitError")
        self.assertEqual(row["error_message"], "rate limited")
        self.assertEqual(row["input_tokens"], 0)
        self.assertEqual(row["cost_usd"], 0)

    def test_request_id_unique_constraint_via_insert_or_ignore(self) -> None:
        record_llm_call(_make_response(request_id="dup"), stage="x", db_path=self.db_path)
        record_llm_call(_make_response(request_id="dup"), stage="x", db_path=self.db_path)
        self.assertEqual(self._row_count(), 1)

    def test_telemetry_swallows_db_errors(self) -> None:
        bad_path = Path(self.tmpdir.name) / "missing" / "no_such.sqlite3"
        # Should not raise — failure is logged.
        record_llm_call(_make_response(request_id="x"), stage="x", db_path=bad_path)

    def test_purge_keeps_recent_drops_old(self) -> None:
        record_llm_call(_make_response(request_id="recent"), stage="x", db_path=self.db_path)
        record_llm_call(_make_response(request_id="old"), stage="x", db_path=self.db_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=400)).replace(microsecond=0).isoformat()
        _override_ts(self.db_path, "old", old_ts)

        deleted = purge_old_llm_calls(retention_days=365, db_path=self.db_path)

        self.assertEqual(deleted, 1)
        self.assertEqual(self._row_count(), 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            kept = conn.execute("SELECT request_id FROM llm_calls").fetchone()
        self.assertEqual(kept[0], "recent")

    def test_total_cost_sums_window(self) -> None:
        record_llm_call(_make_response(request_id="a", cost=0.01), stage="x", db_path=self.db_path)
        record_llm_call(_make_response(request_id="b", cost=0.02), stage="x", db_path=self.db_path)
        self.assertAlmostEqual(total_cost(db_path=self.db_path), 0.03)

    def test_cost_by_dimension_groups_and_orders(self) -> None:
        record_llm_call(_make_response(request_id="a", model="gemini-2.5-flash", cost=0.01), stage="x", db_path=self.db_path)
        record_llm_call(_make_response(request_id="b", model="gpt-4o", cost=0.05), stage="x", db_path=self.db_path)
        record_llm_call(_make_response(request_id="c", model="gpt-4o", cost=0.03), stage="x", db_path=self.db_path)

        rows = cost_by_dimension("model", db_path=self.db_path)

        self.assertEqual(rows[0]["dimension"], "gpt-4o")
        self.assertAlmostEqual(rows[0]["cost_usd"], 0.08)
        self.assertEqual(rows[0]["request_count"], 2)
        self.assertEqual(rows[1]["dimension"], "gemini-2.5-flash")

    def test_failure_rate_handles_empty_table(self) -> None:
        self.assertEqual(failure_rate(db_path=self.db_path), 0.0)

    def test_failure_rate_counts_correctly(self) -> None:
        record_llm_call(_make_response(request_id="ok1"), stage="x", db_path=self.db_path)
        record_llm_call(_make_response(request_id="ok2"), stage="x", db_path=self.db_path)
        record_llm_failure(
            request_id="fail1",
            provider="gemini",
            model="gemini-2.5-flash",
            stage="x",
            error_class="LLMError",
            error_message="boom",
            latency_ms=1,
            db_path=self.db_path,
        )
        self.assertAlmostEqual(failure_rate(db_path=self.db_path), 1 / 3)

    def test_cost_by_dimension_rejects_unsupported_column(self) -> None:
        with self.assertRaises(ValueError):
            cost_by_dimension("evil_column", db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
