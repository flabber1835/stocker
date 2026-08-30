#!/usr/bin/env python3
"""Strict-PIT production certification on the agreed 20-year window."""
from __future__ import annotations

import os

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

import backtester.run_production_strict_pit_certification as strict

WARMUP_START = "2006-01-03"
MEASUREMENT_START = "2006-07-31"
END_SESSION = os.environ.get("CERTIFICATION_END_SESSION", "2026-07-31")

# The corrected production wrapper resolves these names dynamically, so the
# certified mechanics remain unchanged while the historical contract moves to
# the evidence-supported 20-year boundary.
strict.corrected.WARMUP_START = WARMUP_START
strict.corrected.MEASUREMENT_START = MEASUREMENT_START
strict.corrected.runner.CHAIN_START = WARMUP_START
strict.corrected.runner.END_SESSION = END_SESSION
strict.corrected.runner.EXPERIMENT_ID = "2026-08-30-strict-pit-20y-production"

strict.runner.CHAIN_START = WARMUP_START
strict.runner.END_SESSION = END_SESSION
strict.MEASUREMENT_START = MEASUREMENT_START


def main() -> int:
    print(
        f"[CONTRACT] role=production warmup={WARMUP_START} "
        f"measurement={MEASUREMENT_START} end={END_SESSION}",
        flush=True,
    )
    return int(strict.main())


if __name__ == "__main__":
    raise SystemExit(main())
