"""Launch the TCL Finance & Billing web UI.

    python web.py                 # http://127.0.0.1:8000
    python web.py --port 9000 --host 0.0.0.0

A clean browser chat interface in front of the same agent stack as chat.py:
plain-English answers, RCA, DBA diagnostics, and approval-gated writes with
Approve / Cancel buttons. Requires a populated .env (DB_* + OPENAI_API_KEY).
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

# Ensure the project root is importable when run as `python web.py`.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv()


def main() -> None:
    ap = argparse.ArgumentParser(description="TCL Finance & Billing web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = ap.parse_args()

    import uvicorn

    url = f"http://{args.host}:{args.port}"
    print("=" * 64)
    print("  TCL Finance & Billing — Web Assistant")
    print(f"  Open your browser at:  {url}")
    print("  Press Ctrl+C to stop.")
    print("=" * 64)

    uvicorn.run("src.web.app:app", host=args.host, port=args.port,
                reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
