"""Admin command: prune the session quarantine directory.

Quarantined session JSONs accumulate under ``backend/sessions/_quarantine/``
whenever a corrupt session file is moved aside (see
``SessionStore._quarantine_corrupt_file``). They are never overwritten by the
runtime, so without retention the directory grows unbounded.

Usage:
    python -m backend.scripts.prune_quarantine
    python -m backend.scripts.prune_quarantine --base-dir PATH
    python -m backend.scripts.prune_quarantine --max-age-days 30

Default retention is 7 days, matching ``QUARANTINE_RETENTION_SECONDS`` in
``graph.session.session_store``. Files whose name does not match the
``{int(time.time())}_{session_id}.json`` pattern produced by quarantine are
skipped.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from graph.session.session_store import (  # noqa: E402
    QUARANTINE_RETENTION_SECONDS,
    SessionStore,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=BACKEND_ROOT,
        help="Backend root that contains sessions/_quarantine (default: %(default)s)",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=QUARANTINE_RETENTION_SECONDS / 86400,
        help="Delete files older than this many days (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    max_age_seconds = int(args.max_age_days * 86400)
    store = SessionStore(args.base_dir)
    removed = store.prune_quarantine(max_age_seconds=max_age_seconds)
    print(
        f"prune_quarantine: removed {removed} file(s) older than "
        f"{args.max_age_days} day(s) from {store.quarantine_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
