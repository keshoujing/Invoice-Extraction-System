from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import DB_PATH, SUPPLIER_FILE as DEFAULT_SUPPLIER_FILE, ensure_directories


ORIGINAL_DB_PATH = DB_PATH
ORIGINAL_SUPPLIER_FILE = DEFAULT_SUPPLIER_FILE


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_cursor() -> Iterable[sqlite3.Cursor]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    ensure_directories()
    db_existed = DB_PATH.exists()
    conn = get_connection()
    try:
        cur = conn.cursor()
        _create_base_schema(cur)
        conn.commit()

        pending = _pending_migrations(cur)
        if pending and db_existed:
            _backup_database(conn)

        for version, name, migrate in pending:
            migrate(cur)
            cur.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (version, name, now_iso()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


Migration = tuple[str, str, Callable[[sqlite3.Cursor], None]]


def _create_base_schema(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            uploaded_at TEXT NOT NULL,
            recognized_at TEXT,
            confirmed_at TEXT,
            updated_at TEXT NOT NULL,
            error_message TEXT,
            vendor_code TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            po_number TEXT DEFAULT '',
            invoice_number TEXT DEFAULT '',
            invoice_date TEXT DEFAULT '',
            invoice_date_iso TEXT DEFAULT '',
            total_amount REAL DEFAULT 0,
            expense_type TEXT DEFAULT '',
            invoice_category TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS extracted_data (
            invoice_id INTEGER PRIMARY KEY,
            data_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS recognition_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            total INTEGER NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0,
            succeeded INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS recognition_job_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            invoice_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            error_message TEXT,
            result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES recognition_jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS upload_preview_jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            total INTEGER NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0,
            succeeded INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS upload_preview_job_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            invoice_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES upload_preview_jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS export_batches (
            id TEXT PRIMARY KEY,
            destination_dir TEXT NOT NULL,
            prefix TEXT NOT NULL,
            start_number INTEGER NOT NULL,
            number_width INTEGER NOT NULL,
            filters_json TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            excel_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS export_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            invoice_id INTEGER NOT NULL,
            archive_number TEXT NOT NULL,
            exported_filename TEXT NOT NULL,
            exported_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES export_batches(id) ON DELETE CASCADE,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS prompt_tags (
            tag_name TEXT PRIMARY KEY,
            prompt_body TEXT NOT NULL DEFAULT '',
            fields_json TEXT NOT NULL,
            export_settings_json TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS supplier_tag_map (
            vendor_code TEXT PRIMARY KEY,
            tag_name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(tag_name) REFERENCES prompt_tags(tag_name) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS special_document_rules (
            vendor_code TEXT PRIMARY KEY,
            vendor_name TEXT NOT NULL DEFAULT '',
            prompt_body TEXT NOT NULL DEFAULT '',
            fields_json TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schemes (
            name TEXT PRIMARY KEY,
            preview_prompt_body TEXT NOT NULL DEFAULT '',
            preview_prompt_enabled INTEGER NOT NULL DEFAULT 0,
            prompt_body TEXT NOT NULL DEFAULT '',
            fields_json TEXT NOT NULL,
            export_settings_json TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS supplier_scheme_map (
            vendor_code TEXT PRIMARY KEY,
            scheme_name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(vendor_code) REFERENCES suppliers(code) ON DELETE CASCADE,
            FOREIGN KEY(scheme_name) REFERENCES schemes(name) ON DELETE CASCADE ON UPDATE CASCADE
        );

        CREATE TABLE IF NOT EXISTS supplier_expense_type_history (
            invoice_id INTEGER PRIMARY KEY,
            vendor_code TEXT NOT NULL,
            expense_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            selected_at TEXT NOT NULL,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS supplier_auto_archive_checks (
            vendor_code TEXT NOT NULL,
            field_key TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            baseline_value TEXT NOT NULL DEFAULT '',
            tolerance_percent TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(vendor_code, field_key),
            FOREIGN KEY(vendor_code) REFERENCES suppliers(code) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS llm_calls (
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

        CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
        CREATE INDEX IF NOT EXISTS idx_invoices_confirmed_at ON invoices(confirmed_at);
        CREATE INDEX IF NOT EXISTS idx_invoices_invoice_date_iso ON invoices(invoice_date_iso);
        CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor_name, vendor_code);
        CREATE INDEX IF NOT EXISTS idx_upload_preview_job_items_job ON upload_preview_job_items(job_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_prompt_tags_default ON prompt_tags(is_default, tag_name);
        CREATE INDEX IF NOT EXISTS idx_supplier_tag_map_tag ON supplier_tag_map(tag_name);
        CREATE INDEX IF NOT EXISTS idx_special_document_rules_active
            ON special_document_rules(is_active, vendor_name);
        CREATE INDEX IF NOT EXISTS idx_schemes_default ON schemes(is_default, name);
        CREATE INDEX IF NOT EXISTS idx_supplier_scheme_map_scheme ON supplier_scheme_map(scheme_name);
        CREATE INDEX IF NOT EXISTS idx_supplier_expense_type_history_vendor
            ON supplier_expense_type_history(vendor_code, selected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_supplier_auto_archive_checks_vendor
            ON supplier_auto_archive_checks(vendor_code);

        CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
        CREATE INDEX IF NOT EXISTS idx_llm_calls_model_ts ON llm_calls(model, ts);
        CREATE INDEX IF NOT EXISTS idx_llm_calls_supplier_ts ON llm_calls(supplier_code, ts);
        CREATE INDEX IF NOT EXISTS idx_llm_calls_stage_ts ON llm_calls(stage, ts);
        """
    )


def _pending_migrations(cur: sqlite3.Cursor) -> list[Migration]:
    applied = {
        row["version"]
        for row in cur.execute("SELECT version FROM schema_migrations").fetchall()
    }
    return [migration for migration in MIGRATIONS if migration[0] not in applied]


def _backup_database(conn: sqlite3.Connection) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.with_name(f"{DB_PATH.name}.backup_{timestamp}_before_migration")
    backup_conn = sqlite3.connect(backup_path)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    return backup_path


def _table_has_column(cur: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    return any(row["name"] == column_name for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall())


def _table_exists(cur: sqlite3.Cursor, table_name: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _migration_001_add_invoice_category(cur: sqlite3.Cursor) -> None:
    if not _table_has_column(cur, "invoices", "invoice_category"):
        cur.execute("ALTER TABLE invoices ADD COLUMN invoice_category TEXT DEFAULT ''")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_category ON invoices(invoice_category)")


def _migration_002_add_prompt_tag_export_settings(cur: sqlite3.Cursor) -> None:
    if not _table_has_column(cur, "prompt_tags", "export_settings_json"):
        cur.execute("ALTER TABLE prompt_tags ADD COLUMN export_settings_json TEXT NOT NULL DEFAULT ''")


def _migration_003_add_supplier_expense_type_history(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_expense_type_history (
            invoice_id INTEGER PRIMARY KEY,
            vendor_code TEXT NOT NULL,
            expense_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            selected_at TEXT NOT NULL,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_supplier_expense_type_history_vendor
            ON supplier_expense_type_history(vendor_code, selected_at DESC);
        """
    )
    cur.execute(
        """
        INSERT INTO supplier_expense_type_history(invoice_id, vendor_code, expense_type, source, selected_at)
        SELECT id,
            TRIM(vendor_code),
            TRIM(expense_type),
            'backfill',
            COALESCE(confirmed_at, recognized_at, updated_at, uploaded_at)
        FROM invoices
        WHERE TRIM(COALESCE(vendor_code, '')) <> ''
            AND TRIM(COALESCE(expense_type, '')) <> ''
        ON CONFLICT(invoice_id) DO UPDATE SET
            vendor_code = excluded.vendor_code,
            expense_type = excluded.expense_type,
            selected_at = excluded.selected_at
        """
    )


def _migration_004_add_special_document_rules(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS special_document_rules (
            vendor_code TEXT PRIMARY KEY,
            vendor_name TEXT NOT NULL DEFAULT '',
            prompt_body TEXT NOT NULL DEFAULT '',
            fields_json TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_special_document_rules_active
            ON special_document_rules(is_active, vendor_name);
        """
    )


def _migration_005_add_llm_calls(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS llm_calls (
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

        CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
        CREATE INDEX IF NOT EXISTS idx_llm_calls_model_ts ON llm_calls(model, ts);
        CREATE INDEX IF NOT EXISTS idx_llm_calls_supplier_ts ON llm_calls(supplier_code, ts);
        CREATE INDEX IF NOT EXISTS idx_llm_calls_stage_ts ON llm_calls(stage, ts);
        """
    )


def _migration_006_add_review_labels(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS review_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            confirmed_at TEXT NOT NULL,
            source_status TEXT NOT NULL,
            model_output_json TEXT NOT NULL,
            user_confirmed_json TEXT NOT NULL,
            fields_changed_json TEXT NOT NULL,
            was_corrected INTEGER NOT NULL,
            supplier_code TEXT,
            supplier_name TEXT,
            prompt_tag TEXT,
            document_type TEXT,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_review_confirmations_invoice
            ON review_confirmations(invoice_id, confirmed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_review_confirmations_supplier
            ON review_confirmations(supplier_code, confirmed_at DESC);
        """
    )


def _migration_007_simplify_hitl_review_confirmations(cur: sqlite3.Cursor) -> None:
    cur.execute("DROP TABLE IF EXISTS review_confirmations_lite")
    cur.executescript(
        """
        CREATE TABLE review_confirmations_lite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            confirmed_at TEXT NOT NULL,
            source_status TEXT NOT NULL,
            model_output_json TEXT NOT NULL,
            user_confirmed_json TEXT NOT NULL,
            fields_changed_json TEXT NOT NULL,
            was_corrected INTEGER NOT NULL,
            supplier_code TEXT,
            supplier_name TEXT,
            prompt_tag TEXT,
            document_type TEXT,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        );
        """
    )
    if _table_exists(cur, "review_confirmations"):
        existing_columns = {
            row["name"]
            for row in cur.execute("PRAGMA table_info(review_confirmations)").fetchall()
        }
        expected_columns = {
            "id",
            "invoice_id",
            "confirmed_at",
            "source_status",
            "model_output_json",
            "user_confirmed_json",
            "fields_changed_json",
            "was_corrected",
            "supplier_code",
            "supplier_name",
            "prompt_tag",
            "document_type",
        }
        if expected_columns.issubset(existing_columns):
            cur.execute(
                """
                INSERT INTO review_confirmations_lite(
                    id, invoice_id, confirmed_at, source_status, model_output_json,
                    user_confirmed_json, fields_changed_json, was_corrected,
                    supplier_code, supplier_name, prompt_tag, document_type
                )
                SELECT
                    id, invoice_id, confirmed_at, source_status, model_output_json,
                    user_confirmed_json, fields_changed_json, was_corrected,
                    supplier_code, supplier_name, prompt_tag, document_type
                FROM review_confirmations
                """
            )
    cur.execute("DROP TABLE IF EXISTS review_model_snapshots")
    cur.execute("DROP TABLE IF EXISTS review_field_labels")
    cur.execute("DROP TABLE IF EXISTS review_confirmations")
    cur.execute("ALTER TABLE review_confirmations_lite RENAME TO review_confirmations")
    cur.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_review_confirmations_invoice
            ON review_confirmations(invoice_id, confirmed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_review_confirmations_supplier
            ON review_confirmations(supplier_code, confirmed_at DESC);
        """
    )


def _migration_008_add_schemes_and_suppliers(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS suppliers (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schemes (
            name TEXT PRIMARY KEY,
            prompt_body TEXT NOT NULL DEFAULT '',
            fields_json TEXT NOT NULL,
            export_settings_json TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS supplier_scheme_map (
            vendor_code TEXT PRIMARY KEY,
            scheme_name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(vendor_code) REFERENCES suppliers(code) ON DELETE CASCADE,
            FOREIGN KEY(scheme_name) REFERENCES schemes(name) ON DELETE CASCADE ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_schemes_default ON schemes(is_default, name);
        CREATE INDEX IF NOT EXISTS idx_supplier_scheme_map_scheme ON supplier_scheme_map(scheme_name);
        """
    )


def _iter_supplier_file_rows(path: Path) -> Iterable[tuple[str, str]]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0].strip()
        name = parts[1].strip()
        if not code or not name:
            continue
        if "vendor" in code.lower() or "vendor" in name.lower():
            continue
        yield code, name


def _should_rename_supplier_file(path: Path) -> bool:
    return DB_PATH == ORIGINAL_DB_PATH or path != ORIGINAL_SUPPLIER_FILE


def _migration_009_migrate_prompt_data(cur: sqlite3.Cursor) -> None:
    from .services import supplier_matcher as supplier_matcher_module

    timestamp = now_iso()
    supplier_file = supplier_matcher_module.SUPPLIER_FILE

    if supplier_file.exists():
        for code, name in _iter_supplier_file_rows(supplier_file):
            cur.execute(
                """
                INSERT OR IGNORE INTO suppliers (code, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (code, name, timestamp, timestamp),
            )
        if _should_rename_supplier_file(supplier_file):
            suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            supplier_file.rename(supplier_file.with_suffix(f".txt.imported_{suffix}"))

    cur.execute(
        """
        INSERT OR IGNORE INTO schemes
            (name, prompt_body, fields_json, export_settings_json, is_default, created_at, updated_at)
        SELECT tag_name, prompt_body, fields_json, export_settings_json, is_default, created_at, updated_at
        FROM prompt_tags
        """
    )

    cur.execute(
        """
        INSERT OR IGNORE INTO supplier_scheme_map (vendor_code, scheme_name, updated_at)
        SELECT m.vendor_code, m.tag_name, m.updated_at
        FROM supplier_tag_map m
        INNER JOIN suppliers s ON s.code = m.vendor_code
        INNER JOIN schemes sc ON sc.name = m.tag_name
        """
    )

    rules = cur.execute(
        """
        SELECT vendor_code, vendor_name, prompt_body, fields_json, is_active, created_at, updated_at
        FROM special_document_rules
        WHERE is_active = 1
        """
    ).fetchall()
    existing_names = {row[0] for row in cur.execute("SELECT name FROM schemes").fetchall()}
    for row in rules:
        vendor_code, vendor_name, prompt_body, fields_json, _is_active, created_at, updated_at = row
        clean_code = str(vendor_code or "").strip()
        clean_name = str(vendor_name or "").strip()
        if not clean_code:
            continue
        if clean_name:
            cur.execute(
                """
                INSERT OR IGNORE INTO suppliers (code, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (clean_code, clean_name, created_at or timestamp, updated_at or timestamp),
            )
        base_name = clean_name or clean_code
        candidate = base_name
        suffix = 1
        while candidate in existing_names:
            candidate = f"{base_name} ({clean_code})" if suffix == 1 else f"{base_name} ({clean_code})#{suffix}"
            suffix += 1
        existing_names.add(candidate)
        cur.execute(
            """
            INSERT INTO schemes (
                name, prompt_body, fields_json, export_settings_json,
                is_default, created_at, updated_at
            )
            VALUES (?, ?, ?, '', 0, ?, ?)
            """,
            (candidate, prompt_body, fields_json, created_at or timestamp, updated_at or timestamp),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO supplier_scheme_map (vendor_code, scheme_name, updated_at)
            VALUES (?, ?, ?)
            """,
            (clean_code, candidate, updated_at or timestamp),
        )


def _migration_010_add_supplier_auto_archive_checks(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_auto_archive_checks (
            vendor_code TEXT NOT NULL,
            field_key TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            baseline_value TEXT NOT NULL DEFAULT '',
            tolerance_percent TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(vendor_code, field_key),
            FOREIGN KEY(vendor_code) REFERENCES suppliers(code) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_supplier_auto_archive_checks_vendor
            ON supplier_auto_archive_checks(vendor_code);
        """
    )


def _migration_011_add_scheme_preview_prompt(cur: sqlite3.Cursor) -> None:
    if not _table_has_column(cur, "schemes", "preview_prompt_body"):
        cur.execute("ALTER TABLE schemes ADD COLUMN preview_prompt_body TEXT NOT NULL DEFAULT ''")
    if not _table_has_column(cur, "schemes", "preview_prompt_enabled"):
        cur.execute("ALTER TABLE schemes ADD COLUMN preview_prompt_enabled INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: list[Migration] = [
    ("001", "add_invoice_category", _migration_001_add_invoice_category),
    ("002", "add_prompt_tag_export_settings", _migration_002_add_prompt_tag_export_settings),
    ("003", "add_supplier_expense_type_history", _migration_003_add_supplier_expense_type_history),
    ("004", "add_special_document_rules", _migration_004_add_special_document_rules),
    ("005", "add_llm_calls", _migration_005_add_llm_calls),
    ("006", "add_review_labels", _migration_006_add_review_labels),
    ("007", "simplify_hitl_review_confirmations", _migration_007_simplify_hitl_review_confirmations),
    ("008", "add_schemes_and_suppliers", _migration_008_add_schemes_and_suppliers),
    ("009", "migrate_prompt_data", _migration_009_migrate_prompt_data),
    ("010", "add_supplier_auto_archive_checks", _migration_010_add_supplier_auto_archive_checks),
    ("011", "add_scheme_preview_prompt", _migration_011_add_scheme_preview_prompt),
]


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def get_extracted_data(invoice_id: int) -> dict[str, Any]:
    with db_cursor() as cur:
        row = cur.execute(
            "SELECT data_json FROM extracted_data WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["data_json"])
    except json.JSONDecodeError:
        return {}


def upsert_extracted_data(cur: sqlite3.Cursor, invoice_id: int, data: dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO extracted_data(invoice_id, data_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(invoice_id) DO UPDATE SET
            data_json = excluded.data_json,
            updated_at = excluded.updated_at
        """,
        (invoice_id, json.dumps(data, ensure_ascii=False), now_iso()),
    )


def path_exists(path_text: str) -> bool:
    try:
        return Path(path_text).exists()
    except OSError:
        return False
