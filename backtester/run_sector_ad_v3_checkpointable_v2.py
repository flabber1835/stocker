#!/usr/bin/env python3
"""Checkpoint-capable A/D v3 launcher with canonical daily serialization."""
from __future__ import annotations

from pathlib import Path
import runpy
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Load the existing checkpoint-capable v3 launcher without executing its main.
ns = runpy.run_path(str(Path(__file__).with_name("run_sector_ad_v3_checkpointable.py")))
checkpoint_runner = ns["checkpoint_runner"]
main = ns["main"]

from backtester.checkpoint_output_schema import install  # noqa: E402

install(checkpoint_runner)


if __name__ == "__main__":
    raise SystemExit(main())
