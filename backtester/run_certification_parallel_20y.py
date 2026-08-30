#!/usr/bin/env python3
"""Parallel strict-PIT certification for 2006-07-31 through 2026-07-31."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pandas as pd

import backtester.run_certification_parallel as base

WARMUP_START = pd.Timestamp("2006-01-03")
MEASUREMENT_START = pd.Timestamp("2006-07-31")
PRODUCTION_WRAPPER = Path("backtester/run_production_strict_pit_20y.py")
RESEARCH_WRAPPER = Path("backtester/run_research_strict_pit_20y.py")


def _consume_end_session() -> str:
    args = list(sys.argv[1:])
    end = "2026-07-31"
    if "--end-session" in args:
        i = args.index("--end-session")
        try:
            end = args[i + 1]
        except IndexError as exc:
            raise RuntimeError("--end-session requires YYYY-MM-DD") from exc
        del args[i : i + 2]
    sys.argv = [sys.argv[0], *args]
    return end


def main() -> int:
    end = _consume_end_session()
    os.environ["CERTIFICATION_END_SESSION"] = end
    os.environ["CERTIFICATION_WARMUP_START"] = WARMUP_START.date().isoformat()
    os.environ["CERTIFICATION_MEASUREMENT_START"] = MEASUREMENT_START.date().isoformat()

    base.WARMUP_START = WARMUP_START
    base.MEASUREMENT_START = MEASUREMENT_START
    base.PRODUCTION_WRAPPER = PRODUCTION_WRAPPER
    base.RESEARCH_WRAPPER = RESEARCH_WRAPPER

    real_print = print

    def certification_print(*args, **kwargs):
        first = str(args[0]) if args else ""
        if first.startswith("[WARMUP] 1997-"):
            return
        real_print(*args, **kwargs)
        if first.startswith("[CERTIFICATION] strict PIT"):
            for session in ("2006-03-31", "2006-06-30", "2006-07-28"):
                real_print(
                    f"[WARMUP] {session} full machine state accumulating; CAGR=N/A",
                    flush=True,
                )

    base.print = certification_print
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
