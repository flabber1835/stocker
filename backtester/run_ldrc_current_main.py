#!/usr/bin/env python3
"""Bind the corrected chronological replay to the exact main checkout for this run.

The retained comparison module predates the current Production ownership split and
still contains a historical source constant. The workflow resolves ``main`` once,
checks it out read-only, and exports that immutable SHA as BACKTESTER_MAIN_SHA.
This launcher propagates that exact identity through every retained replay seam
before any session is processed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtester.run_ldrc_corrected_warmup_cash as corrected

_SHA = re.compile(r"^[0-9a-f]{40}$")


def bind_run_start_main() -> str:
    sha = os.environ.get("BACKTESTER_MAIN_SHA", "").strip()
    if not _SHA.fullmatch(sha):
        raise RuntimeError("BACKTESTER_MAIN_SHA must be the exact 40-hex run-start main SHA")

    root_text = os.environ.get("BACKTESTER_MAIN_ROOT", "").strip()
    if not root_text:
        raise RuntimeError("BACKTESTER_MAIN_ROOT is required")
    root = Path(root_text).resolve()

    # The compatibility modules must actually have loaded from the immutable
    # checkout whose SHA we are about to certify. A sys.path leak would otherwise
    # let the identity say one revision while Python executes another.
    for module in (corrected.prod.production_kernel, corrected.prod.production):
        source = Path(module.__file__).resolve()
        if root not in source.parents:
            raise RuntimeError(
                f"Production module escaped exact run-start checkout: {source} not under {root}"
            )

    corrected.prod.EXPECTED_MAIN_SHA = sha
    corrected.runner.EXPECTED_MAIN_SHA = sha
    return sha


def main() -> int:
    sha = bind_run_start_main()
    print(f"[RUN] chronological Production source bound to run-start main={sha}", flush=True)
    return int(corrected.main())


if __name__ == "__main__":
    raise SystemExit(main())
