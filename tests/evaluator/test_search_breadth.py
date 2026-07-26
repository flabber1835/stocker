"""Search breadth: fill the lane with INDEPENDENT hypotheses.

The bottleneck was neither the promotion gate nor the lane. The per-review cap
was 4 and the lane's weekly candidate cap is 5 — and the W30 review queued ONE
candidate, leaving four slots idle. The system was not rejecting ideas; it was
not generating them.

Raising the budget only helps if the extra slots carry INDEPENDENT hypotheses:
four momentum thresholds are one hypothesis wearing four slots. Since the whole
change rests on that property, it is enforced deterministically rather than
merely requested in the prompt — which is exactly the mistake (trusting an
instruction to carry a load-bearing property) that produced the
under-generation.
"""
import pytest

from app.tools import (MECHANISMS, MAX_QUEUED_EXPERIMENTS,
                       experiment_diversity_conflict, overlapping_fields)
from app.packet import mechanism_scorecard


def _pending(mech, fields, cfg_hash="abc123", hyp="h"):
    return {"mechanism": mech, "changed_fields": list(fields),
            "config_hash": cfg_hash, "hypothesis": hyp}


# ── budget ───────────────────────────────────────────────────────────────────

def test_budget_matches_the_lane_capacity():
    """5 per review against the lane's 5 candidate slots per week (baselines
    fire outside that cap). Raising this alone does nothing if the lane cap
    does not move with it."""
    assert MAX_QUEUED_EXPERIMENTS == 5


# ── mechanism vocabulary ─────────────────────────────────────────────────────

def test_mechanisms_cover_the_distinct_places_a_strategy_can_be_wrong():
    for m in ("factor_weighting", "entry_selection", "exit_hysteresis",
              "portfolio_construction", "concentration_control", "risk_control",
              "turnover_control", "universe"):
        assert m in MECHANISMS, f"{m} missing from the mechanism vocabulary"
    assert all(isinstance(v, str) and v for v in MECHANISMS.values()), (
        "every mechanism needs a description — the model picks from it blind")


# ── independence enforcement ─────────────────────────────────────────────────

class TestDiversityConflict:
    def test_first_candidate_of_a_mechanism_is_accepted(self):
        assert experiment_diversity_conflict([], "exit_hysteresis", {"a"}) is None

    def test_second_draw_on_the_same_mechanism_is_refused(self):
        """THE case: four variants of one knob is ONE experiment."""
        pending = [_pending("factor_weighting", ["static_factor_weights.momentum"])]
        why = experiment_diversity_conflict(
            pending, "factor_weighting", {"static_factor_weights.quality"})
        assert why and "factor_weighting" in why
        assert "already queued" in why

    def test_a_different_mechanism_is_accepted_even_touching_a_shared_field(self):
        """Overlap short of equality is legitimate — two theses can move the
        same knob for different reasons. Refusing it would block real breadth."""
        pending = [_pending("exit_hysteresis", ["delta_engine.exit_rank"])]
        assert experiment_diversity_conflict(
            pending, "turnover_control",
            {"delta_engine.exit_rank",
             "delta_engine.rebalance_drift_threshold"}) is None

    def test_identical_field_set_is_refused_as_the_backstop(self):
        """Catches an unlabelled repeat: same knobs, different values. The
        mechanism label is authoritative; this is the safety net under it."""
        pending = [_pending("factor_weighting", ["a", "b"])]
        why = experiment_diversity_conflict(pending, "risk_control", {"b", "a"})
        assert why and "identical changed-field set" in why

    def test_an_empty_diff_does_not_trip_the_field_backstop(self):
        """An empty field set must not match another empty one and refuse
        everything — the empty-diff case is rejected earlier, on its own terms."""
        pending = [_pending("factor_weighting", [])]
        assert experiment_diversity_conflict(pending, "risk_control", set()) is None

    def test_unlabelled_pending_entries_do_not_block_a_mechanism(self):
        """Proposals queued before the label existed carry no mechanism; they
        must not silently veto every new candidate."""
        pending = [{"changed_fields": ["x"], "config_hash": "old"}]
        assert experiment_diversity_conflict(pending, "risk_control", {"y"}) is None

    def test_the_refusal_names_the_alternatives(self):
        """A refusal that does not say what to do instead just wastes the turn."""
        pending = [_pending("risk_control", ["p"])]
        why = experiment_diversity_conflict(pending, "risk_control", {"q"})
        assert "Mechanisms:" in why and "turnover_control" in why


def test_overlap_is_reported_not_refused():
    pending = [_pending("exit_hysteresis", ["a", "b"])]
    assert overlapping_fields(pending, {"b", "c"}) == {"b"}
    assert overlapping_fields(pending, {"z"}) == set()


# ── learning from failure: aggregate by CLASS of intervention ────────────────

class TestMechanismScorecard:
    def _exp(self, mech, eligible=None, status="success", edge=None):
        e = {"kind": "full_config", "mechanism": mech, "status": status}
        if eligible is not None:
            e["promotion"] = {"eligible": eligible, "reason": "r"}
        if edge is not None:
            e["prediction"] = {"actual_edge": edge}
        return e

    def test_repeated_failures_of_one_class_become_visible(self):
        """'exit-hysteresis has failed 4 for 4' is the sharpest thing a failed
        experiment can say, and it was not computable when results were
        attributable only per config hash."""
        exps = [self._exp("exit_hysteresis", eligible=False) for _ in range(4)]
        m = mechanism_scorecard(exps)["mechanisms"]["exit_hysteresis"]
        assert m == {"queued": 4, "scored": 4, "promoted": 0, "refused": 4,
                     "not_scored": 0, "best_tune_edge": None}

    def test_unscored_runs_are_not_counted_as_refusals(self):
        """A mechanism whose runs never completed has proved nothing — counting
        them as failures would argue against a class on zero evidence."""
        exps = [self._exp("risk_control", status="failed"),
                self._exp("risk_control", eligible=True)]
        m = mechanism_scorecard(exps)["mechanisms"]["risk_control"]
        assert m["not_scored"] == 1 and m["scored"] == 1 and m["promoted"] == 1
        assert m["refused"] == 0

    def test_best_edge_is_tracked_per_mechanism(self):
        exps = [self._exp("factor_weighting", eligible=False, edge=-0.02),
                self._exp("factor_weighting", eligible=False, edge=0.005)]
        m = mechanism_scorecard(exps)["mechanisms"]["factor_weighting"]
        assert m["best_tune_edge"] == pytest.approx(0.005)

    def test_legacy_entries_group_as_unlabelled_rather_than_vanishing(self):
        m = mechanism_scorecard([{"kind": "full_config", "status": "success",
                                  "promotion": {"eligible": False}}])
        assert m["mechanisms"]["unlabelled"]["refused"] == 1

    def test_baselines_are_excluded(self):
        """A baseline tests no hypothesis; counting it would dilute every rate."""
        assert mechanism_scorecard(
            [{"kind": "baseline", "status": "success"}])["mechanisms"] == {}


# ── the prompt has to ask for breadth AND for accounting ────────────────────

def test_prompt_requires_using_slots_and_justifying_idle_ones():
    """An LLM told 'queue one if warranted' optimises for precision. The
    instruction has to change the objective to expected information gain — and
    make idle capacity explicit rather than silent."""
    from app.report import SYSTEM_PROMPT
    p = SYSTEM_PROMPT.lower()
    assert "breadth" in p
    assert "unused" in p, "idle slots must be accounted for, not silently left"
    assert "variant" in p, "must warn against padding with parameter variants"
    assert "refuted" in p, "a refuted candidate must be framed as a success"
    assert "dsr" in p or "deflated" in p, (
        "the model must be told DSR falling with trial count is correct "
        "accounting, or it will read it as decay and argue to weaken it")
