#!/usr/bin/env python3
"""Annual-segment strict-PIT production entrypoint with durable restart state."""
from __future__ import annotations

import os

FULL_DATASET_END = "2026-07-31"
SEGMENT_END = os.environ.get("CERTIFICATION_SEGMENT_END_SESSION", FULL_DATASET_END)

# The strict metadata wrapper constructs and validates the immutable canonical
# dataset at import time. Validate the complete package, then bind the economic
# replay to the requested annual prefix after imports are complete.
os.environ.setdefault("CANONICAL_PIT_EXPECTED_END", FULL_DATASET_END)
os.environ["CERTIFICATION_END_SESSION"] = FULL_DATASET_END

import backtester.run_production_strict_pit_20y as base  # noqa: E402
from backtester.production_year_checkpoint_overlay import install  # noqa: E402

base.END_SESSION = SEGMENT_END
base.strict.corrected.runner.END_SESSION = SEGMENT_END
base.strict.runner.END_SESSION = SEGMENT_END
if SEGMENT_END != FULL_DATASET_END:
    base.strict.corrected.runner.MEASUREMENT_WINDOWS = {
        1: base.MEASUREMENT_START,
    }
    base.strict.runner.MEASUREMENT_WINDOWS = {
        1: base.MEASUREMENT_START,
    }
os.environ["CERTIFICATION_END_SESSION"] = SEGMENT_END

install(base.strict.runner)

if __name__ == "__main__":
    raise SystemExit(base.main())
