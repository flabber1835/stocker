#!/usr/bin/env python3
"""Bounded base-runner launcher used only to certify checkpoint equivalence."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


root = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
sys.path.insert(0, str(root))

from backtester import checkpoint_runner  # noqa: E402


base = root / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
spec = importlib.util.spec_from_file_location("checkpoint_equivalence_base", base)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {base}")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.EXPERIMENT_ID = "2026-08-28-checkpoint-equivalence"
runner.END_SESSION = os.environ.get("BACKTESTER_CHECKPOINT_EQUIV_END", "1998-06-30")
runner.MEASUREMENT_WINDOWS = {}
runner.print = print


if __name__ == "__main__":
    raise SystemExit(checkpoint_runner.run(runner))
