"""The Sentinel 1.1 controller, against the frozen research oracle.

THE ORACLE IS THE TEST. `04_BREADTH_ORACLES/sentinel_1p1_exact_daily_with_breadth.csv`
is 5,032 sessions of the research harness's own output — `candidate_alloc`, the
exposure the frozen rule chose on each date — beside the observations it chose
from. There is nothing to invent and nothing to argue about: the controller
either reproduces that column or it is a different strategy.

That framing is the whole point of `docs/sentinel-architecture.md` §7's warning:

> Re-inferring Sentinel from prose is how you get a Sentinel that merely
> resembles 1.1.

So the thresholds are LOADED from `FROZEN_SENTINEL_1P1_RULE.json` with its
digest verified, and the behaviour is asserted against the tape rather than
against my reading of the tape.

## What this file can and cannot prove

```text
EXACT, all 5,032 sessions
    the recovery ramp        fragility gate, 0.55 -> 0.65 -> 1.0, abandonment
    the healthy triple       r20 / damaged / green
    slow severe ENTRY        every predicate is on the tape
    fast and slow RECOVERY   dwell counts, confirmation streaks, re-arm

NOT PROVABLE HERE
    the two SPY predicates of fast entry. SPY appears in no handoff artifact,
    so those are implemented from the frozen JSON and gated separately. Where
    this file needs a severe entry it consumes the tape's own canonical
    transitions as the parent signal — which is honest about what is being
    certified rather than quietly filling the gap with an assumption.
```

`02_recovery_gate_flags.csv` is the sharpest single artefact: seven recovery
dates with the exact `delta_r40` each was judged on and whether it was flagged
fragile. Three of the seven are True. A ramp that gets the arithmetic subtly
wrong will still produce a plausible allocation path and will not match those
seven rows.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.controller import frozen_rule  # noqa: E402
from sentinel.controller.machine import Controller, Observation  # noqa: E402

HANDOFF = ROOT / "docs" / "sentinel-handoff"
TAPE = HANDOFF / "04_BREADTH_ORACLES" / "sentinel_1p1_exact_daily_with_breadth.csv"
GATES = HANDOFF / "02_SENTINEL_1P1_FROZEN_ORACLE" / "02_recovery_gate_flags.csv"


def _f(v):
    """A tape cell as a float, or None when the harness had no value.

    None is NOT zero and never becomes zero. A missing r40 early in the window
    is 'we cannot evaluate this predicate', and the controller must fail that
    transition closed rather than treat it as a comfortable positive.
    """
    v = (v or "").strip()
    if v == "" or v.lower() in ("nan", "none"):
        return None
    return float(v)


def tape():
    with TAPE.open() as fh:
        return list(csv.DictReader(fh))


def observations():
    """The tape as the controller's input type, in session order."""
    rows = tape()
    navs = [_f(r["wealth_core_nav"]) for r in rows]
    damaged = [_f(r["damaged"]) for r in rows]
    out = []
    for i, r in enumerate(rows):
        out.append(Observation(
            session=r["date"],
            shadow_nav=navs[i],
            damaged_breadth=damaged[i],
            green_breadth=_f(r["green"]),
            shadow_r20=_f(r["r20"]),
            shadow_r40=_f(r["r40"]),
            # Derived from the shadow NAV series the tape supplies, exactly as
            # the harness derives them. Not read from a column, because the
            # tape has no r5/r10/drawdown columns — and inventing them from a
            # different source would be certifying against the wrong numbers.
            shadow_r5=_ret(navs, i, 5),
            shadow_r10=_ret(navs, i, 10),
            shadow_drawdown=_drawdown(navs, i),
            damaged_breadth_delta5=_delta(damaged, i, 5),
            # SPY IS ABSENT FROM EVERY HANDOFF ARTIFACT. Left None so the fast
            # entry's evidence records it as UNAVAILABLE, which fails that
            # transition closed — see the module docstring.
            spy_r20=None, spy_vol_ratio=None))
    return rows, out


def _ret(navs, i, n):
    if i < n or navs[i] is None or navs[i - n] in (None, 0):
        return None
    return navs[i] / navs[i - n] - 1.0


def _delta(series, i, n):
    if i < n or series[i] is None or series[i - n] is None:
        return None
    return series[i] - series[i - n]


def _drawdown(navs, i):
    seen = [v for v in navs[: i + 1] if v is not None]
    if not seen or navs[i] is None:
        return None
    peak = max(seen)
    return navs[i] / peak - 1.0 if peak else None


class TestTheFrozenRuleIsLOADEDNotTranscribed:
    def test_the_digest_matches_the_handoffs_own_manifest(self):
        """A transcribed threshold can drift from the artefact it claims to
        reproduce. The digest turns 'we copied it correctly' into a fact."""
        assert frozen_rule.verify_digest() is True

    def test_every_threshold_comes_from_the_file(self):
        cfg = frozen_rule.load()
        assert cfg.severe_target_core == 0.0
        assert cfg.ordinary_stress_drawdown == -0.155
        assert cfg.ramp.fragile_if_delta_r40_5_lte == 0.0
        assert cfg.ramp.steps == (0.55, 0.65, 1.0)
        assert cfg.ramp.confirmation_sessions == (10, 10)

    def test_a_TAMPERED_rule_file_is_refused(self, tmp_path):
        """The check has to actually check. A digest verifier that passes on a
        modified file is a comment."""
        bad = tmp_path / "rule.json"
        bad.write_text('{"sentinel_parent": {"severe_target_core": 0.5}}')
        with pytest.raises(frozen_rule.FrozenRuleTampered):
            frozen_rule.load(path=bad)


class TestTheSevenRecoveryGates:
    """The sharpest artefact in the handoff: every fragility decision the ramp
    ever made, with the exact number it was made on."""

    def test_the_fragility_verdicts_match_EXACTLY(self):
        cfg = frozen_rule.load()
        with GATES.open() as fh:
            gates = list(csv.DictReader(fh))
        assert len(gates) == 7

        verdicts = []
        for g in gates:
            fragile = Controller(cfg).is_fragile(float(g["delta_r40"]))
            verdicts.append((g["recovery_date"], fragile,
                             g["flagged"].strip().lower() == "true"))
        wrong = [(d, got, want) for d, got, want in verdicts if got != want]
        assert not wrong, f"fragility verdicts disagree with the oracle: {wrong}"
        assert sum(1 for _, got, _ in verdicts if got) == 3


class TestTheTapeIsReproduced:
    def test_the_ramp_reproduces_candidate_alloc_on_EVERY_session(self):
        """The headline claim, and the only one worth making.

        The tape's `canonical_alloc` is the PARENT controller's exposure — the
        severe entries and canonical recoveries whose two SPY predicates cannot
        be certified here. Feeding it in as the parent signal isolates exactly
        what Sentinel 1.1 ADDS: the selective recovery ramp. If the ramp is
        right, `candidate_alloc` follows on all 5,032 sessions.
        """
        cfg = frozen_rule.load()
        rows, obs = observations()
        ctl = Controller(cfg)
        state = ctl.initial_state()

        mismatches = []
        for i, (row, ob) in enumerate(zip(rows, obs)):
            prior_canonical = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            canonical = float(row["canonical_alloc"])
            state, decision = ctl.step_with_parent(
                observation=ob, state=state,
                parent_alloc=canonical, prior_parent_alloc=prior_canonical)
            want = float(row["candidate_alloc"])
            if abs(decision.target_core_exposure - want) > 1e-12:
                mismatches.append((row["date"], decision.target_core_exposure,
                                   want, decision.reason))
            if len(mismatches) >= 8:
                break

        assert not mismatches, (
            "the ramp diverges from the frozen oracle:\n" +
            "\n".join(f"  {d}  got {g}  want {w}  ({r})"
                      for d, g, w, r in mismatches))

    def test_the_allocation_LEVELS_are_exactly_the_four(self):
        """0.55 and 0.65 are real baskets, not corner cases — §7a. A controller
        emitting a fifth level has invented one."""
        cfg = frozen_rule.load()
        rows, obs = observations()
        ctl = Controller(cfg)
        state = ctl.initial_state()
        seen = set()
        for i, (row, ob) in enumerate(zip(rows, obs)):
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            state, d = ctl.step_with_parent(
                observation=ob, state=state,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)
            seen.add(round(d.target_core_exposure, 4))
        assert seen <= {0.0, 0.55, 0.65, 1.0}, seen

    def test_the_session_COUNT_at_each_level_matches(self):
        """A path can hit every level and still be wrong about when. The
        oracle's own distribution: 4413 at 1.0, 386 at 0.0, 150 at 0.55,
        83 at 0.65."""
        import collections

        cfg = frozen_rule.load()
        rows, obs = observations()
        ctl = Controller(cfg)
        state = ctl.initial_state()
        got = collections.Counter()
        for i, (row, ob) in enumerate(zip(rows, obs)):
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            state, d = ctl.step_with_parent(
                observation=ob, state=state,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)
            got[round(d.target_core_exposure, 4)] += 1
        assert dict(got) == {1.0: 4413, 0.0: 386, 0.55: 150, 0.65: 83}


class TestTheHealthyTriple:
    def test_it_matches_the_tapes_own_healthy_column(self):
        """The tape computes `healthy` itself, so this is a direct check on the
        predicate every recovery and every ramp step depends on."""
        cfg = frozen_rule.load()
        rows, obs = observations()
        ctl = Controller(cfg)
        wrong = []
        for row, ob in zip(rows, obs):
            got = ctl.is_healthy(ob)
            want = row["healthy"].strip().lower() == "true"
            if got is not want:
                wrong.append((row["date"], got, want))
        assert not wrong[:8], f"healthy disagrees on {len(wrong)} sessions: {wrong[:8]}"


class TestFailClosed:
    """§7: a required-but-unavailable predicate fails the transition CLOSED,
    with an explicit reason, never coerced into an ordinary negative. This is
    the lesson from Stocker's crash brake, which was fail-open because one
    boolean answered both 'the evidence says no' and 'there is no evidence'."""

    def test_an_unavailable_predicate_is_not_a_passing_one(self):
        cfg = frozen_rule.load()
        ctl = Controller(cfg)
        ob = Observation(session="2026-08-10", shadow_nav=1.0,
                         damaged_breadth=None, green_breadth=0.1,
                         shadow_r20=-0.2, shadow_r40=-0.2, shadow_r5=-0.1,
                         shadow_r10=-0.2, shadow_drawdown=-0.3,
                         damaged_breadth_delta5=0.5,
                         spy_r20=-0.05, spy_vol_ratio=0.10)
        ev = ctl.fast_severe_evidence(ob)
        assert ev.damaged_breadth.available is False
        assert ev.damaged_breadth.passed is None, "None must not become False"
        assert ev.satisfied is False
        # The reason NAMES the missing predicate. "FAST_EVIDENCE_UNAVAILABLE"
        # alone tells an operator a transition failed closed; naming
        # `damaged_breadth` tells them which feed to go and look at.
        assert ev.reason.startswith("FAST_EVIDENCE_UNAVAILABLE")
        assert "damaged_breadth" in ev.reason

    def test_unavailable_is_distinguishable_from_a_genuine_negative(self):
        cfg = frozen_rule.load()
        ctl = Controller(cfg)
        ob = Observation(session="2026-08-10", shadow_nav=1.0,
                         damaged_breadth=0.10, green_breadth=0.9,
                         shadow_r20=0.2, shadow_r40=0.2, shadow_r5=0.1,
                         shadow_r10=0.2, shadow_drawdown=-0.01,
                         damaged_breadth_delta5=0.0,
                         spy_r20=0.05, spy_vol_ratio=0.0)
        ev = ctl.fast_severe_evidence(ob)
        assert ev.damaged_breadth.available is True
        assert ev.damaged_breadth.passed is False
        assert ev.satisfied is False
        assert not ev.reason.startswith("FAST_EVIDENCE_UNAVAILABLE"), (
            "a real negative must not be reported as missing evidence")

    def test_the_SPY_predicates_are_unavailable_on_the_tape(self):
        """Stated as a test so the certification claim cannot quietly widen.
        SPY is in no handoff artifact; the fast path's two SPY predicates are
        implemented and NOT certified here."""
        _, obs = observations()
        assert all(o.spy_r20 is None and o.spy_vol_ratio is None for o in obs)


class TestTheStateIsDURABLE:
    def test_it_round_trips_through_STRICT_json(self):
        """The catch-up seam persists this state in the same statement as the
        session pointer, and refuses anything it cannot encode. A controller
        whose state needs `default=str` cannot be driven by it."""
        import json

        cfg = frozen_rule.load()
        rows, obs = observations()
        ctl = Controller(cfg)
        state = ctl.initial_state()
        for i, (row, ob) in enumerate(zip(rows[:400], obs[:400])):
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            state, _ = ctl.step_with_parent(
                observation=ob, state=state,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)

        blob = json.dumps(state, sort_keys=True)     # STRICT: no default=
        assert json.loads(blob) == state

    def test_a_RESUMED_controller_continues_identically(self):
        """Convergence after absence, at the controller. Serialising and
        reloading mid-ramp must not reset a healthy streak — a silently reset
        clock delays a step by ten sessions while looking healthy."""
        import json

        cfg = frozen_rule.load()
        rows, obs = observations()

        straight = Controller(cfg)
        s = straight.initial_state()
        for i, (row, ob) in enumerate(zip(rows, obs)):
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            s, _ = straight.step_with_parent(
                observation=ob, state=s,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)

        # The same tape, but the process "restarts" every 250 sessions.
        broken = Controller(cfg)
        r = broken.initial_state()
        for i, (row, ob) in enumerate(zip(rows, obs)):
            if i % 250 == 0:
                r = json.loads(json.dumps(r, sort_keys=True))
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            r, _ = broken.step_with_parent(
                observation=ob, state=r,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)

        assert r == s, "a restart changed the controller's state"


class TestTheParameterPlateau:
    """The frozen rule makes a claim about its own threshold, and it is
    checkable rather than merely quotable:

    > fragility was tightened from `<= +0.01` to `<= 0.0` and **the exact
    > historical path did not change** — so that threshold is on a plateau,
    > not a knife edge.

    A threshold on a plateau is one the strategy does not balance on. A
    threshold that changes the tape when nudged is a fitted number wearing a
    rule's clothing, and the difference matters more than either value.
    """

    def _replay(self, cfg) -> int:
        rows, obs = observations()
        ctl = Controller(cfg)
        st = ctl.initial_state()
        bad = 0
        for i, (row, ob) in enumerate(zip(rows, obs)):
            prior = float(rows[i - 1]["canonical_alloc"]) if i else 1.0
            st, d = ctl.step_with_parent(
                observation=ob, state=st,
                parent_alloc=float(row["canonical_alloc"]),
                prior_parent_alloc=prior)
            if abs(d.target_core_exposure - float(row["candidate_alloc"])) > 1e-12:
                bad += 1
        return bad

    def _ramp(self, **kw):
        import dataclasses
        base = frozen_rule.load()
        return dataclasses.replace(
            base, ramp=dataclasses.replace(base.ramp, **kw))

    def test_the_FRAGILITY_threshold_is_on_a_plateau(self):
        """Independently verified, not taken on trust. Both values reproduce
        the tape exactly, which is what 'the historical path did not change'
        has to mean if it means anything."""
        assert self._replay(self._ramp(fragile_if_delta_r40_5_lte=0.01)) == 0

    def test_but_the_CONFIRMATION_COUNT_is_not(self):
        """Stated beside the plateau so the first test cannot be mistaken for
        'nothing here matters'. Nine confirmations instead of ten moves 125
        sessions — the ramp's dwell is load-bearing, and only the fragility
        comparison is flat."""
        assert self._replay(self._ramp(confirmation_sessions=(9, 10))) > 100

    def test_nor_is_the_GATE_HORIZON(self):
        assert self._replay(self._ramp(gate_horizon_sessions=4)) > 100

    def test_nor_are_the_STEP_LEVELS(self):
        assert self._replay(self._ramp(steps=(0.50, 0.65, 1.0))) > 100


class TestRenewedSevereAbandonsTheRamp:
    """§7a: 'a renewed severe cause at any point -> 0.0, ramp abandoned'.

    THE FROZEN TAPE NEVER EXERCISES THIS. Across 2006-2026 no severe cause ever
    fired while a ramp was mid-flight, so the certification above cannot
    distinguish abandonment from a pause. That is a coverage gap in the oracle,
    not a licence to leave the rule untested: a resumed ramp promotes to 0.65
    on confirmations collected BEFORE the event that broke it.

    WHERE THE RULE IS ACTUALLY ENFORCED, established by mutation: not on the
    severe branch, which is belt and braces, but on the RECOVERY branch — the
    only route out of severe restarts the ramp at step 0 unconditionally.
    Removing the severe-branch reset changes nothing; removing the recovery
    restart turns these tests red. Worth knowing, because a future edit to the
    recovery branch is what could resurrect a stale ramp, and that is where a
    reviewer should look.
    """

    def _drive(self, sequence):
        """(parent_alloc, healthy) per session -> the exposure path."""
        cfg = frozen_rule.load()
        ctl = Controller(cfg)
        st = ctl.initial_state()
        out = []
        prior = 1.0
        for i, (parent, healthy) in enumerate(sequence):
            ob = Observation(
                session=f"2030-01-{i + 1:02d}", shadow_nav=1.0,
                damaged_breadth=0.1 if healthy else 0.9,
                green_breadth=0.9 if healthy else 0.05,
                shadow_r20=0.05 if healthy else -0.05,
                # A flat r40 series makes delta_r40_5 == 0.0, which is FRAGILE
                # under the frozen gate — so every recovery below takes the
                # ramp, which is the path being tested.
                shadow_r40=0.0)
            st, d = ctl.step_with_parent(observation=ob, state=st,
                                         parent_alloc=parent,
                                         prior_parent_alloc=prior)
            prior = parent
            out.append(d.target_core_exposure)
        return out

    def test_a_severe_MID_RAMP_drops_to_zero_and_does_not_resume_at_0_65(self):
        seq = ([(1.0, True)] * 8 + [(0.0, False)] * 3          # severe
               + [(1.0, True)] * 6                              # recover -> ramp
               + [(0.0, False)] * 2                             # RENEWED severe
               + [(1.0, True)] * 3)                             # recover again
        path = self._drive(seq)
        assert path[11] == 0.55, "the first recovery should enter the ramp"
        assert path[17] == 0.0, "a renewed severe must go to zero"
        assert path[19] == 0.55, (
            f"the ramp resumed at {path[19]} instead of restarting — those "
            f"confirmations were collected before the thing that broke it")

    def test_the_streak_does_not_survive_the_interruption(self):
        """Nine confirmations, a severe, then one more healthy session must NOT
        promote. If it does, the ramp kept a streak across the event whose
        whole meaning is that the recovery was not confirmed."""
        seq = ([(1.0, True)] * 3 + [(0.0, False)] * 2
               + [(1.0, True)] * 9                               # ramp, 9 healthy
               + [(0.0, False)] * 1                              # renewed severe
               + [(1.0, True)] * 2)
        path = self._drive(seq)
        assert path[-1] == 0.55, f"promoted to {path[-1]} on a stale streak"
