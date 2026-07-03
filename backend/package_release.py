"""Build and package the InvoiceArchive desktop app into a ready-to-hand-over folder + zip.

Run from anywhere (uses absolute paths), with the backend venv's Python:

    backend\\.venv\\Scripts\\python.exe backend\\package_release.py
    # full build: vite build -> PyInstaller -> assemble release/ -> zip

    ... package_release.py --skip-build      # assemble only (reuse existing exe)
    ... package_release.py --no-frontend     # skip vite build (reuse frontend/dist)

Output:
    release/InvoiceArchive/        ready-to-ship folder (exe + .env + secrets/ + README.txt)
    release/InvoiceArchive.zip     zipped for sharing
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import zipfile
from pathlib import Path


def _force_remove(func, path, _exc) -> None:
    """rmtree handler: clear the read-only bit (the SA JSON ships read-only) and retry.

    If the file is still locked (commonly: the packaged exe is currently running),
    surface a clear message instead of a cryptic PermissionError.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except PermissionError as exc:
        raise SystemExit(
            f"Unable to delete {path}\n"
            "The file may be in use. Close the running InvoiceArchive.exe "
            "(the black console window), then package again."
        ) from exc

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
DIST = BACKEND / "dist"
EXE = DIST / "InvoiceArchive.exe"
SECRETS_SRC = BACKEND / "secrets" / "gemini-service-account.json"
SOURCE_DB = REPO / "data" / "invoices.sqlite3"
RELEASE_ROOT = REPO / "release"
RELEASE_DIR = RELEASE_ROOT / "InvoiceArchive"
RELEASE_ZIP = RELEASE_ROOT / "InvoiceArchive.zip"

# Rule / config / reference tables that MUST ship in the seed database. Every
# other table (invoice records, extraction results, uploaded-file jobs, exports,
# telemetry, learned history) is wiped so the distributed copy carries ONLY the
# rules. Whitelist on purpose: any unknown/new table defaults to cleared, so no
# invoice data can leak by accident.
SEED_KEEP_TABLES = {
    "suppliers",                     # supplier data
    "schemes",                       # schemes, including prompt / return fields / export columns
    "prompt_tags",                   # tag
    "supplier_scheme_map",           # supplier-to-scheme bindings
    "supplier_tag_map",              # supplier-to-tag bindings
    "supplier_auto_archive_checks",  # auto-archive checks
    "special_document_rules",        # special document rules
    "supplier_expense_type_history",  # supplier expense-type learning history, shared as a warm start
    "schema_migrations",             # migration state, retained so first launch does not rerun migrations
}

ENV_TEMPLATE = (
    "# InvoiceArchive runtime configuration. Keep this file next to the exe.\n"
    "# Service-account credentials are loaded from the sibling secrets/gemini-service-account.json file.\n"
    "GOOGLE_CLOUD_PROJECT=test-project\n"
    "GOOGLE_CLOUD_LOCATION=global\n"
    "# If the port is already in use, uncomment the next line and choose another port:\n"
    "# INVOICE_PORT=8001\n"
)

USER_GUIDE = """InvoiceArchive User Guide
============================

Start
1. Double-click InvoiceArchive.exe.
2. A black console window opens in the background. Keep it open while using the app.
3. After a few seconds, your browser should open http://127.0.0.1:8000.
   If it does not open automatically, paste that URL into your browser.

Exit
- Close the black console window to stop the app.

Included Rules
- Supplier data and recognition rules are preloaded. Invoice records start empty.

Where Your Data Lives
- The data folder next to the exe stores the database, invoices, and uploaded files.
- To back up or move computers, copy the full data folder.

Do Not Delete
- The sibling secrets folder and .env file are required at runtime. Do not delete or rename them.

First-Run Notes
- Windows may show a security warning or unknown-publisher prompt. Choose the option to run anyway.
- Antivirus software may flag single-file packaged apps. Add this app to the trusted list if needed.

Troubleshooting
- If recognition fails or the app will not open, Shift-right-click inside this folder, choose "Open PowerShell here",
  then run .\\InvoiceArchive.exe --selftest to check credentials and network access.
- If the port is already in use, open .env in Notepad, remove the # before "# INVOICE_PORT=8001", save, and restart.
"""


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}\n  (cwd={cwd})")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def build_frontend() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm was not found. Install Node.js or use --no-frontend to reuse an existing frontend/dist.")
    run([npm, "run", "build"], cwd=FRONTEND)


def build_exe() -> None:
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit(
            "PyInstaller is not installed. Run this first:\n"
            f"    {sys.executable} -m pip install pyinstaller"
        )
    run(
        [sys.executable, "-m", "PyInstaller", "build_exe.spec",
         "--noconfirm", "--distpath", "dist", "--workpath", "build"],
        cwd=BACKEND,
    )


def build_seed_db(dest_dir: Path) -> None:
    """Ship a seed DB with only the rules: copy the dev DB, wipe invoice/runtime tables.

    Keeps SEED_KEEP_TABLES (rules, schemes, suppliers, bindings, migration state);
    clears invoice records, extraction results, uploaded-file jobs, exports and
    telemetry. VACUUM rewrites the file so wiped invoice data is physically gone.
    """
    if not SOURCE_DB.is_file():
        print(f"  ! Seed database not found: {SOURCE_DB}; skipping seed database. Users will start with an empty database.")
        return

    data_dir = dest_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dest_db = data_dir / "invoices.sqlite3"
    if dest_db.exists():
        dest_db.unlink()

    # Consistent snapshot even if the app currently has the source DB open.
    src = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    con = sqlite3.connect(dest_db)
    try:
        src.backup(con)
    finally:
        src.close()

    try:
        con.execute("PRAGMA foreign_keys=OFF")
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        has_seq = "sqlite_sequence" in tables
        cleared: list[str] = []
        for table in tables:
            if table in SEED_KEEP_TABLES or table.startswith("sqlite_"):
                continue
            con.execute(f'DELETE FROM "{table}"')
            # Reset AUTOINCREMENT so user IDs start at 1 — EXCEPT invoices: the kept
            # supplier_expense_type_history still references old invoice ids, so keep
            # the counter high so new invoices never collide with that warm-start data.
            if has_seq and table != "invoices":
                con.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
            cleared.append(table)
        con.commit()
        con.execute("VACUUM")
        con.commit()
        kept = sorted(t for t in tables if t in SEED_KEEP_TABLES)
    finally:
        con.close()

    print("  Seed database -> data/invoices.sqlite3")
    print(f"    Kept (rules): {kept}")
    print(f"    Cleared (invoice/runtime data): {sorted(cleared)}")


def assemble() -> None:
    if not EXE.is_file():
        raise SystemExit(f"Could not find {EXE}. Build it first (remove --skip-build).")
    if not SECRETS_SRC.is_file():
        raise SystemExit(f"Could not find service-account credentials: {SECRETS_SRC}")

    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR, onexc=_force_remove)
    RELEASE_DIR.mkdir(parents=True)

    shutil.copy2(EXE, RELEASE_DIR / EXE.name)
    (RELEASE_DIR / "secrets").mkdir()
    shutil.copy2(SECRETS_SRC, RELEASE_DIR / "secrets" / "gemini-service-account.json")
    (RELEASE_DIR / ".env").write_text(ENV_TEMPLATE, encoding="utf-8")
    (RELEASE_DIR / "README.txt").write_text(USER_GUIDE, encoding="utf-8")
    build_seed_db(RELEASE_DIR)

    if RELEASE_ZIP.exists():
        RELEASE_ZIP.unlink()
    with zipfile.ZipFile(RELEASE_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(RELEASE_DIR.rglob("*")):
            zf.write(path, path.relative_to(RELEASE_ROOT))

    size_mb = RELEASE_ZIP.stat().st_size / (1024 * 1024)
    print("\n==== Packaging complete ====")
    print(f"Folder: {RELEASE_DIR}")
    print(f"Zip: {RELEASE_ZIP}  ({size_mb:.0f} MB)")
    print("Send the full InvoiceArchive folder or zip to the user; they can start it by double-clicking InvoiceArchive.exe.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Package InvoiceArchive desktop app.")
    parser.add_argument("--skip-build", action="store_true", help="Assemble only; reuse the existing built exe.")
    parser.add_argument("--no-frontend", action="store_true", help="Skip the frontend build and reuse frontend/dist.")
    args = parser.parse_args()

    if not args.skip_build:
        if not args.no_frontend:
            build_frontend()
        build_exe()
    assemble()


if __name__ == "__main__":
    main()
