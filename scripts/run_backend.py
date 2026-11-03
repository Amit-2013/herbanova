"""Start the API server on its own.

Run from the repository root:

    python scripts/run_backend.py
    python scripts/run_backend.py --host 0.0.0.0 --port 8000 --workers 4

The backend owns the database, the session cookie, permissions and every
``/api`` route. The separate frontend process (``scripts/run_frontend.py``)
serves the single-page UI and forwards ``/api`` here, so the browser keeps one
origin and the cookie stays first-party.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Herbanova API server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (default 127.0.0.1; use 0.0.0.0 for a LAN)")
    parser.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    parser.add_argument("--workers", type=int, default=1,
                        help="worker processes (default 1; the email worker is separate)")
    parser.add_argument("--reload", action="store_true",
                        help="reload on code changes (development only)")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port,
                workers=args.workers if not args.reload else 1,
                reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
