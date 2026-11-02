"""Entry point for the scheduled-report worker.

    python -m app.email_worker            # loop until stopped
    python -m app.email_worker --once     # one cycle, for cron or a smoke test

The implementation lives in `app.services.email_worker`; this module exists so
the documented command works and a deployment only needs to start one process.
"""
from .services.email_worker import main

if __name__ == "__main__":
    raise SystemExit(main())
