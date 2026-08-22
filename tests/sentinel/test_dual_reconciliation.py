from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import dual_reconciliation as dual


SESSION = "2026-08-20"
STATE_HASH = "a" * 64
AUTHORITY = "b" * 64


def _plan(**changes):
    values = {
        "decision_session": date.fromisoformat(SESSION),
        "effective_session": date.fromisoformat("2026-08-21"),
        "shadow_snapshot_hash": STATE_HASH,
        "data_version": 7,
        "target_exposure": Decimal("0.55"),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _result(**changes):
    state = SimpleNamespace(
        last_processed_session=SESSION,
        state_hash=STATE_HASH,
        data_version=7,
        last_decision={
            "session": SESSION,
            "target_core_exposure": "0.55",
        })
    values = {
        "session": SESSION,
        "shadow_verdict": "SHADOW_GO",
        "verification": "VERIFIED",
        "state": state,
        "record_sha256": "c" * 64,
        "runtime_authority_sha256": AUTHORITY,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_exact_plan_state_session_and_exposure_match(monkeypatch):
    monkeypatch.setattr(
        dual.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(
        dual.dual_plan_authority, "rederive_plan",
        lambda *_args, **_kwargs: {
            "authority_sha256": "d" * 64,
            "plan_fingerprint": "e" * 64,
        })

    result = dual.require_plan_matches_verified_shadow(
        object(), plan=_plan(), observation_id="year-end",
        starting_cash="100000", binding=object(), rollout_state=object())

    assert result == {
        "schema": "sentinel.dual-plan-shadow-reconciliation/1",
        "decision_session": SESSION,
        "effective_session": "2026-08-21",
        "state_sha256": STATE_HASH,
        "shadow_record_sha256": "c" * 64,
        "shadow_runtime_authority_sha256": AUTHORITY,
        "sizing_authority_sha256": "d" * 64,
        "plan_fingerprint": "e" * 64,
        "target_core_exposure": "0.55",
        "verdict": "MATCH",
    }


def test_missing_or_behind_shadow_is_retryable(monkeypatch):
    monkeypatch.setattr(
        dual.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: None)
    with pytest.raises(dual.DualReconciliationPending):
        dual.require_plan_matches_verified_shadow(
            object(), plan=_plan(), observation_id="year-end",
            starting_cash="100000")

    monkeypatch.setattr(
        dual.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: _result(session="2026-08-19"))
    with pytest.raises(dual.DualReconciliationPending):
        dual.require_plan_matches_verified_shadow(
            object(), plan=_plan(), observation_id="year-end",
            starting_cash="100000")


@pytest.mark.parametrize("change", [
    {"shadow_snapshot_hash": "d" * 64},
    {"data_version": 8},
    {"target_exposure": Decimal("0.54")},
    {"effective_session": date.fromisoformat("2026-08-24")},
])
def test_any_plan_economic_drift_is_permanent_refusal(monkeypatch, change):
    monkeypatch.setattr(
        dual.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: _result())
    with pytest.raises(dual.DualReconciliationRefused):
        dual.require_plan_matches_verified_shadow(
            object(), plan=_plan(**change), observation_id="year-end",
            starting_cash="100000")


def test_ahead_or_invalid_shadow_is_permanent_refusal(monkeypatch):
    monkeypatch.setattr(
        dual.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: _result(session="2026-08-21"))
    with pytest.raises(dual.DualReconciliationRefused):
        dual.require_plan_matches_verified_shadow(
            object(), plan=_plan(), observation_id="year-end",
            starting_cash="100000")

    def refused(*_args, **_kwargs):
        raise dual.shadow_runtime.ShadowRuntimeRefused("revised warmup")

    monkeypatch.setattr(
        dual.shadow_runtime, "verified_shadow_status", refused)
    with pytest.raises(dual.DualReconciliationRefused, match="revised warmup"):
        dual.require_plan_matches_verified_shadow(
            object(), plan=_plan(), observation_id="year-end",
            starting_cash="100000")
