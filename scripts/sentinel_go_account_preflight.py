#!/usr/bin/env python3
"""Cheap GET-only paper-account preflight for dual-run GO validation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402


def main() -> int:
    target = str(__import__("os").environ.get(
        "SENTINEL_GO_TARGET", "DUAL_RUN_OBSERVATION"))
    if target == "SHADOW":
        print("paper account preflight: SKIPPED for SHADOW target", flush=True)
        return 0
    if target == "HISTORICAL_PAPER_EXECUTION":
        # Historical paper certification also requires the account gate.
        pass
    elif target != "DUAL_RUN_OBSERVATION":
        print("REFUSED: unsupported GO target", file=sys.stderr)
        return 2

    gate, _subjects = go.probe_alpaca_account(
        env=go.merged_environment(),
        now_text=go._utc_text(datetime.now(timezone.utc)),
    )
    if gate.status != go.PASS:
        print(
            "REFUSED: paper account preflight is not PASS; expensive certification was not started",
            file=sys.stderr,
        )
        return 2
    print("paper account preflight: PASS (GET-only)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
