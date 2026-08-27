#!/usr/bin/env python3
"""Cheap GET-only paper-account preflight for dual-run GO validation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402

TARGETS = ("SHADOW", "DUAL_RUN_OBSERVATION", "HISTORICAL_PAPER_EXECUTION")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--target", choices=TARGETS,
        default=os.environ.get("SENTINEL_GO_TARGET", "DUAL_RUN_OBSERVATION"))
    args, _remaining = parser.parse_known_args(
        list(argv if argv is not None else sys.argv[1:]))
    target = args.target
    if target == "SHADOW":
        print("paper account preflight: SKIPPED for SHADOW target", flush=True)
        return 0

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
