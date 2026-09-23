#!/usr/bin/env python3
"""Verify audit hash chain integrity."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audit.log_store import AuditLogStore

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _PROJECT_ROOT / "data" / "audit.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify hash-chained audit log")
    parser.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"Path to SQLite audit database (default: {_DEFAULT_DB})",
    )
    args = parser.parse_args()
    store = AuditLogStore(args.db)
    ok = store.verify_chain()
    if ok:
        print("OK: audit chain verified")
        return 0
    print("FAIL: audit chain broken", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
