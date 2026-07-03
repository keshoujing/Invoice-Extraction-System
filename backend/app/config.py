from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_base_dir() -> Path:
    """Base dir for user-facing files (.env, data/, secrets/, supplier.txt).

    Packaged as a PyInstaller exe these live next to the executable; from source
    they live at the repo root. ``__file__`` is unreliable when frozen because it
    points inside PyInstaller's temporary extraction dir.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = _app_base_dir()
ENV_FILE = REPO_ROOT / ".env"
SUPPLIER_FILE = REPO_ROOT / "supplier.txt"

DATA_DIR = REPO_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PENDING_DIR = UPLOAD_DIR / "pending"
CONFIRMED_DIR = UPLOAD_DIR / "confirmed"
DB_PATH = DATA_DIR / "invoices.sqlite3"

MODEL_ID = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def frontend_dist_dir() -> Path | None:
    """Locate the built frontend (``vite build`` output), or None if absent.

    Bundled into the exe via PyInstaller ``--add-data`` it lands under _MEIPASS;
    from source it is ``frontend/dist``. When None, the API runs headless and the
    Vite dev server (:5173) serves the UI instead.
    """
    if getattr(sys, "frozen", False):
        candidate = Path(getattr(sys, "_MEIPASS", REPO_ROOT)) / "frontend_dist"
    else:
        candidate = REPO_ROOT / "frontend" / "dist"
    return candidate if candidate.is_dir() else None


def default_service_account_path() -> Path:
    """Default GC service-account location: ``secrets/`` next to the app."""
    return REPO_ROOT / "secrets" / "gemini-service-account.json"


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_directories() -> None:
    for path in (DATA_DIR, PENDING_DIR, CONFIRMED_DIR):
        path.mkdir(parents=True, exist_ok=True)


def supplier_confidence_threshold() -> float:
    raw = (os.getenv("SUPPLIER_CONFIDENCE_THRESHOLD") or "").strip()
    if not raw:
        return 0.82
    try:
        value = float(raw)
    except ValueError:
        return 0.82
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def supplier_preview_worker_count() -> int:
    return _env_int("SUPPLIER_PREVIEW_WORKERS", 2, minimum=1, maximum=5)


def supplier_preview_retry_attempts() -> int:
    return _env_int("SUPPLIER_PREVIEW_RETRY_ATTEMPTS", 5, minimum=1, maximum=5)


def supplier_preview_retry_delay_seconds() -> float:
    return _env_float("SUPPLIER_PREVIEW_RETRY_DELAY_SECONDS", 1.0, minimum=0.0, maximum=30.0)


def hitl_review_enabled() -> bool:
    return (os.getenv("HITL_REVIEW_ENABLED") or "").strip().lower() in TRUTHY_ENV_VALUES


def llm_timeout_seconds() -> float:
    raw = (
        os.getenv("GEMINI_TIMEOUT_SECONDS")
        or os.getenv("LLM_TIMEOUT_SECONDS")
        or ""
    ).strip()
    if not raw:
        return 60.0
    try:
        value = float(raw)
    except ValueError:
        return 60.0
    if value < 5:
        return 5.0
    if value > 600:
        return 600.0
    return value
