"""Terminal-wealth comparison — the LEFT-TAIL half of the promotion gate.

Lives in shared/ because BOTH stacks need the identical rule and they share no
other code path: bt-engine PRODUCES the distribution (app/bootstrap.py, numpy),
bt-scheduler CONSUMES it in the gate. Two copies of a promotion criterion is
exactly the drift that has bitten this system before, so there is one.

Pure / dependency-free (no numpy) so the scheduler need not carry the
simulator's dependencies.

NOTE FOR DEPLOYS: this is a NEW module file under shared/, so `stocker-base`
must be rebuilt before the services that import it — the editable install caches
the module file list.
"""
from __future__ import annotations

from typing import Optional

# How much worse the candidate's BAD case may be, as a multiple of starting
# capital. 0.05 = its 5th-percentile terminal wealth may sit 5% of starting
# capital below the baseline's before the gate refuses.
DEFAULT_TAIL_TOLERANCE = 0.05


def tail_is_acceptable(cand: Optional[dict], base: Optional[dict],
                       tolerance: float = DEFAULT_TAIL_TOLERANCE
                       ) -> tuple[bool, str]:
    """Is the candidate's left tail acceptable next to the baseline's?

    Compares 5th-percentile terminal wealth as a MULTIPLE of starting capital,
    so the test is scale-free and stated directly in the objective's units
    (money at the end), not in a rate.

    Missing stats => (True, ...) DELIBERATELY. This runs alongside the existing
    CAGR/drawdown conditions on results that may predate the feature or come
    from a stress-regime run. A newly added check must never silently block
    every promotion because an older row lacks a field — it tightens the gate
    where it can see and stays inert where it cannot."""
    cp = (cand or {}).get("p5_multiple")
    bp = (base or {}).get("p5_multiple")
    if cp is None or bp is None:
        return True, "no terminal-wealth distribution to compare (check skipped)"
    cp, bp, tol = float(cp), float(bp), float(tolerance)
    if cp < bp - tol:
        return False, (f"left tail worse: 5th-percentile terminal wealth "
                       f"{cp:.3f}x vs baseline {bp:.3f}x (tolerance {tol:.3f}x)")
    return True, (f"left tail acceptable: p5 {cp:.3f}x vs baseline {bp:.3f}x")
