"""The Sentinel 1.1 controller: a pure deterministic state machine.

```text
step(observation, state) -> (state, decision)
```

No IO, no clock, no corpus access, no broker. Given the same observation and
the same prior state it returns the same next state and the same exposure,
forever — which is what makes it certifiable against a 5,032-session tape at
all, and what lets `catchup.advance_state` drive it inside a transaction.

## Breadth is an INPUT, and that is a module boundary

A controller that computed breadth internally would fold two separately
certifiable things — the per-security classifier and the state machine — into
one artefact, and neither could then be falsified alone. Taking breadth as an
observation keeps `step` a pure function of (observation, state): exactly
certifiable against the frozen transition tape, testable with hand-built
sequences, and drivable by `catchup.advance_state` with no database.

**This is not because the classifier is unknown.** The 2026-08-09 handoff bundle
did not contain it — `09_GAPS/MISSING_OR_UNRECOVERED.md` and the frozen rule's
`breadth` block both record that handoff-era status, and both are preserved as
written. It was recovered independently later the same day and is in the
repository (`docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`;
rules transcribed in `docs/sentinel-controller-certification.md` §7a), so
`damaged` and `green` are computed deterministically from the Wealth Core
shadow. That engine is now IMPLEMENTED, as `sentinel/breadth/` — a pure
stdlib-only module whose `breadth_observation_fields()` produces exactly the two
fields this dataclass reads.

Three statuses, and they are not the same one:

```text
classifier logic        RECOVERED     exact, two independently agreeing sources
sentinel/breadth/       IMPLEMENTED   transcribed from the standalone source and
                                      falsified offline, including a randomised
                                      differential against the stored artefact
raw-corpus parity       REQUIRES NAS  the 7,061-session reproduction against the
                                      corrected lineage is a separate step
```

So the seam exists and the chain is assemblable, but `decide` stays empty until
the NAS run certifies it end to end (certification §7c).

The frozen breadth and transition tapes are certification and regression
evidence. They are not runtime inputs: nothing on the live path reads one.

## Evidence records, not boolean expressions

Seven conditions with two embedded disjunctions is where a transcription error
hides. Each predicate carries its value, whether it was AVAILABLE, and whether
it passed — three states, not two:

```text
available=False, passed=None   we could not evaluate this
available=True,  passed=False  we evaluated it and it said no
```

A required-but-unavailable predicate fails the transition CLOSED with an
explicit reason, never coerced into an ordinary negative. This is the direct
lesson from Stocker's crash brake, which was fail-open on the restore side
because one boolean answered both "the evidence says no crash" and "there is no
evidence".

## Causes are tracked separately

`fast_severe_active` and `slow_severe_active` are distinct, not one flag. Their
recovery clocks differ: if fast clears while slow persists, exposure stays 0%
and the governing clock changes. A single flag would silently adopt whichever
clock cleared first.

## The state is a plain JSON-round-trippable dict

Not a dataclass. `catchup._mark_processed` persists it in the same statement as
the session pointer and refuses anything `json.dumps` cannot encode without a
`default=` fallback — because a fallback makes everything encodable and nothing
round-trip. A dict of floats, ints, strings and bools survives that exactly, and
a resumed controller continues mid-ramp with its healthy streak intact.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from sentinel.controller.frozen_rule import ControllerConfig

#: Reason codes. Named constants because they are consumed by the transition
#: record and an operator reads them under pressure.
FAST_EVIDENCE_UNAVAILABLE = "FAST_EVIDENCE_UNAVAILABLE"
SLOW_EVIDENCE_UNAVAILABLE = "SLOW_EVIDENCE_UNAVAILABLE"
HEALTH_EVIDENCE_UNAVAILABLE = "HEALTH_EVIDENCE_UNAVAILABLE"

# Persisted controller state is a production input, not a bag of optional
# implementation details.  Versioning and validating it here keeps every
# caller -- production, certification and restart tests -- on one restoration
# rule instead of allowing each transition branch to invent defaults.
CONTROLLER_STATE_VERSION = 1

_BOOL_STATE_FIELDS = frozenset({
    "ordinary_stress_active", "fast_severe_active", "fast_rearm_armed",
    "binary_armed", "base_fast_active", "base_fast_armed",
    "slow_severe_active", "ramp_active",
})
_INT_STATE_FIELDS = frozenset({
    "ordinary_stress_age", "ordinary_healthy_streak", "fast_severe_age",
    "fast_healthy_streak", "base_fast_age", "base_fast_healthy_streak",
    "base_stress_duration", "slow_severe_age", "slow_healthy_streak",
    "ramp_healthy_streak",
})
_OPTIONAL_SESSION_FIELDS = frozenset({
    "ordinary_stress_start_session", "fast_severe_entry_session",
    "slow_severe_entry_session", "ramp_entry_session", "last_session",
})
_OPTIONAL_FLOAT_FIELDS = frozenset({
    "ordinary_stress_start_shadow_nav", "base_stress_start_shadow_nav",
})
_CONTROLLER_STATE_FIELDS = frozenset({
    "controller_state_version", "_r40_history", "ramp_step_index",
    "last_target_core",
}) | _BOOL_STATE_FIELDS | _INT_STATE_FIELDS | _OPTIONAL_SESSION_FIELDS \
    | _OPTIONAL_FLOAT_FIELDS


def _finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def validate_controller_state(raw: Mapping) -> dict:
    """Restore one exact, versioned controller state.

    The only legacy migration is deliberately narrow.  A pre-schema cold state
    never had an r40 observation, so its absent history means the empty list.
    Once ``last_session`` is set, however, losing ``_r40_history`` destroys the
    recovery gate's path-dependent evidence and is not reconstructable.
    """
    if not isinstance(raw, Mapping):
        raise ValueError("controller state must be a mapping")
    state = dict(raw)
    if "controller_state_version" not in state:
        if state.get("last_session") is not None and "_r40_history" not in state:
            raise ValueError(
                "legacy controller state has progressed but lacks _r40_history")
        state["controller_state_version"] = CONTROLLER_STATE_VERSION
        state.setdefault("_r40_history", [])
    version = state["controller_state_version"]
    if (isinstance(version, bool) or not isinstance(version, int)
            or version != CONTROLLER_STATE_VERSION):
        raise ValueError(f"unsupported controller state version {version!r}")

    missing = _CONTROLLER_STATE_FIELDS - set(state)
    extra = set(state) - _CONTROLLER_STATE_FIELDS
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unknown " + ", ".join(sorted(extra)))
        raise ValueError("controller state schema mismatch: " + "; ".join(detail))

    for name in _BOOL_STATE_FIELDS:
        if not isinstance(state[name], bool):
            raise ValueError(f"controller state {name} must be boolean")
    for name in _INT_STATE_FIELDS:
        value = state[name]
        if (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(
                f"controller state {name} must be a non-negative integer")
    for name in _OPTIONAL_SESSION_FIELDS:
        value = state[name]
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(
                f"controller state {name} must be a non-empty string or null")
    for name in _OPTIONAL_FLOAT_FIELDS:
        value = state[name]
        if value is not None and not _finite_number(value):
            raise ValueError(f"controller state {name} must be finite or null")

    target = state["last_target_core"]
    if not _finite_number(target) or not 0.0 <= float(target) <= 1.0:
        raise ValueError("controller state last_target_core must be finite in [0, 1]")
    state["last_target_core"] = float(target)

    ramp_index = state["ramp_step_index"]
    if ramp_index is not None and (
            isinstance(ramp_index, bool) or not isinstance(ramp_index, int)
            or ramp_index < 0):
        raise ValueError(
            "controller state ramp_step_index must be a non-negative integer or null")

    history = state["_r40_history"]
    if not isinstance(history, list):
        raise ValueError("controller state _r40_history must be a list")
    if len(history) > 6:
        raise ValueError("controller state _r40_history exceeds its bounded window")
    clean_history = []
    for value in history:
        if value is None:
            clean_history.append(None)
        elif _finite_number(value):
            clean_history.append(float(value))
        else:
            raise ValueError(
                "controller state _r40_history contains a non-finite value")
    state["_r40_history"] = clean_history

    # This also rejects a future accidental NaN hidden in a newly-added nested
    # value before that value can become durable JSON.
    json.dumps(state, sort_keys=True, allow_nan=False)
    return state


@dataclass(frozen=True)
class Observation:
    """One session's inputs. Every field may be None, meaning UNAVAILABLE.

    None is never zero. An absent `shadow_r40` early in a window is "we cannot
    evaluate this predicate", and a controller that reads it as 0.0 would find
    a comfortable positive where there is no evidence at all.
    """

    session: str
    shadow_nav: Optional[float] = None
    damaged_breadth: Optional[float] = None
    green_breadth: Optional[float] = None
    shadow_drawdown: Optional[float] = None
    shadow_r5: Optional[float] = None
    shadow_r10: Optional[float] = None
    shadow_r20: Optional[float] = None
    shadow_r40: Optional[float] = None
    damaged_breadth_delta5: Optional[float] = None
    #: SPY confirmation. ABSENT FROM EVERY HANDOFF ARTEFACT, so these are
    #: implemented from the frozen rule and cannot be certified against the
    #: tape — see the certification module's docstring.
    spy_r20: Optional[float] = None
    spy_vol_ratio: Optional[float] = None
    stops20: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.session, str) or not self.session:
            raise ValueError("controller observation session must be non-empty")
        numeric = (
            "shadow_nav", "damaged_breadth", "green_breadth",
            "shadow_drawdown", "shadow_r5", "shadow_r10", "shadow_r20",
            "shadow_r40", "damaged_breadth_delta5", "spy_r20",
            "spy_vol_ratio",
        )
        for name in numeric:
            value = getattr(self, name)
            if value is None:
                continue
            # Non-finite transport values are unavailable evidence.  Convert
            # them before predicates or durable evidence can observe them.
            object.__setattr__(
                self, name, float(value) if _finite_number(value) else None)
        stops = self.stops20
        if (stops is not None and (
                isinstance(stops, bool) or not isinstance(stops, int)
                or stops < 0)):
            object.__setattr__(self, "stops20", None)


@dataclass(frozen=True)
class PredicateResult:
    """value / available / passed, kept apart on purpose."""

    name: str
    value: Optional[float]
    available: bool
    passed: Optional[bool]

    def to_dict(self) -> dict:
        out = {"name": self.name, "value": self.value,
               "available": self.available, "passed": self.passed}
        json.dumps(out, sort_keys=True, allow_nan=False)
        return out


@dataclass(frozen=True)
class Evidence:
    """A transition's predicates and what they collectively say."""

    predicates: tuple
    satisfied: bool
    reason: str

    def __getattr__(self, item):
        for p in self.predicates:
            if p.name == item:
                return p
        raise AttributeError(item)

    def to_dict(self) -> dict:
        return {"satisfied": self.satisfied, "reason": self.reason,
                "predicates": [p.to_dict() for p in self.predicates]}


@dataclass(frozen=True)
class Decision:
    session: str
    target_core_exposure: float
    reason: str
    fast_severe_active: bool = False
    slow_severe_active: bool = False
    ramp_step: Optional[float] = None
    evidence: dict = field(default_factory=dict)

    @property
    def severe(self) -> bool:
        return self.fast_severe_active or self.slow_severe_active

    def to_dict(self) -> dict:
        """The transition record. Parity is asserted on THIS, not on a call
        site — both engines must emit the same canonical shape."""
        out = {"session": self.session,
               "target_core_exposure": self.target_core_exposure,
               "reason": self.reason,
               "fast_severe_active": self.fast_severe_active,
               "slow_severe_active": self.slow_severe_active,
               "severe": self.severe,
               "ramp_step": self.ramp_step,
               "evidence": self.evidence}
        json.dumps(out, sort_keys=True, allow_nan=False)
        return out


def _p(name, value, test) -> PredicateResult:
    """One predicate, with UNAVAILABLE kept distinct from FAILED."""
    if value is None or not _finite_number(value):
        return PredicateResult(name=name, value=None, available=False,
                               passed=None)
    return PredicateResult(name=name, value=float(value), available=True,
                           passed=bool(test(value)))


def _collect(predicates, unavailable_reason: str, satisfied_reason: str,
             failed_reason: str) -> Evidence:
    """FAIL CLOSED on missing evidence, and say which kind of no it is.

    Order matters: unavailability is checked BEFORE the pass/fail tally, so a
    transition never reports "the conditions were not met" when the truth is
    that it could not look.
    """
    missing = [p.name for p in predicates if not p.available]
    if missing:
        return Evidence(predicates=tuple(predicates), satisfied=False,
                        reason=f"{unavailable_reason}: {','.join(missing)}")
    ok = all(p.passed for p in predicates)
    return Evidence(predicates=tuple(predicates), satisfied=ok,
                    reason=satisfied_reason if ok else failed_reason)


class Controller:
    """Sentinel 1.1. Constructed with the frozen config; holds no state itself.

    State lives in the dict passed through `step`, never on the instance — so
    two sessions replayed on one instance cannot leak into each other, and a
    controller is safe to reuse across a catch-up replay.
    """

    def __init__(self, config: ControllerConfig) -> None:
        self.cfg = config

    # ── state ───────────────────────────────────────────────────────────────

    def initial_state(self) -> dict:
        """A COLD START, stated explicitly rather than defaulted field by field.

        Every clock starts unset and every streak at zero, which is the correct
        reading of "we have no history": a controller that began mid-ramp, or
        with a stress clock already aged, would make its first decision on
        evidence it never saw.
        """
        return {
            "controller_state_version": CONTROLLER_STATE_VERSION,
            "_r40_history": [],
            "ordinary_stress_active": False,
            "ordinary_stress_start_session": None,
            "ordinary_stress_start_shadow_nav": None,
            "ordinary_stress_age": 0,
            "ordinary_healthy_streak": 0,
            "fast_severe_active": False,
            "fast_severe_entry_session": None,
            "fast_severe_age": 0,
            "fast_healthy_streak": 0,
            "fast_rearm_armed": True,
            "binary_armed": True,
            "base_fast_active": False,
            "base_fast_age": 0,
            "base_fast_healthy_streak": 0,
            "base_fast_armed": True,
            "base_stress_start_shadow_nav": None,
            "base_stress_duration": 0,
            "slow_severe_active": False,
            "slow_severe_entry_session": None,
            "slow_severe_age": 0,
            "slow_healthy_streak": 0,
            "ramp_active": False,
            "ramp_step_index": None,
            "ramp_healthy_streak": 0,
            "ramp_entry_session": None,
            "last_target_core": 1.0,
            "last_session": None,
        }

    # ── predicates ──────────────────────────────────────────────────────────

    def is_healthy(self, ob: Observation) -> Optional[bool]:
        """The triple every recovery and every ramp promotion depends on.

        Returns None when it cannot be evaluated — callers must treat that as
        "not healthy" for promotion purposes AND must not let it break a
        streak silently, which is why the streak logic reads it explicitly.
        """
        h = self.cfg.healthy
        if (not _finite_number(ob.shadow_r20)
                or not _finite_number(ob.damaged_breadth)
                or not _finite_number(ob.green_breadth)):
            return None
        return (ob.shadow_r20 > h.shadow_r20_strictly_greater_than
                and ob.damaged_breadth <= h.max_damaged_breadth
                and ob.green_breadth >= h.min_green_breadth)

    def is_fragile(self, delta_r40_5: Optional[float]) -> Optional[bool]:
        """§7a's gate. `<= 0.0`, tightened from `<= +0.01` with the exact
        historical path unchanged — so the threshold sits on a plateau rather
        than a knife edge, which is why this is a comparison and not a band."""
        if not _finite_number(delta_r40_5):
            return None
        return delta_r40_5 <= self.cfg.ramp.fragile_if_delta_r40_5_lte

    def fast_severe_evidence(self, ob: Observation) -> Evidence:
        """The seven-condition fast path, with its two embedded disjunctions.

        The disjunctions are evaluated as single predicates with their own
        availability, because `A or B` where A is unavailable and B is False is
        NOT False — it is unknown, and the whole point of this structure is
        that unknown fails closed.
        """
        e = self.cfg.fast_entry
        short_loss = _or_predicate(
            "short_loss",
            [(ob.shadow_r5, e["short_loss_or"][0]["max_shadow_r5"]),
             (ob.shadow_r10, e["short_loss_or"][1]["max_shadow_r10"])])
        confirmation = _or_predicate(
            "confirmation",
            [(ob.spy_r20, e["confirmation_or"][0]["max_spy_r20"]),
             (ob.shadow_r10, e["confirmation_or"][1]["max_shadow_r10"])])
        preds = [
            _p("shadow_drawdown", ob.shadow_drawdown,
               lambda v: v <= e["max_shadow_drawdown"]),
            _p("damaged_breadth", ob.damaged_breadth,
               lambda v: v >= e["min_damaged_breadth"]),
            _p("green_breadth", ob.green_breadth,
               lambda v: v <= e["max_green_breadth"]),
            short_loss,
            _p("damage_acceleration", ob.damaged_breadth_delta5,
               lambda v: v >= e["min_damaged_breadth_delta5"]),
            _p("vol_acceleration", ob.spy_vol_ratio,
               lambda v: v >= e["min_spy_vol5_over_vol20_minus_1"]),
            confirmation,
        ]
        return _collect(preds, FAST_EVIDENCE_UNAVAILABLE,
                        "FAST_SEVERE_ENTRY", "FAST_CONDITIONS_NOT_MET")

    def slow_severe_evidence(self, ob: Observation, state: dict) -> Evidence:
        """The grinding-bear path. Evaluated only while ordinary stress is
        active — the caller enforces that; this reports the predicates."""
        state = validate_controller_state(state)
        e = self.cfg.slow_entry
        # The slow predicate is anchored to the full base-stress episode,
        # whether BinaryStress or base FastState started it.
        anchor = state.get("base_stress_start_shadow_nav")
        since = (None if not anchor or ob.shadow_nav is None
                 else ob.shadow_nav / anchor - 1.0)
        preds = [
            _p("stress_duration", state.get("base_stress_duration"),
               lambda v: v >= e["minimum_stress_sessions"]),
            _p("return_since_anchor", since,
               lambda v: v <= e["max_return_since_anchor"]),
            _p("shadow_r40", ob.shadow_r40,
               lambda v: v <= e["max_shadow_return_40"]),
            _p("damaged_breadth", ob.damaged_breadth,
               lambda v: v >= e["min_damaged_breadth"]),
            _p("green_breadth", ob.green_breadth,
               lambda v: v <= e["max_green_breadth"]),
        ]
        return _collect(preds, SLOW_EVIDENCE_UNAVAILABLE,
                        "SLOW_SEVERE_ENTRY", "SLOW_CONDITIONS_NOT_MET")

    def step(self, *, observation: Observation, state: dict) -> tuple:
        """Advance the production parent controller and the 1.1 ramp.

        Unlike :meth:`step_with_parent`, this entry point never consumes an
        oracle allocation.  The parent severe state is derived exclusively
        from the supplied observation and prior durable state.
        """
        prior_state = validate_controller_state(state)
        st = dict(prior_state)
        ob = observation
        fast = self.fast_severe_evidence(ob)

        dd = ob.shadow_drawdown
        signal = fast.satisfied
        healthy = self.is_healthy(ob)

        # Exact BinaryStress ordering: rearm, entry, then active recovery.
        ordinary = bool(st.get("ordinary_stress_active"))
        if dd is not None and dd > self.cfg.ordinary_stress_drawdown:
            st["binary_armed"] = True
        if (dd is not None and dd <= self.cfg.ordinary_stress_drawdown
                and st.get("binary_armed", True) and not ordinary):
            ordinary = True
            st.update(binary_armed=False,
                      ordinary_stress_start_session=ob.session,
                      ordinary_stress_start_shadow_nav=ob.shadow_nav,
                      ordinary_stress_age=0, ordinary_healthy_streak=0)
        elif ordinary:
            st["ordinary_stress_age"] = int(st.get("ordinary_stress_age", 0)) + 1
            stops_available = (isinstance(ob.stops20, int)
                               and not isinstance(ob.stops20, bool)
                               and ob.stops20 >= 0)
            binary_healthy = (ob.shadow_r20 is not None and ob.shadow_r20 > 0
                              and stops_available and ob.stops20 <= 2)
            st["ordinary_healthy_streak"] = (
                int(st["ordinary_healthy_streak"]) + 1
                if binary_healthy else 0)
            if (st["ordinary_stress_age"] >= 20
                    and st["ordinary_healthy_streak"] >= 3):
                ordinary = False
                st["ordinary_healthy_streak"] = 0
        st["ordinary_stress_active"] = ordinary

        # Exact base-mode FastState. Binary stress blocks only entry.
        base_fast = bool(st.get("base_fast_active"))
        if dd is not None and dd > -0.06 and not signal:
            st["base_fast_armed"] = True
        if (signal and st.get("base_fast_armed", True) and not base_fast
                and not ordinary):
            base_fast = True
            st.update(base_fast_armed=False, base_fast_age=0,
                      base_fast_healthy_streak=0)
        elif base_fast:
            st["base_fast_age"] = int(st.get("base_fast_age", 0)) + 1
            st["base_fast_healthy_streak"] = (
                int(st.get("base_fast_healthy_streak", 0)) + 1 if healthy else 0)
            if (st["base_fast_age"] >= 10
                    and st["base_fast_healthy_streak"] >= 3):
                base_fast = False
                st["base_fast_healthy_streak"] = 0
        st["base_fast_active"] = base_fast

        base_stress = ordinary or base_fast
        if base_stress:
            if not (prior_state.get("ordinary_stress_active")
                    or prior_state.get("base_fast_active")):
                st["base_stress_start_shadow_nav"] = ob.shadow_nav
                st["base_stress_duration"] = 1
            else:
                st["base_stress_duration"] = int(
                    st.get("base_stress_duration", 0)) + 1
        else:
            st.update(base_stress_start_shadow_nav=None, base_stress_duration=0)
        slow = (self.slow_severe_evidence(ob, st) if base_stress
                else Evidence((), False, "SLOW_CONDITIONS_NOT_MET"))
        fast_active = bool(st.get("fast_severe_active"))
        slow_active = bool(st.get("slow_severe_active"))

        # Exact parent-mode FastState: rearm precedes entry and retrigger is
        # impossible until dd > -6% while the shock is absent.
        if dd is not None and dd > -0.06 and not signal:
            st["fast_rearm_armed"] = True
        if signal and st.get("fast_rearm_armed", True) and not fast_active:
            if not fast_active:
                fast_active = True
                st.update(fast_severe_entry_session=ob.session,
                          fast_severe_age=0, fast_healthy_streak=0,
                          fast_rearm_armed=False)
            else:
                st["fast_severe_age"] = int(st.get("fast_severe_age", 0)) + 1
                st["fast_healthy_streak"] = 0
        elif fast_active:
            st["fast_severe_age"] = int(st.get("fast_severe_age", 0)) + 1
            st["fast_healthy_streak"] = (
                int(st.get("fast_healthy_streak", 0)) + 1 if healthy else 0)
            r = self.cfg.fast_recovery
            if (st["fast_severe_age"] + 1 >= r["minimum_state_sessions"]
                    and st["fast_healthy_streak"] >= r["confirmation_sessions"]):
                fast_active = False
                st["fast_healthy_streak"] = 0

        if slow_active:
            st["slow_severe_age"] = int(st.get("slow_severe_age", 0)) + 1
            st["slow_healthy_streak"] = (
                int(st.get("slow_healthy_streak", 0)) + 1 if healthy else 0)
            # Standalone exits on the sixth healthy observation.
            if (st["slow_severe_age"] + 1 >= 20
                    and st["slow_healthy_streak"] >= 6):
                slow_active = False
                st["slow_healthy_streak"] = 0
        elif slow.satisfied:
            if not slow_active:
                slow_active = True
                st.update(slow_severe_entry_session=ob.session,
                          slow_severe_age=0, slow_healthy_streak=0)
            else:
                st["slow_severe_age"] = int(st.get("slow_severe_age", 0)) + 1
                st["slow_healthy_streak"] = 0

        st["fast_severe_active"] = fast_active
        st["slow_severe_active"] = slow_active
        parent = 0.0 if fast_active or slow_active else 1.0
        prior = (0.0 if prior_state.get("fast_severe_active")
                 or prior_state.get("slow_severe_active") else 1.0)
        nxt, decision = self.step_with_parent(
            observation=ob, state=st, parent_alloc=parent,
            prior_parent_alloc=prior)
        nxt["fast_severe_active"] = fast_active
        nxt["slow_severe_active"] = slow_active
        decision = Decision(
            session=decision.session,
            target_core_exposure=decision.target_core_exposure,
            reason=decision.reason,
            fast_severe_active=fast_active,
            slow_severe_active=slow_active,
            ramp_step=decision.ramp_step,
            evidence={"fast": fast.to_dict(), "slow": slow.to_dict()},
        )
        return validate_controller_state(nxt), decision

    # ── the ramp ────────────────────────────────────────────────────────────

    def ramp_target(self, state: dict) -> float:
        """Exposure implied by the ramp alone, ignoring severe causes."""
        state = validate_controller_state(state)
        if not state.get("ramp_active"):
            return 1.0
        idx = state.get("ramp_step_index")
        return self.cfg.ramp.steps[idx] if idx is not None else 1.0

    def step_with_parent(self, *, observation: Observation, state: dict,
                         parent_alloc: float,
                         prior_parent_alloc: float) -> tuple:
        """One session, with the PARENT severe signal supplied externally.

        This is the certification entry point, and the separation is a
        statement about what is proven rather than a convenience. The parent's
        fast path needs two SPY predicates that appear in NO handoff artefact,
        so its entries cannot be reproduced from the frozen tape. Consuming the
        tape's own canonical allocation as the severe signal isolates exactly
        what Sentinel 1.1 ADDS — the selective recovery ramp — and certifies
        that exactly, instead of certifying a guess about SPY.

        `step()` is the production path, where the parent signal is computed
        from the evidence rather than supplied.
        """
        cfg = self.cfg
        st = validate_controller_state(state)
        if not _finite_number(parent_alloc) or not _finite_number(prior_parent_alloc):
            raise ValueError("parent allocations must be finite")
        severe = parent_alloc <= 0.0
        recovering = prior_parent_alloc <= 0.0 and not severe

        healthy = self.is_healthy(observation)

        if severe:
            # RENEWED SEVERE ABANDONS THE RAMP (§7a). Not paused: the ramp's
            # premise is that a recovery is being confirmed, and a fresh severe
            # cause is that premise failing. Resuming at 0.65 afterwards would
            # promote on confirmations collected before the thing that broke.
            #
            # BELT AND BRACES, and labelled as such rather than left looking
            # load-bearing. Abandonment is actually ENFORCED one branch down:
            # the only route out of severe is a canonical recovery, and that
            # branch re-evaluates fragility and restarts the ramp at step 0
            # unconditionally. Mutation testing proved it — deleting this line
            # changes no behaviour at all. It stays because the rule is
            # explicit and a future edit to the recovery branch should not be
            # able to resurrect a stale ramp silently.
            st.update(ramp_active=False, ramp_step_index=None,
                      ramp_healthy_streak=0, ramp_entry_session=None)
            target, reason = cfg.severe_target_core, "SEVERE"
        elif recovering:
            fragile = self.is_fragile(
                _delta_r40_at_prior_close(st.get("_r40_history"),
                                          cfg.ramp.gate_horizon_sessions))
            # AN UNEVALUABLE GATE RAMPS. `fragile is not False`, not `if
            # fragile` — None means the five-session r40 window could not be
            # formed, and taking the falsy branch there sends the account to
            # 100% on absent evidence.
            #
            # That is exposure-INCREASING action on no evidence, which
            # architecture invariant 26 forbids outright: "exposure-increasing
            # action requires strictly stronger evidence than
            # exposure-reducing action". Ramping instead costs opportunity on a
            # recovery that might have been robust; the other way round buys a
            # full book into a recovery nobody could assess.
            #
            # Found by composing the controller with catch-up rather than by
            # the frozen tape, whose first recovery is ~290 sessions in and
            # never has a short window. A cold start does.
            if fragile is not False:
                # THE RECOVERY SESSION ITSELF SEEDS THE STREAK. 2022-08-05 is
                # healthy and its ramp promotes on 08-19; counting from the day
                # AFTER would put the tenth confirmation on 08-22.
                st.update(ramp_active=True, ramp_step_index=0,
                          ramp_healthy_streak=1 if healthy else 0,
                          ramp_entry_session=observation.session)
                target = cfg.ramp.steps[0]
                reason = ("RECOVERY_FRAGILE_RAMP" if fragile
                          else "RECOVERY_GATE_UNAVAILABLE_RAMP")
            else:
                st.update(ramp_active=False, ramp_step_index=None,
                          ramp_healthy_streak=0)
                target, reason = cfg.ramp.not_fragile_target, "RECOVERY_FULL"
        elif st.get("ramp_active"):
            idx = st["ramp_step_index"]
            need = cfg.ramp.confirmation_sessions[idx]
            # CONSECUTIVE, INCLUDING THE RECOVERY SESSION, JUDGED ON THE PRIOR
            # CLOSE. Three properties, and the frozen tape pins all three
            # independently — each of my first two attempts had exactly one of
            # them and diverged on five sessions out of 5,032:
            #
            #   consecutive     2011's cumulative count reaches ten on 09-23
            #                   and does NOT promote; a False on 09-12 reset it
            #   includes entry  2022-08-05 is healthy and its ramp promotes on
            #                   08-19, which is only reachable if the recovery
            #                   session is the first confirmation
            #   prior close     2011-11-08 reaches ten and promotes on 11-09,
            #                   as does 2022-10-31 -> 11-01
            #
            # A ramp that steps one session early holds 10% more exposure
            # through a day the rule says was still being confirmed, at each of
            # two steps, on every fragile recovery.
            if st.get("ramp_healthy_streak", 0) >= need:
                idx += 1
                st["ramp_step_index"] = idx
                st["ramp_healthy_streak"] = 0
                if idx >= len(cfg.ramp.steps) - 1:
                    st.update(ramp_active=False, ramp_step_index=None,
                              ramp_entry_session=None)
                    target, reason = cfg.ramp.steps[-1], "RAMP_COMPLETE"
                else:
                    target, reason = cfg.ramp.steps[idx], "RAMP_PROMOTED"
            else:
                target, reason = cfg.ramp.steps[idx], "RAMP_HOLDING"

            if st.get("ramp_active"):
                # UNAVAILABLE resets too. The rule asks for consecutive healthy
                # CLOSES, and a close we could not classify is not one.
                st["ramp_healthy_streak"] = (
                    st.get("ramp_healthy_streak", 0) + 1 if healthy else 0)

        else:
            target, reason = cfg.ordinary_target_core, "NORMAL"

        st["_r40_history"] = _push(st.get("_r40_history"),
                                   observation.shadow_r40,
                                   cfg.ramp.gate_horizon_sessions + 1)
        st["last_target_core"] = target
        st["last_session"] = observation.session
        st["fast_severe_active"] = severe
        st["slow_severe_active"] = False

        return validate_controller_state(st), Decision(
            session=observation.session, target_core_exposure=target,
            reason=reason, fast_severe_active=severe,
            ramp_step=(cfg.ramp.steps[st["ramp_step_index"]]
                       if st.get("ramp_active")
                       and st.get("ramp_step_index") is not None else None))


def _or_predicate(name, pairs) -> PredicateResult:
    """`A or B` where an unavailable side is UNKNOWN, not False.

    Available-and-true short-circuits to a pass — a satisfied disjunct settles
    it regardless of the other. Otherwise, if any side is unavailable the whole
    thing is unavailable, because "no and unknown" cannot be distinguished from
    "no and yes" without looking.
    """
    if any(_finite_number(v) and v <= t for v, t in pairs):
        return PredicateResult(name=name, value=None, available=True,
                               passed=True)
    if any(not _finite_number(v) for v, _ in pairs):
        return PredicateResult(name=name, value=None, available=False,
                               passed=None)
    return PredicateResult(name=name, value=None, available=True, passed=False)


def _push(history, value, keep: int) -> list:
    h = list(history or [])
    h.append(float(value) if _finite_number(value) else None)
    return h[-keep:]


def _delta_r40_at_prior_close(history, horizon: int):
    """`delta_r40_5`, evaluated on PRIOR-CLOSE information.

        r40[prior_close] - r40[prior_close - horizon]

    The frozen rule says "using prior close information", and
    `02_recovery_gate_flags.csv` pins it exactly: each of the seven recovery
    dates carries its `prior_close` and the `delta_r40` judged on it. This
    formulation reproduces all seven to 1e-12; today-based ones do not.

    `history` is the controller's own rolling r40 window, pushed AFTER each
    decision — so on a recovery session its last element IS the prior close,
    and the horizon is `h[-1] - h[-1-horizon]`. That off-by-one is the whole
    defect this replaced: reading `h[-horizon]` compared the prior close
    against four sessions back instead of five, which flipped 2011-09-07 from
    fragile to not-fragile and skipped a 0.55 ramp entirely.

    None when the window is not yet full. Never zero: an unevaluable gate is
    not a comfortable positive, and `is_fragile(None)` returns None so the
    caller fails it closed.
    """
    h = list(history or [])
    if len(h) < horizon + 1:
        return None
    now, then = h[-1], h[-1 - horizon]
    if not _finite_number(now) or not _finite_number(then):
        return None
    return now - then


__all__ = ["CONTROLLER_STATE_VERSION", "Controller", "Decision", "Evidence",
           "Observation", "PredicateResult", "validate_controller_state"]
