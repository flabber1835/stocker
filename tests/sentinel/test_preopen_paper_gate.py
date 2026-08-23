"""Focused arithmetic at the paper pre-open authority boundary."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import (
    dual_plan_authority,
    dual_reconciliation,
    handover,
    informational_paper_mirror,
    paper,
    schema,
    shadow_runtime,
    trial,
)
from sentinel.core import catchup
from sentinel.execution import journal, preopen_authority
from sentinel.execution import reconcile as reconciliation
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    BrokerPosition,
    Side,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import CorpusActionLookup
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import calendar, publication


SESSION = date(2026, 8, 21)
NOW = datetime(2026, 8, 21, 14, tzinfo=timezone.utc)
DEPLOYMENT = DeploymentIdentity(
    deployment_id="preopen-paper-test", broker="sim",
    broker_account_id="paper", takeover_epoch=1)


def _plan(*, basket=None, effective_session=SESSION,
          decision_session=date(2026, 8, 20)):
    candidate = ExecutionPlan(
        plan_id="",
        decision_session=decision_session,
        effective_session=effective_session,
        target_exposure=Decimal(1),
        target_basket=basket or {
            "SEC-A": Decimal(10), "SEC-ZERO": Decimal(0)},
        rollout_mode="PINNED_1_00", rollout_version=1)
    return replace(
        candidate, plan_id=f"sentinel-{candidate.fingerprint()}")


def _command(
        security_id, *, quantity, state, filled=Decimal(0),
        recovered_key=None, created_at=NOW):
    return Command(
        identity=CommandIdentity(
            deployment=DEPLOYMENT, plan_id="historical-plan",
            security_id=security_id),
        instrument=BrokerInstrument(security_id, security_id),
        side=Side.BUY, quantity=quantity, state=state,
        filled_quantity=filled, created_at=created_at,
        recovered_key=recovered_key)


def _observation(*, positions=(), orders=()):
    return BrokerObservation(
        observed_at=NOW, terminal_recovery_through=NOW,
        positions=tuple(positions), orders=tuple(orders))


class _RecoveryBroker:
    async def account_snapshot(self):
        return object()


def _install_recovery_harness(
        monkeypatch, *, plan, authority, commands, reconcile,
        cycle_generation=3, grant_generation=3, load_plan=None):
    """Install only the non-financial shell around recovery's unit boundary."""
    binding = SimpleNamespace(
        identity=DEPLOYMENT, broker_account_id=DEPLOYMENT.broker_account_id)
    cycle = SimpleNamespace(
        cycle_id="preopen-recovery-cycle",
        control_generation=cycle_generation,
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        decision_session=plan.decision_session,
        effective_session=plan.effective_session)
    grant = SimpleNamespace(
        operation_scope="RECOVER", certificate_sha256="certified-recovery",
        control_generation=grant_generation,
        broker_account_id=DEPLOYMENT.broker_account_id)
    broker = _RecoveryBroker()
    recorded = []

    monkeypatch.setattr(paper, "assert_paper_url", lambda *_: None)
    monkeypatch.setattr(
        paper, "_require_certified_paper_broker", lambda *_: None)
    monkeypatch.setattr(schema, "require_runtime_schema", lambda *_: None)
    monkeypatch.setattr(journal, "writer_lock", lambda *_: nullcontext())
    monkeypatch.setattr(
        handover, "assert_no_legacy_path", lambda *_: binding)
    monkeypatch.setattr(
        paper, "load_rollout_state", lambda *_: SimpleNamespace(mode="PINNED"))
    monkeypatch.setattr(paper, "_default_paper_strategy", lambda: (object(), {}))
    monkeypatch.setattr(
        publication, "require_current", lambda *_: SimpleNamespace(version=1))
    monkeypatch.setattr(
        paper, "require_current_authority",
        lambda *_args, **_kwargs: SimpleNamespace(
            certificate_sha256=grant.certificate_sha256))
    monkeypatch.setattr(
        paper, "_validate_automation_grant", lambda *_: (object(), cycle))
    monkeypatch.setattr(paper, "_guard_broker", lambda **_kwargs: broker)
    monkeypatch.setattr(
        paper, "_recovery_account_identity_or_refuse", lambda *_: None)

    async def activity_state(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(paper, "_broker_cash_state_or_refuse", activity_state)
    monkeypatch.setattr(catchup, "resume_state", lambda *_: {})
    monkeypatch.setattr(
        paper, "SessionState",
        SimpleNamespace(from_dict=lambda _raw: object()))
    action_base = CorpusActionLookup(
        start=plan.decision_session, events={})
    target_base = CorpusActionLookup(
        start=plan.decision_session, events={})
    monkeypatch.setattr(paper, "_action_lookup", lambda *_: action_base)
    monkeypatch.setattr(
        paper, "_target_action_lookup", lambda *_: target_base)
    monkeypatch.setattr(
        journal, "load_plan", load_plan or (lambda *_: plan))
    def load_commands(*_args, states=None, **_kwargs):
        if states is None:
            return tuple(commands)
        permitted = set(states)
        return tuple(command for command in commands
                     if command.state in permitted)

    monkeypatch.setattr(journal, "load_commands", load_commands)
    monkeypatch.setattr(
        preopen_authority, "load_authority", lambda *_args, **_kwargs: authority)
    monkeypatch.setattr(reconciliation, "reconcile", reconcile)
    monkeypatch.setattr(paper, "_account_or_refuse", lambda *_: None)
    monkeypatch.setattr(paper, "_cash_authority_or_refuse", lambda *_args, **_kwargs: None)

    async def evidence_bracket(**kwargs):
        return kwargs["initial_result"], object(), object(), NOW, NOW

    monkeypatch.setattr(
        paper, "_settled_account_evidence_bracket", evidence_bracket)
    monkeypatch.setattr(
        trial, "record_account_evidence",
        lambda *_args, **kwargs: recorded.append(kwargs))
    return grant, broker, recorded


def test_active_units_include_working_and_recovered_command_identities():
    commands = (
        _command(
            "SEC-B", quantity=Decimal(5), state=CommandState.FILLED,
            filled=Decimal(5)),
        _command(
            "SEC-C", quantity=Decimal(2),
            state=CommandState.ACKNOWLEDGED),
        _command(
            "SEC-INACTIVE", quantity=Decimal(1),
            state=CommandState.CANCELLED),
        _command(
            "SEC-RECOVERED", quantity=Decimal(1),
            state=CommandState.CANCELLED,
            recovered_key="sntl-recovered-terminal"),
    )
    actions = CorpusActionLookup(
        start=date(2026, 8, 19), events={})

    active = paper._preopen_active_security_ids(  # noqa: SLF001
        plan=_plan(), commands=commands, actions=actions)

    assert active == ("SEC-A", "SEC-B", "SEC-C", "SEC-RECOVERED")


def test_post_reconciliation_terminal_recovered_identity_requires_coverage():
    plan = _plan()
    cutoff = paper._official_preopen_cutoff(plan)  # noqa: SLF001
    authority = preopen_authority.PreOpenShareUnitAuthority(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        effective_session=plan.effective_session,
        provider="test-provider", publication_id="test-publication",
        as_of=cutoff, cutoff_at=cutoff, complete=True,
        coverage=(
            preopen_authority.ShareUnitCoverage.no_event("SEC-A"),))
    recovered = _command(
        "SEC-RECOVERED", quantity=Decimal(1),
        state=CommandState.CANCELLED,
        recovered_key="sntl-recovered-after-publication")

    with pytest.raises(
            paper.PreOpenShareUnitAuthorityUnavailable,
            match=r"missing=\['SEC-RECOVERED'\]"):
        paper._revalidate_preopen_authority_or_refuse(  # noqa: SLF001
            authority=authority, plan=plan, commands=(recovered,),
            actions=CorpusActionLookup(
                start=date(2026, 8, 19), events={}),
            required_cutoff_at=cutoff, evaluated_at=cutoff)


def test_only_empty_share_unit_domain_can_bypass_preopen_authority():
    instrument = BrokerInstrument("SEC-A", "AAA")
    flat = _observation(positions=(
        BrokerPosition(instrument, Decimal(10)),))
    flat_deltas = paper._plan_deltas(  # noqa: SLF001
        target_basket=_plan().target_basket, observation=flat,
        minimum_quantity_increment=Decimal(1))
    assert not paper._provably_clean_empty_noop(  # noqa: SLF001
        deltas=flat_deltas, commands=(), observation=flat)

    empty = _observation()
    empty_deltas = paper._plan_deltas(  # noqa: SLF001
        target_basket={"SEC-A": Decimal(0)}, observation=empty,
        minimum_quantity_increment=Decimal(1))
    assert paper._provably_clean_empty_noop(  # noqa: SLF001
        deltas=empty_deltas, commands=(), observation=empty)

    dust_deltas = paper._plan_deltas(  # noqa: SLF001
        target_basket={"SEC-A": Decimal("10.5")}, observation=flat,
        minimum_quantity_increment=Decimal(1))
    assert not paper._provably_clean_empty_noop(  # noqa: SLF001
        deltas=dust_deltas, commands=(), observation=flat)

    working_command = _command(
        "SEC-A", quantity=Decimal(1), state=CommandState.ACKNOWLEDGED)
    working_order = BrokerOrder(
        broker_order_id="working-1",
        client_key=working_command.client_key,
        instrument=instrument, side=Side.BUY,
        state=CommandState.ACKNOWLEDGED, quantity=Decimal(1),
        submitted_at=NOW)
    committed = _observation(
        positions=(BrokerPosition(instrument, Decimal(10)),),
        orders=(working_order,))
    committed_deltas = paper._plan_deltas(  # noqa: SLF001
        target_basket={"SEC-A": Decimal(11)}, observation=committed,
        minimum_quantity_increment=Decimal(1))
    assert not paper._provably_clean_empty_noop(  # noqa: SLF001
        deltas=committed_deltas, commands=(working_command,),
        observation=committed)


def test_cutoff_is_exact_official_xnys_open_even_on_a_half_day():
    half_day = date(2024, 11, 29)
    opened, closed = calendar.session_window(half_day)

    cutoff = paper._official_preopen_cutoff(  # noqa: SLF001
        _plan(effective_session=half_day))

    assert cutoff == opened
    assert cutoff.hour == 9 and cutoff.minute == 30
    assert closed.hour == 13


def test_recovery_overlays_open_split_before_book_classification_and_evidence(
        monkeypatch):
    effective = date(2026, 8, 20)
    decision = date(2026, 8, 19)
    plan = _plan(
        basket={"SEC-A": Decimal(10)}, effective_session=effective,
        decision_session=decision)
    command = _command(
        "SEC-A", quantity=Decimal(10), state=CommandState.FILLED,
        filled=Decimal(10),
        created_at=datetime(2026, 8, 19, 18, tzinfo=timezone.utc))
    instrument = BrokerInstrument("SEC-A", "AAA")
    observation = _observation(positions=(
        BrokerPosition(instrument, Decimal(20)),))
    cutoff = paper._official_preopen_cutoff(plan)  # noqa: SLF001
    authority = preopen_authority.PreOpenShareUnitAuthority(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        effective_session=effective,
        provider="test-provider", publication_id="split-at-open",
        as_of=cutoff, cutoff_at=cutoff, complete=True,
        coverage=(preopen_authority.ShareUnitCoverage.oriented(
            "SEC-A", (preopen_authority.ShareUnitEvent(
                event_id="split-2-for-1", revision_id="revision-1",
                effective_session=effective, multiplier=Decimal(2)),)),))
    commands = [command]
    seen = []

    async def reconcile_with_supplied_actions(**kwargs):
        seen.append(kwargs["actions"])
        expected = reconciliation.expected_book_from_commands(
            commands, actions=kwargs["actions"])
        observed = observation.positions_by_security()
        foreign = () if expected == observed else tuple(sorted(observed))
        return reconciliation.ReconciliationResult(
            runtime_state=RuntimeState.RUNNING,
            observation=observation, observation_id=17,
            expected=expected, observed=observed,
            corporate_actions={"SEC-A": kwargs["actions"]("SEC-A")},
            foreign_positions=foreign)

    grant, broker, recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=authority, commands=commands,
        reconcile=reconcile_with_supplied_actions)
    projection_calls = []

    def require_authority_projection(_conn, **kwargs):
        projection_calls.append(kwargs)
        return SimpleNamespace(
            target_basket={"SEC-A": Decimal(20)},
            through_session=effective)

    monkeypatch.setattr(
        paper, "_target_projection_or_refuse", require_authority_projection)

    result = asyncio.run(paper.recover_automated_paper_cycle(
        conn=object(), broker=broker, base_url="https://paper.example",
        grant=grant, automation_config_sha256="config"))

    assert isinstance(
        seen[0], preopen_authority.AuthorityActionOverlay)
    assert result.clean
    assert result.foreign_positions == ()
    assert result.expected == {"SEC-A": Decimal(20)}
    assert recorded[0]["target_projection"].target_basket == {
        "SEC-A": Decimal(20)}
    assert recorded[0]["observation_post_projection_actions"] == {}
    assert len(projection_calls) == 1
    assert projection_calls[0]["require_existing"] is True
    assert projection_calls[0]["target_actions"]("SEC-A") == Decimal(2)


def test_recovery_refuses_stale_projection_from_before_current_authority(
        monkeypatch):
    plan = _plan(basket={"SEC-A": Decimal(10)})
    empty = CorpusActionLookup(start=plan.decision_session, events={})
    fresh = object()
    stale = object()
    asserted = []

    monkeypatch.setattr(
        paper, "shadow_target",
        lambda _state: SimpleNamespace(
            shares={}, tickers={}, pending_open_shares={}, held_shares={},
            pending_close_shares={}))
    monkeypatch.setattr(journal, "load_commands", lambda *_: ())
    monkeypatch.setattr(
        reconciliation, "expected_book_from_commands", lambda *_args, **_kw: {})
    monkeypatch.setattr(
        paper.target_reprojection, "project_target", lambda *_args, **_kw: fresh)
    monkeypatch.setattr(
        paper.target_reprojection, "load_projection", lambda *_args, **_kw: stale)
    monkeypatch.setattr(
        paper.target_reprojection, "assert_projection",
        lambda *_args, **_kw: asserted.append(True))
    broker = SimpleNamespace(capabilities=SimpleNamespace(
        minimum_quantity_increment=Decimal(1)))
    binding = SimpleNamespace(identity=DEPLOYMENT)

    with pytest.raises(
            paper.PaperActivationRefused,
            match="authority-derived target projection.*differs"):
        paper._target_projection_or_refuse(  # noqa: SLF001
            object(), state=SimpleNamespace(state_hash=plan.shadow_snapshot_hash),
            plan=plan, binding=binding,
            broker=broker, through=plan.effective_session,
            actions=empty, target_actions=empty, require_existing=True)

    assert asserted == []


def test_target_projection_preview_does_not_persist(monkeypatch):
    plan = _plan(basket={"SEC-A": Decimal(10)})
    empty = CorpusActionLookup(start=plan.decision_session, events={})
    projected = object()
    recorded = []

    monkeypatch.setattr(
        paper, "shadow_target",
        lambda _state: SimpleNamespace(
            shares={}, tickers={}, pending_open_shares={}, held_shares={},
            pending_close_shares={}))
    monkeypatch.setattr(journal, "load_commands", lambda *_: ())
    monkeypatch.setattr(
        reconciliation, "expected_book_from_commands", lambda *_args, **_kw: {})
    monkeypatch.setattr(
        paper.target_reprojection, "project_target",
        lambda *_args, **_kw: projected)
    monkeypatch.setattr(
        paper.target_reprojection, "record_projection",
        lambda *_args, **_kw: recorded.append(True))
    broker = SimpleNamespace(capabilities=SimpleNamespace(
        minimum_quantity_increment=Decimal(1)))

    result = paper._target_projection_or_refuse(  # noqa: SLF001
        object(), state=SimpleNamespace(state_hash=plan.shadow_snapshot_hash),
        plan=plan,
        binding=SimpleNamespace(identity=DEPLOYMENT), broker=broker,
        through=plan.effective_session, actions=empty,
        target_actions=empty, persist_projection=False)

    assert result is projected
    assert recorded == []


def test_target_projection_preview_mismatch_refuses_before_persist(monkeypatch):
    plan = _plan(basket={"SEC-A": Decimal(10)})
    empty = CorpusActionLookup(start=plan.decision_session, events={})
    recorded = []

    monkeypatch.setattr(
        paper, "shadow_target",
        lambda _state: SimpleNamespace(
            shares={}, tickers={}, pending_open_shares={}, held_shares={},
            pending_close_shares={}))
    monkeypatch.setattr(journal, "load_commands", lambda *_: ())
    monkeypatch.setattr(
        reconciliation, "expected_book_from_commands", lambda *_args, **_kw: {})
    monkeypatch.setattr(
        paper.target_reprojection, "project_target",
        lambda *_args, **_kw: object())
    monkeypatch.setattr(
        paper.target_reprojection, "record_projection",
        lambda *_args, **_kw: recorded.append(True))
    broker = SimpleNamespace(capabilities=SimpleNamespace(
        minimum_quantity_increment=Decimal(1)))

    with pytest.raises(
            paper.PaperActivationRefused,
            match="post-reconciliation.*differs"):
        paper._target_projection_or_refuse(  # noqa: SLF001
            object(), state=SimpleNamespace(state_hash=plan.shadow_snapshot_hash),
            plan=plan,
            binding=SimpleNamespace(identity=DEPLOYMENT), broker=broker,
            through=plan.effective_session, actions=empty,
            target_actions=empty, expected_projection=object())

    assert recorded == []


def test_recovery_revalidates_coverage_after_adopting_command(monkeypatch):
    effective = date(2026, 8, 20)
    plan = _plan(
        basket={"SEC-A": Decimal(10)}, effective_session=effective,
        decision_session=date(2026, 8, 19))
    cutoff = paper._official_preopen_cutoff(plan)  # noqa: SLF001
    authority = preopen_authority.PreOpenShareUnitAuthority(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        effective_session=effective,
        provider="test-provider", publication_id="only-original-domain",
        as_of=cutoff, cutoff_at=cutoff, complete=True,
        coverage=(
            preopen_authority.ShareUnitCoverage.no_event("SEC-A"),))
    commands = []
    recovered = _command(
        "SEC-RECOVERED", quantity=Decimal(1),
        state=CommandState.CANCELLED,
        recovered_key="sntl-recovered-during-reconcile")

    async def reconcile_then_adopt(**_kwargs):
        commands.append(recovered)
        return reconciliation.ReconciliationResult(
            runtime_state=RuntimeState.RUNNING,
            observation=_observation(), observation_id=None)

    grant, broker, _recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=authority, commands=commands,
        reconcile=reconcile_then_adopt)

    with pytest.raises(
            paper.PreOpenShareUnitAuthorityUnavailable,
            match=r"missing=\['SEC-RECOVERED'\]"):
        asyncio.run(paper.recover_automated_paper_cycle(
            conn=object(), broker=broker, base_url="https://paper.example",
            grant=grant, automation_config_sha256="config"))


def test_recovery_missing_authority_refuses_nonempty_domain_before_observation(
        monkeypatch):
    plan = _plan(basket={"SEC-A": Decimal(10)})

    async def must_not_reconcile(**_kwargs):
        pytest.fail("nonempty recovery reached broker reconciliation without authority")

    grant, broker, _recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=None, commands=[],
        reconcile=must_not_reconcile)

    with pytest.raises(
            paper.PreOpenShareUnitAuthorityUnavailable,
            match="absent for the nonempty recovery book"):
        asyncio.run(paper.recover_automated_paper_cycle(
            conn=object(), broker=broker, base_url="https://paper.example",
            grant=grant, automation_config_sha256="config"))


def test_recovery_all_zero_domain_is_the_only_authority_bypass(monkeypatch):
    plan = _plan(basket={"SEC-A": Decimal(0)})
    calls = []

    async def reconcile_empty(**kwargs):
        calls.append(kwargs)
        return reconciliation.ReconciliationResult(
            runtime_state=RuntimeState.RUNNING,
            observation=_observation(), observation_id=None)

    grant, broker, _recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=None, commands=[],
        reconcile=reconcile_empty)

    result = asyncio.run(paper.recover_automated_paper_cycle(
        conn=object(), broker=broker, base_url="https://paper.example",
        grant=grant, automation_config_sha256="config"))

    assert result.clean
    assert len(calls) == 1


def test_dual_recovery_earns_due_mirror_check_before_transport_gate(
        monkeypatch):
    """A partial cycle crossing close cannot deadlock on a missing check."""
    plan = _plan(basket={"SEC-A": Decimal(10)})
    events = []

    async def clean_reconcile(**_kwargs):
        events.append("reconcile")
        return reconciliation.ReconciliationResult(
            runtime_state=RuntimeState.RUNNING,
            observation=_observation(), observation_id=None)

    grant, broker, _recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=None, commands=[],
        reconcile=clean_reconcile)
    shadow_result = SimpleNamespace(
        state=SimpleNamespace(to_dict=lambda: {}))
    monkeypatch.setattr(
        dual_reconciliation, "verified_shadow_intent",
        lambda *_args, **_kwargs: shadow_result)
    monkeypatch.setattr(
        dual_plan_authority, "rederive_plan",
        lambda *_args, **_kwargs: {"authority_sha256": "a" * 64})
    monkeypatch.setattr(
        publication, "pinned",
        lambda *_args, **_kwargs: nullcontext(SimpleNamespace(version=1)))
    monkeypatch.setattr(
        paper.feed_store, "latest_visible_session",
        lambda *_args, **_kwargs: plan.effective_session)
    monkeypatch.setattr(
        shadow_runtime, "publication_not_before",
        lambda *_args, **_kwargs: NOW.replace(year=2020))

    def revalidate(*_args, **_kwargs):
        events.append("revalidate")
        return {"status": informational_paper_mirror.NO_UNIT_CHANGE}

    def require(*_args, **_kwargs):
        events.append("require")
        assert "revalidate" in events
        return {"status": informational_paper_mirror.NO_UNIT_CHANGE}

    monkeypatch.setattr(
        informational_paper_mirror, "revalidate_all", revalidate)
    monkeypatch.setattr(
        informational_paper_mirror, "require_transport_permitted", require)

    result = asyncio.run(paper.recover_automated_paper_cycle(
        conn=object(), broker=broker, base_url="https://paper.example",
        grant=grant, automation_config_sha256="config",
        dual_shadow_observation_id="obs-year-end",
        dual_shadow_starting_cash=Decimal("100000")))

    assert result.clean
    assert events[:3] == ["revalidate", "require", "reconcile"]


def test_old_generation_recovery_never_loads_stale_plan_economics(monkeypatch):
    plan = _plan()

    async def clean_reconcile(**_kwargs):
        return reconciliation.ReconciliationResult(
            runtime_state=RuntimeState.RUNNING,
            observation=_observation(), observation_id=None)

    def stale_plan(*_args, **_kwargs):
        pytest.fail("old-generation recovery loaded stale plan economics")

    grant, broker, _recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=None, commands=[],
        reconcile=clean_reconcile, cycle_generation=2,
        grant_generation=3, load_plan=stale_plan)

    result = asyncio.run(paper.recover_automated_paper_cycle(
        conn=object(), broker=broker, base_url="https://paper.example",
        grant=grant, automation_config_sha256="config"))

    assert result.clean
