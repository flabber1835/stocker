"""Independent checkpoint facts exercise the actual production restart guard."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from sentinel.core import catchup
from sentinel.core.kernel import advance_session
from sentinel.execution.plan import ExecutionPlan
from sentinel.feed import calendar
from tests.internal_state.contract import digest
from tests.internal_state.test_market import formed_state, inputs


@pytest.mark.parametrize("fault", ["intact", "state", "missing", "session", "anchor", "extra", "strategy",
                                   "controller", "book", "missing_feed"])
def test_intermediate_resume_requires_exact_independent_commitment(monkeypatch, fault):
    config, prior = formed_state(days=1)
    day = calendar.next_session(prior.last_processed_session)
    _, _, published = inputs(day)
    current = advance_session(prior, published, controller_config=config,
                              strategy_identity=prior.strategy_identity).to_dict()
    template = ExecutionPlan(plan_id="pending", decision_session=date.fromisoformat(prior.last_processed_session),
        effective_session=date.fromisoformat(day), target_exposure=Decimal(1),
        data_version=prior.data_version, shadow_snapshot_hash=prior.state_hash,
        sentinel_transition_hash=digest(prior.last_decision), strategy_fingerprint=digest(prior.strategy_identity))
    plan = replace(template, plan_id="sentinel-" + template.fingerprint())
    proof = {"schema": "sentinel.catchup-resume/1", "session": day,
             "state_sha256": digest(current), "anchor_plan_id": plan.plan_id,
             "anchor_plan_fingerprint": plan.fingerprint()}
    checkpoint = (day, proof)
    if fault == "state":
        current["shadow_peak_nav"] += 1
    elif fault == "missing":
        checkpoint = None
    elif fault == "session":
        checkpoint = (prior.last_processed_session, proof)
    elif fault == "anchor":
        proof["anchor_plan_id"] = "sentinel-another"
    elif fault == "extra":
        proof["unrecognized_authority"] = True
    elif fault == "strategy":
        current["strategy_identity"] = dict(current["strategy_identity"], strategy="changed")
        proof["state_sha256"] = digest(current)
    elif fault == "controller":
        current["controller"]["ordinary_stress_age"] = 21
        proof["state_sha256"] = digest(current)
    elif fault == "book":
        current["wealth_core"]["entry_sizing_profile"] = "changed"
        proof["state_sha256"] = digest(current)
    elif fault == "missing_feed":
        del current["feed"]
        proof["state_sha256"] = digest(current)

    class ReadOnlyFacts:
        def cursor(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, query, params):
            assert query.startswith("SELECT ")
            self.query = query
        def fetchone(self):
            if self.query.startswith("SELECT session,state"):
                return deepcopy(checkpoint)
            if self.query.startswith("SELECT session FROM"):
                return (day,)
            if self.query.startswith("SELECT state FROM"):
                return (deepcopy(current),)
            raise AssertionError(self.query)
    monkeypatch.setattr(catchup.journal, "latest_plan", lambda conn: plan)
    if fault == "intact":
        assert catchup.resume_state(ReadOnlyFacts()) == current
    else:
        with pytest.raises(catchup.StateCommitmentMismatch):
            catchup.resume_state(ReadOnlyFacts())
