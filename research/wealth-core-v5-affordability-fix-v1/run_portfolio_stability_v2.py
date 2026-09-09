#!/usr/bin/env python3
"""Filesystem-only launcher for the V5 portfolio stability replay.

The frozen generated economic source creates ``$GITHUB_WORKSPACE/final-output/engine``
at import time with ``parents=False``. The V4 workflow happened to establish that
parent through its canonical launcher path. The isolated V5 runner executes the
generated source directly, so establish the inherited parent before delegating.
No generated source or economic parameter is modified here.
"""
from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
    (workspace / "final-output").mkdir(parents=True, exist_ok=True)

    from run_portfolio_stability import main as run

    return int(run())


if __name__ == "__main__":
    raise SystemExit(main())
