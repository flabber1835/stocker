#!/usr/bin/env python3
"""Bounded checkpoint equivalence launcher with canonical daily serialization."""
from __future__ import annotations

from pathlib import Path
import runpy
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Import the existing launcher without executing its __main__ block.
ns = runpy.run_path(str(Path(__file__).with_name("run_checkpoint_equivalence_base.py")))
checkpoint_runner = ns["checkpoint_runner"]
runner = ns["runner"]

from backtester.checkpoint_output_schema import install  # noqa: E402

install(checkpoint_runner)


if __name__ == "__main__":
    raise SystemExit(checkpoint_runner.run(runner))
