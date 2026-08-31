#!/usr/bin/env python3
"""Annual-segment strict-PIT production entrypoint with durable restart state."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PINNED_MAIN_ROOT = ROOT / "main-src"
if PINNED_MAIN_ROOT.is_dir() and str(PINNED_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PINNED_MAIN_ROOT))

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

# The durable handoff includes the production SessionState plus the independent
# full-stack PIT Wealth Core return path and strict metadata authority counters.
# These module globals affect the next session or final evidence and therefore
# cross the annual boundary with the same fail-closed identity contract.
install(
    base.strict.runner,
    fullstack_module=base.strict.prod,
    strict_module=base.strict,
    progress_module=base.strict.base,
)

# Diagnostic-only observer. It receives the already-computed ephemeral candidate
# rows and cannot alter state, ordering, intents, or execution. The observer is
# inert unless an explicit target session is supplied by a diagnostic workflow.
_DIAGNOSTIC_SESSION = os.environ.get(
    "CERTIFICATION_RANKING_DIAGNOSTIC_SESSION", ""
).strip()
if _DIAGNOSTIC_SESSION:
    _diagnostic_plan_session = base.strict.strategy_production.plan_session

    def _plan_session_with_ranking_diagnostic(*args, **kwargs):
        plan = _diagnostic_plan_session(*args, **kwargs)
        if str(plan.session) == _DIAGNOSTIC_SESSION:
            top = [row for row in plan.leadership_candidates if row.in_top_decile]

            def leadership_key(row):
                momentum = float(row.momentum) if row.momentum is not None else float("nan")
                return (
                    0 if math.isfinite(momentum) else 1,
                    -momentum if math.isfinite(momentum) else 0.0,
                    str(row.security_id),
                    str(row.ticker),
                )

            def ranking_key(row):
                score = float(row.score) if row.score is not None else float("nan")
                return (
                    0 if math.isfinite(score) else 1,
                    -score if math.isfinite(score) else 0.0,
                    str(row.security_id),
                    str(row.ticker),
                )

            leadership = sorted(top, key=leadership_key)
            ranked = sorted(top, key=ranking_key)
            payload = {
                "session": str(plan.session),
                "eligible_universe": int(plan.eligible_universe_count),
                "leadership_ids": [str(row.security_id) for row in leadership],
                "ranking": [
                    {
                        "security_id": str(row.security_id),
                        "ticker": str(row.ticker),
                        "momentum": row.momentum,
                        "recent": row.recent,
                        "score": row.score,
                    }
                    for row in ranked
                ],
            }
            print(
                "[RANKING DIAGNOSTIC] role=production "
                + json.dumps(payload, sort_keys=True, separators=(",", ":")),
                flush=True,
            )
        return plan

    base.strict.strategy_production.plan_session = _plan_session_with_ranking_diagnostic

if __name__ == "__main__":
    raise SystemExit(base.main())
