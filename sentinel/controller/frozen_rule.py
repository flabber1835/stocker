"""The Sentinel 1.1 thresholds, LOADED from the frozen research artefact.

## Why this is a loader and not a module of constants

`docs/sentinel-architecture.md` §7 opens with the warning that matters most
here:

> Source of truth is the frozen research harness, NOT this document. The
> numbers below are transcribed from the prospectus PDFs and are here for
> orientation. They must be imported as explicit versioned configuration from
> the harness code before implementation. Re-inferring Sentinel from prose is
> how you get a Sentinel that merely resembles 1.1.

A Python file of transcribed floats is exactly the artefact that warning
describes. It looks identical to a correct one, it passes review, and a single
digit — `-0.155` for `-0.15`, `0.85` for `0.8` — produces a controller that
trades plausibly and is a different strategy. Nothing downstream would report
it: the allocation path stays smooth, the NAV curve stays believable, and the
divergence only shows up against a tape nobody re-runs.

So the thresholds are READ from
`docs/sentinel-handoff/00_README/FROZEN_SENTINEL_1P1_RULE.json`, and its SHA256
is checked against the handoff's own `SHA256SUMS.txt` at load. That turns "we
copied it correctly" from a claim into a verified fact, and it makes an edit to
the frozen rule a loud failure rather than a silent restrategy.

## What is deliberately NOT here — and why that is a boundary, not a gap

The security-level damaged/green classifier. Note what that does NOT mean: the
classifier is known. The handoff bundle of 2026-08-09 did not contain it, which
is why this file's frozen `breadth` block still reads `NOT FOUND IN RETAINED
ARTIFACTS` / `DO NOT RE-INFER` — that JSON is a hash-verified artefact of that
date and is never rewritten to match later knowledge. Later the same day the
classifier was recovered independently and preserved here:

```text
docs/sentinel-reference-implementation/sentinel_1p1_standalone.py
docs/sentinel-breadth-reconstruction/recovered_breadth_classifier.py
```

Its exact GREEN/RED/AMBER rules — including the age-63 GREEN exemption and
AMBER's sector escalation — are transcribed in
`docs/sentinel-controller-certification.md` §7a. Sentinel's `damaged` and
`green` are therefore deterministically computable from the Wealth Core shadow.

The classifier is absent from THIS module because this module loads thresholds.
Breadth generation is a separate component — `sentinel/breadth/`, implemented
and falsified offline, with its raw-corpus parity against the corrected lineage
still owed to the NAS run. Breadth reaches the controller as an OBSERVATION for
that separation, not because the logic is missing.

Its thresholds are NOT in this JSON and could not be: the frozen rule's `breadth`
block carries oracle paths and the re-inference warning, never the predicates. So
`sentinel/breadth/` transcribes its constants from the recovered source instead,
and pins them there the only way available — a randomised differential test
against the stored artefact, which fails offline on any semantic drift.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_HANDOFF = Path(__file__).resolve().parents[2] / "docs" / "sentinel-handoff"
RULE_PATH = _HANDOFF / "00_README" / "FROZEN_SENTINEL_1P1_RULE.json"
SUMS_PATH = _HANDOFF / "00_README" / "SHA256SUMS.txt"

#: The manifest's own entry for the rule file. Named here so a reader can see
#: what is being checked without opening two files.
RULE_MANIFEST_KEY = "00_README/FROZEN_SENTINEL_1P1_RULE.json"


class FrozenRuleTampered(RuntimeError):
    """The frozen rule's bytes do not match the handoff's manifest.

    Raised rather than warned. A controller running on thresholds that are not
    the certified ones is not a degraded controller — it is an uncertified
    strategy wearing a certified name, and every performance claim attached to
    it becomes false at the same moment.
    """


class FrozenRuleMissing(RuntimeError):
    """The handoff artefact is absent. The controller has no thresholds."""


@dataclass(frozen=True)
class RampConfig:
    """Sentinel 1.1's own contribution — the selective recovery ramp (§7a)."""

    gate_horizon_sessions: int
    fragile_if_delta_r40_5_lte: float
    #: (first, second, final). 0.55 and 0.65 are REAL baskets, not corner
    #: cases; §7a corrected an earlier draft that said exposure was binary.
    steps: tuple
    #: (first, second) — consecutive HEALTHY sessions required per promotion.
    confirmation_sessions: tuple
    not_fragile_target: float
    renewed_severe_target: float


@dataclass(frozen=True)
class HealthyConfig:
    """The triple used by every recovery and every ramp promotion."""

    shadow_r20_strictly_greater_than: float
    max_damaged_breadth: float
    min_green_breadth: float


@dataclass(frozen=True)
class ControllerConfig:
    ordinary_stress_drawdown: float
    ordinary_target_core: float
    severe_target_core: float
    slow_entry: dict
    slow_recovery: dict
    fast_entry: dict
    fast_recovery: dict
    ramp: RampConfig
    healthy: HealthyConfig
    strategy_id: str
    digest: str

    def to_dict(self) -> dict:
        """What a decision record cites. The DIGEST is the point: a transition
        that names the rule it was made under is auditable years later."""
        return {"strategy_id": self.strategy_id, "frozen_rule_sha256": self.digest}


def expected_digest() -> Optional[str]:
    if not SUMS_PATH.exists():
        return None
    for line in SUMS_PATH.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == RULE_MANIFEST_KEY:
            return parts[0]
    return None


def actual_digest(path: Path = RULE_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_digest() -> bool:
    """True when the rule file matches the handoff manifest."""
    want = expected_digest()
    return want is not None and want == actual_digest()


def load(path: Path = RULE_PATH) -> ControllerConfig:
    """Read the frozen rule, verifying its bytes first.

    `path` is injectable ONLY so a test can prove the verification actually
    verifies. A digest check that cannot be shown to fail is a comment.
    """
    if not path.exists():
        raise FrozenRuleMissing(
            f"{path} is absent, so the controller has no thresholds. It will "
            f"not fall back to transcribed constants: a Sentinel running on "
            f"numbers nobody verified is an uncertified strategy wearing a "
            f"certified name.")

    digest = actual_digest(path)
    if path == RULE_PATH:
        want = expected_digest()
        if want is None:
            raise FrozenRuleTampered(
                f"{SUMS_PATH} has no entry for {RULE_MANIFEST_KEY}, so the "
                f"frozen rule cannot be verified against anything.")
        if want != digest:
            raise FrozenRuleTampered(
                f"the frozen rule's bytes do not match the handoff manifest\n"
                f"  expected {want}\n  actual   {digest}\n"
                f"Either the artefact was edited — in which case this is no "
                f"longer Sentinel 1.1 — or the manifest is stale. Both need a "
                f"human, and neither may be resolved by trading.")

    raw = json.loads(path.read_text())
    parent = raw.get("sentinel_parent")
    ramp = raw.get("sentinel_1_1_recovery_ramp")
    if not parent or not ramp:
        # A file that parses but is not the frozen rule. The tamper test writes
        # exactly this shape, and so would a truncated download.
        raise FrozenRuleTampered(
            f"{path} parses but is not the frozen Sentinel 1.1 rule: "
            f"{'sentinel_parent' if not parent else 'sentinel_1_1_recovery_ramp'} "
            f"is missing.")

    h = ramp["healthy_definition"]
    return ControllerConfig(
        ordinary_stress_drawdown=float(parent["ordinary_stress_drawdown"]),
        ordinary_target_core=float(parent["ordinary_target_core"]),
        severe_target_core=float(parent["severe_target_core"]),
        slow_entry=dict(parent["slow_entry"]),
        slow_recovery=dict(parent["slow_recovery"]),
        fast_entry=dict(parent["fast_entry"]),
        fast_recovery=dict(parent["fast_recovery"]),
        ramp=RampConfig(
            gate_horizon_sessions=int(ramp["gate_horizon_sessions"]),
            fragile_if_delta_r40_5_lte=float(ramp["delta_r40_5_fragile_if_lte"]),
            steps=(float(ramp["if_fragile_first_target_core"]),
                   float(ramp["second_target_core"]),
                   float(ramp["final_target_core"])),
            confirmation_sessions=(int(ramp["first_confirmation_sessions"]),
                                   int(ramp["second_confirmation_sessions"])),
            not_fragile_target=float(ramp["if_not_fragile_target_core"]),
            renewed_severe_target=float(ramp["renewed_severe_overrides_target_core"]),
        ),
        healthy=HealthyConfig(
            shadow_r20_strictly_greater_than=float(
                h["shadow_r20_strictly_greater_than"]),
            max_damaged_breadth=float(h["max_damaged_breadth"]),
            min_green_breadth=float(h["min_green_breadth"]),
        ),
        strategy_id=str(raw.get("strategy_id", "unknown")),
        digest=digest,
    )


__all__ = ["ControllerConfig", "FrozenRuleMissing", "FrozenRuleTampered",
           "HealthyConfig", "RampConfig", "RULE_PATH", "actual_digest",
           "expected_digest", "load", "verify_digest"]
