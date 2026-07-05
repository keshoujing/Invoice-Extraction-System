"""Build the offline demo-data snapshot.

Produces `demo-data/` (a ready-to-copy `data/` directory: seed SQLite DB + invoice
files) from the committed synthetic sample set. No LLM calls -- fields come straight
from the ground truth -- so the snapshot is deterministic and reproducible.

`docker compose --profile demo-data up` copies this into the app's data volume, so a
reviewer sees a populated app (recognized suppliers, confirmed invoices, exportable
records) without needing any Google Cloud credentials.

    python scripts/build_demo_snapshot.py
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "evaluation" / "scripts"))

from eval_lib import flatten_gt, map_ground_truth, parse_money  # noqa: E402
from supplier_master import build_master, expected_code, parse_company_name  # noqa: E402

DEMO = REPO / "demo-data"
DEMO_CONTAINER_DATA = Path("/app/data")
SRC = REPO / "evaluation" / "invoices-donut-demo"
N_CONFIRMED = 12
N_PENDING = 4

NOW = dt.datetime.now().replace(microsecond=0).isoformat()


def _iso_date(value: str) -> str:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def insert_row(cur, table: str, values: dict) -> int:
    """Insert `values` into `table`, filling required columns we omitted."""
    info = cur.execute(f"PRAGMA table_info({table})").fetchall()
    cols, params = [], []
    for col in info:
        name, notnull, default, pk = col["name"], col["notnull"], col["dflt_value"], col["pk"]
        if name in values:
            cols.append(name)
            params.append(values[name])
        elif pk:
            continue  # autoincrement primary key
        elif notnull and default is None:
            cols.append(name)
            params.append(NOW if name.endswith("_at") else "")
    placeholders = ",".join("?" * len(cols))
    cur.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({placeholders})", params)
    return int(cur.lastrowid)


def load_records() -> list[dict]:
    path = SRC / "ground_truth.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build() -> None:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    confirmed_dir = DEMO / "uploads" / "confirmed"
    pending_dir = DEMO / "uploads" / "pending"
    confirmed_dir.mkdir(parents=True)
    pending_dir.mkdir(parents=True)

    # Point the app's DB layer at the snapshot before importing/initializing it.
    import app.database as db

    db.DB_PATH = DEMO / "invoices.sqlite3"
    db.init_db()

    records = load_records()
    sellers = [flatten_gt(r["ground_truth"]["gt_parse"]).get("seller", "") for r in records]
    master, by_name = build_master(sellers)

    from app.database import db_cursor, upsert_extracted_data

    with db_cursor() as cur:
        for code, name in master:
            insert_row(cur, "suppliers", {"code": code, "name": name})

        for idx, rec in enumerate(records[: N_CONFIRMED + N_PENDING]):
            gt = map_ground_truth(rec["ground_truth"]["gt_parse"])
            seller = sellers[idx]
            company = parse_company_name(seller)
            vendor_code = expected_code(seller, by_name)
            total = parse_money(gt["total_amount"]) or 0.0
            confirmed = idx < N_CONFIRMED
            stored = f"{vendor_code}_{idx + 1:03d}.png"
            target_dir = confirmed_dir if confirmed else pending_dir
            container_dir = DEMO_CONTAINER_DATA / "uploads" / ("confirmed" if confirmed else "pending")
            shutil.copy2(SRC / rec["file"], target_dir / stored)

            row = {
                "original_filename": Path(rec["file"]).name,
                "stored_filename": stored,
                "file_path": str(container_dir / stored),
                "mime_type": "image/png",
                "status": "confirmed" if confirmed else "pending",
                "uploaded_at": NOW,
                "updated_at": NOW,
                "recognized_at": NOW if confirmed else None,
                "confirmed_at": NOW if confirmed else None,
                "vendor_code": vendor_code,
                "vendor_name": company,
                "po_number": "",
                "invoice_number": gt["invoice_number"],
                "invoice_date": gt["invoice_date"],
                "invoice_date_iso": _iso_date(gt["invoice_date"]),
                "total_amount": total,
                "expense_type": "",
                "invoice_category": "",
            }
            invoice_id = insert_row(cur, "invoices", row)
            upsert_extracted_data(
                cur,
                invoice_id,
                {
                    "vendor_name": company,
                    "vendor_code": vendor_code,
                    "Is_Invoice": "True",
                    "document_is_invoice": "True",
                    "document_type": "invoice",
                    "vendor_matched": "True",
                    "vendor_match_confidence": 1.0,
                    "invoice_type": "Invoice",
                    "PO_number": "",
                    "invoice_number": gt["invoice_number"],
                    "invoice_date": gt["invoice_date"],
                    "commodity_amount": total,
                    "freight_amount": 0.0,
                    "tax_amount": 0.0,
                    "total_amount": total,
                },
            )

    (pending_dir / ".gitkeep").touch()
    print(f"snapshot built at {DEMO.relative_to(REPO)}")
    print(f"  suppliers: {len(master)}")
    print(f"  invoices:  {N_CONFIRMED} confirmed + {N_PENDING} pending")


if __name__ == "__main__":
    build()
