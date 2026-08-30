#!/usr/bin/env python3
"""Strict-PIT production certification on the agreed 20-year window."""
from __future__ import annotations

import os
from pathlib import Path
import sys

# This file is executed as a script by the parallel orchestrator.  Python then
# puts ``.../backtester`` on sys.path, not the repository root, so importing the
# ``backtester`` package must not depend on an inherited PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

import backtester.run_production_strict_pit_certification as strict

WARMUP_START = "2006-01-03"
MEASUREMENT_START = "2006-07-31"
FULL_END_SESSION = "2026-07-31"
END_SESSION = os.environ.get("CERTIFICATION_END_SESSION", FULL_END_SESSION)

# The machine's causal state begins at WARMUP_START.  The corrected SFP builder,
# however, expects its wrapped factor series to begin at the measurement anchor
# and prepends raw SPY warm-up observations itself. Keep those two boundaries
# distinct while preserving warm-up ACTIONS/SEP processing.
strict.corrected.WARMUP_START = WARMUP_START
strict.corrected.MEASUREMENT_START = MEASUREMENT_START
strict.corrected.runner.CHAIN_START = WARMUP_START
strict.corrected.runner.END_SESSION = END_SESSION
strict.corrected.runner.EXPERIMENT_ID = "2026-08-30-strict-pit-20y-production"

strict.runner.CHAIN_START = WARMUP_START
strict.runner.END_SESSION = END_SESSION
strict.MEASUREMENT_START = MEASUREMENT_START

_original_measurement_factor_builder = strict.corrected._original_sfp_builder


def _measurement_anchored_factor_builder(path):
    saved = strict.runner.CHAIN_START
    strict.runner.CHAIN_START = MEASUREMENT_START
    try:
        return _original_measurement_factor_builder(path)
    finally:
        strict.runner.CHAIN_START = saved


strict.corrected._original_sfp_builder = _measurement_anchored_factor_builder

# Frozen terminal evidence stores legacy Sharadar permanent IDs as provenance.
# Strict PIT deliberately replaces those IDs with causal price-tape/SEC episode
# IDs. Join the frozen economics by historical ticker/session and instantiate
# TerminalTerms with the resolver's causal ID so the event reaches the same
# security identity used by Wealth Core on that session.
_original_terminal_loader = strict.base.load_frozen_terminal_terms


def _causal_identity_terminal_loader(*args, **kwargs):
    kwargs["identity_binding"] = "resolved"
    return _original_terminal_loader(*args, **kwargs)


strict.base.load_frozen_terminal_terms = _causal_identity_terminal_loader

# The base terminal provenance layer carries a dedicated 2001 regression witness.
# It remains valuable for replays that include that boundary, but it is outside
# this 2006+ contract. Move only that assertion outside the active horizon; the
# terminal-event loader still validates every in-window frozen event strictly.
if strict.base.BOUNDARY_SESSION < WARMUP_START:
    strict.base.BOUNDARY_SESSION = "9999-12-31"

# The base replay always writes a metrics table before the strict wrapper adds
# its maximum-history row. A bounded diagnostic therefore needs one harmless
# metric window so the table retains its schema. The diagnostic never treats
# this row as certification performance evidence.
if END_SESSION != FULL_END_SESSION:
    strict.runner.MEASUREMENT_WINDOWS = {1: MEASUREMENT_START}


def main() -> int:
    if "--self-test-imports" in sys.argv[1:]:
        print(
            f"[SELFTEST PASS] production 20y entrypoint root={ROOT} "
            f"backtester_import={Path(strict.__file__).resolve()}",
            flush=True,
        )
        return 0
    print(
        f"[CONTRACT] role=production warmup={WARMUP_START} "
        f"measurement={MEASUREMENT_START} end={END_SESSION}",
        flush=True,
    )
    return int(strict.main())


if __name__ == "__main__":
    raise SystemExit(main())
