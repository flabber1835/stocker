#!/usr/bin/env python3
"""Cheap host prerequisites required by production GO reuse and promotion."""
from __future__ import annotations

from pathlib import Path
import sys

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def main() -> int:
    try:
        value = BOOT_ID.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        value = ""
    if not value:
        print(
            "REFUSED: host boot identity is unavailable; GO certification reuse/promotion cannot be safely bound",
            file=sys.stderr,
        )
        return 2
    # Never print the boot identity itself.
    print("host GO identity preflight: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
