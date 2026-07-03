"""Desktop launcher for the InvoiceArchive app: start the server, open the browser.

Used as the PyInstaller entry point. Double-clicking the packaged exe runs this:
it boots uvicorn (serving both the API and the bundled UI on one port) and opens
the default browser once the server is ready. Closing the console window exits.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser


def _open_browser_when_ready(url: str) -> None:
    import urllib.request

    for _ in range(120):  # up to ~60s for cold start (first-run DB init, etc.)
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _selftest() -> int:
    """Verify the bundled Google SDK + service-account auth stack works.

    Proves google.genai / google.oauth2 / cryptography got packaged correctly and
    the credentials in secrets/ can mint a token — without a billed model call.
    Run:  InvoiceArchive.exe --selftest
    """
    from app.config import default_service_account_path, load_env_file
    from app.llm.gemini import _build_native_client

    load_env_file()
    try:
        client = _build_native_client()
    except Exception as exc:  # noqa: BLE001
        print(f"SELFTEST FAILED (client build): {type(exc).__name__}: {exc}")
        return 1
    print(f"SELFTEST: native client OK -> vertexai={getattr(client, 'vertexai', '?')}")
    try:
        import google.auth.transport.requests as gr
        from google.oauth2 import service_account

        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or str(default_service_account_path())
        creds = service_account.Credentials.from_service_account_file(
            cred_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(gr.Request())
        print(f"SELFTEST: token mint OK -> project={creds.project_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"SELFTEST FAILED (token mint): {type(exc).__name__}: {exc}")
        return 1
    try:
        import tkinter

        _root = tkinter.Tk()
        _root.destroy()
        print("SELFTEST: tkinter OK (export folder picker available)")
    except Exception as exc:  # noqa: BLE001
        print(f"SELFTEST FAILED (tkinter): {type(exc).__name__}: {exc}")
        return 1
    print("SELFTEST: PASS")
    return 0


def main() -> None:
    # From source, make the sibling ``app`` package importable. When frozen,
    # PyInstaller already wires the bundled package onto the import path.
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())

    # Load .env (next to the exe) first, so INVOICE_HOST/PORT overrides apply.
    from app.config import load_env_file

    load_env_file()
    host = os.getenv("INVOICE_HOST", "127.0.0.1")
    port = int(os.getenv("INVOICE_PORT", "8000"))
    url = f"http://{host}:{port}"

    import uvicorn

    from app.main import app as fastapi_app

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    print(
        f"\nInvoiceArchive started: {url}\n"
        "The browser should open automatically; if it does not, open the URL above manually.\n"
        "Close this window to stop the app.\n"
    )
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
