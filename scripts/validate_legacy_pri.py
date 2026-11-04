"""Validate a legacy .pri file without changing it or importing records."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.legacy_pri import LegacyPriError, read_legacy_pri, reconcile_legacy_pri


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Path to the legacy .pri project")
    parser.add_argument("--details", action="store_true", help="Include row-indexed issue entries")
    args = parser.parse_args()
    key_text = os.environ.get("LEGACY_PRI_KEY_HEX", "")
    try:
        key = bytes.fromhex(key_text)
    except ValueError:
        parser.error("LEGACY_PRI_KEY_HEX must be a hexadecimal AES key")
    if not key:
        parser.error("Set LEGACY_PRI_KEY_HEX in the process environment before running")
    try:
        report = reconcile_legacy_pri(read_legacy_pri(args.project, key))
    except (OSError, LegacyPriError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    if not args.details:
        report.pop("issues")
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
