# PyInstaller spec for the InvoiceArchive desktop app (single-file Windows exe).
#
# Build (run from the backend/ directory, with the venv active):
#     python -m PyInstaller build_exe.spec --noconfirm
#
# Produces:  backend/dist/InvoiceArchive.exe
# Ship alongside the exe (NOT bundled): secrets/gemini-service-account.json, .env
# (the app reads those from the folder next to the exe; data/ is created there).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("../frontend/dist", "frontend_dist")]
binaries = []
hiddenimports = []

# Google SDK + auth stack: grab submodules/data they import dynamically.
for pkg in ("google.genai", "google.auth", "google.oauth2"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn picks its event loop / HTTP / lifespan implementations at runtime.
hiddenimports += collect_submodules("uvicorn")

# Conda's Python keeps the OpenSSL DLLs in <base>\Library\bin with a "-x64"
# suffix, which PyInstaller's _ssl hook does NOT pick up -> _ssl / _hashlib fail
# with "DLL load failed ... _ssl: procedure not found" on machines without conda
# on PATH. Bundle the interpreter's real OpenSSL DLLs at the exe root.
_lib_bin = Path(sys.base_prefix) / "Library" / "bin"
for _dll in ("libssl-3-x64.dll", "libcrypto-3-x64.dll", "libssl-3.dll", "libcrypto-3.dll", "libffi-8.dll"):
    _path = _lib_bin / _dll
    if _path.is_file():
        binaries.append((str(_path), "."))

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Eval dashboard / notebook deps — not needed by the runtime app.
        "streamlit",
        "altair",
        "pandas",
        "litellm",  # only imported lazily by LiteLLMClient; runtime uses GeminiClient
        "matplotlib",
        "IPython",
        "notebook",
        # GUI toolkits the app never imports. (tkinter IS needed — the export
        # folder picker uses tkinter.filedialog — so it must NOT be excluded.)
        "PyQt5",
        "PySide6",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="InvoiceArchive",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
