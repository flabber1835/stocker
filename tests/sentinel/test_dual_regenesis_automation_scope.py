from __future__ import annotations

import asyncio

import pytest

from sentinel import (
    automation_recovery,
    dual_plan_authority,
    dual_reconciliation,
)
from sentinel.automation.model import NonRetryableCallbackRefused


def _runtime():
    runtime = object.__new__(automation_recovery.ProductionAutomation)
    runtime._dual_run_enabled = True
    runtime._shadow_observation_id = "primary"
    runtime._shadow_starting_cash = "100000"
    return runtime


def test_dual_match_is_verification_only_outside_prepare(monkeypatch):
    runtime = _runtime()
    observed = []

    def require(*_args, **kwargs):
        observed.append(kwargs["establish_regenesis_handover"])
        return {"verdict": "MATCH"}

    monkeypatch.setattr(
        dual_reconciliation, "require_plan_matches_verified_shadow", require)

    result = runtime._require_dual_plan_shadow_match(
        object(), object(), pending_is_retryable=False)

    assert result == {"verdict": "MATCH"}
    assert observed == [False]
    assert dual_reconciliation.regenesis_preparation_active() is False
    assert dual_plan_authority.regenesis_flat_sizing_required() is False


def test_prepare_scopes_handover_and_first_plan_flat_sizing(monkeypatch):
    runtime = _runtime()
    runtime._require_backup_for_new_mutation = lambda _operation: None
    runtime._regenesis_flat_sizing_required = lambda: True
    observed = []

    async def base_prepare(_self, _context):
        observed.append((
            dual_reconciliation.regenesis_preparation_active(),
            dual_plan_authority.regenesis_flat_sizing_required(),
        ))
        return "prepared"

    monkeypatch.setattr(
        automation_recovery.base.ProductionAutomation, "prepare", base_prepare)

    assert dual_reconciliation.regenesis_preparation_active() is False
    assert dual_plan_authority.regenesis_flat_sizing_required() is False
    result = asyncio.run(runtime.prepare(object()))

    assert result == "prepared"
    assert observed == [(True, True)]
    assert dual_reconciliation.regenesis_preparation_active() is False
    assert dual_plan_authority.regenesis_flat_sizing_required() is False


def test_prepare_does_not_require_flat_sizing_after_handover(monkeypatch):
    runtime = _runtime()
    runtime._require_backup_for_new_mutation = lambda _operation: None
    runtime._regenesis_flat_sizing_required = lambda: False
    observed = []

    async def base_prepare(_self, _context):
        observed.append((
            dual_reconciliation.regenesis_preparation_active(),
            dual_plan_authority.regenesis_flat_sizing_required(),
        ))
        return "prepared"

    monkeypatch.setattr(
        automation_recovery.base.ProductionAutomation, "prepare", base_prepare)

    result = asyncio.run(runtime.prepare(object()))
    assert result == "prepared"
    assert observed == [(True, False)]


def test_prepare_scopes_reset_even_when_base_prepare_raises(monkeypatch):
    runtime = _runtime()
    runtime._require_backup_for_new_mutation = lambda _operation: None
    runtime._regenesis_flat_sizing_required = lambda: True

    async def base_prepare(_self, _context):
        assert dual_reconciliation.regenesis_preparation_active() is True
        assert dual_plan_authority.regenesis_flat_sizing_required() is True
        raise RuntimeError("boom")

    monkeypatch.setattr(
        automation_recovery.base.ProductionAutomation, "prepare", base_prepare)

    try:
        asyncio.run(runtime.prepare(object()))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover - falsifier guard
        raise AssertionError("base prepare should have raised")

    assert dual_reconciliation.regenesis_preparation_active() is False
    assert dual_plan_authority.regenesis_flat_sizing_required() is False


def test_legacy_nonflat_sizing_authority_cannot_be_rehabilitated(monkeypatch):
    runtime = _runtime()
    plan = type("Plan", (), {"plan_id": "post-gap-plan"})()
    calls = []

    monkeypatch.setattr(
        dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: {"plan_id": "post-gap-plan"})

    def refuse(*_args, **_kwargs):
        calls.append("checked")
        raise dual_plan_authority.DualPlanAuthorityRefused(
            "post-gap PAPER plan sizing requires a flat broker account")

    monkeypatch.setattr(
        dual_plan_authority, "require_regenesis_flat_authority", refuse)
    monkeypatch.setattr(
        dual_reconciliation, "require_plan_matches_verified_shadow",
        lambda *_args, **_kwargs: pytest.fail(
            "handover must not be attempted after contaminated sizing"))

    with dual_reconciliation.regenesis_preparation_scope(), \
            dual_plan_authority.regenesis_flat_sizing_scope(True):
        with pytest.raises(
                NonRetryableCallbackRefused,
                match="flat broker account"):
            runtime._require_dual_plan_shadow_match(
                object(), plan, pending_is_retryable=True)

    assert calls == ["checked"]


def test_nested_prepare_scope_restores_prior_context():
    assert dual_reconciliation.regenesis_preparation_active() is False
    assert dual_plan_authority.regenesis_flat_sizing_required() is False
    with dual_reconciliation.regenesis_preparation_scope(), \
            dual_plan_authority.regenesis_flat_sizing_scope(True):
        assert dual_reconciliation.regenesis_preparation_active() is True
        assert dual_plan_authority.regenesis_flat_sizing_required() is True
        with dual_reconciliation.regenesis_preparation_scope(), \
                dual_plan_authority.regenesis_flat_sizing_scope(False):
            assert dual_reconciliation.regenesis_preparation_active() is True
            assert dual_plan_authority.regenesis_flat_sizing_required() is False
        assert dual_reconciliation.regenesis_preparation_active() is True
        assert dual_plan_authority.regenesis_flat_sizing_required() is True
    assert dual_reconciliation.regenesis_preparation_active() is False
    assert dual_plan_authority.regenesis_flat_sizing_required() is False
