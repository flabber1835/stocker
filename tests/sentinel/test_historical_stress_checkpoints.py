"""Named historical checkpoints through the production Sentinel controller.

The full 5,032-session differential remains the stronger equality proof. These
checkpoints make stressful periods visible as first-class certification cases
and prevent a generic all-tape pass from obscuring which regimes were present.
"""
from __future__ import annotations

from sentinel.controller import frozen_rule
from sentinel.controller.machine import Controller
from tests.sentinel.test_controller_certification import observations


CHECKPOINTS = {
    "2008-10-10": ("global-financial-crisis", 0.0),
    "2010-05-06": ("flash-crash", 1.0),
    "2015-08-24": ("august-2015-shock", 1.0),
    "2018-02-05": ("volatility-shock", 1.0),
    "2018-12-24": ("q4-2018-selloff", 0.0),
    "2020-03-16": ("covid-crash", 0.0),
    "2021-01-28": ("meme-stock-period", 1.0),
    "2022-06-13": ("2022-bear-market", 0.0),
}


def test_named_stress_checkpoints_replay_the_frozen_economic_state():
    rows, tape = observations()
    controller = Controller(frozen_rule.load())
    state = controller.initial_state()
    seen = {}

    for index, (row, observation) in enumerate(zip(rows, tape)):
        prior_parent = (
            float(rows[index - 1]["canonical_alloc"]) if index else 1.0)
        state, decision = controller.step_with_parent(
            observation=observation,
            state=state,
            parent_alloc=float(row["canonical_alloc"]),
            prior_parent_alloc=prior_parent,
        )
        if row["date"] in CHECKPOINTS:
            label, expected_exposure = CHECKPOINTS[row["date"]]
            seen[row["date"]] = {
                "label": label,
                "exposure": decision.target_core_exposure,
                "durable_last_session": state["last_session"],
            }
            assert decision.target_core_exposure == expected_exposure
            assert decision.target_core_exposure == float(row["candidate_alloc"])
            assert state["last_session"] == row["date"]

    assert set(seen) == set(CHECKPOINTS)
