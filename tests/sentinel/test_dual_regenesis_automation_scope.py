from __future__ import annotations

import asyncio

from sentinel import automation_recovery, dual_reconciliation


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


def test_prepare_scopes_handover_establishment_and_resets_after_return(monkeypatch):
    runtime = _runtime()
    runtime._require_backup_for_new_mutation = lambda _operation: None
    observed = []

    async def base_prepare(_self, _context):
        observed.append(
            automation_recovery._ESTABLISH_REGENESIS_HANDOVER.get())
        return "prepared"

    monkeypatch.setattr(
        automation_recovery.base.ProductionAutomation, "prepare", base_prepare)

    assert automation_recovery._ESTABLISH_REGENESIS_HANDOVER.get() is False
    result = asyncio.run(runtime.prepare(object()))

    assert result == "prepared"
    assert observed == [True]
    assert automation_recovery._ESTABLISH_REGENESIS_HANDOVER.get() is False


def test_prepare_scope_resets_even_when_base_prepare_raises(monkeypatch):
    runtime = _runtime()
    runtime._require_backup_for_new_mutation = lambda _operation: None

    async def base_prepare(_self, _context):
        assert automation_recovery._ESTABLISH_REGENESIS_HANDOVER.get() is True
        raise RuntimeError("boom")

    monkeypatch.setattr(
        automation_recovery.base.ProductionAutomation, "prepare", base_prepare)

    try:
        asyncio.run(runtime.prepare(object()))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover - falsifier guard
        raise AssertionError("base prepare should have raised")

    assert automation_recovery._ESTABLISH_REGENESIS_HANDOVER.get() is False
