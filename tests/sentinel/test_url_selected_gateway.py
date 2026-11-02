"""Neutral operational dispatch never turns URL selection into financial authority."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from live_authority_fixtures import live_fixture
from sentinel import trading
from sentinel.authority import AuthorityRefused, RolloutMode
from sentinel.cli import _shared, main as cli, trading as cli_trading
from sentinel.cli.authorized_routes import ROUTES
from sentinel.config import SentinelConfig
from sentinel.execution import authority_gate
from sentinel.execution.guarded import BrokerOperation, LiveExecutionGrant

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"


@contextmanager
def _scope(value=None, **_kwargs):
    yield value


def test_paper_gateway_delegates_without_loading_live_authority(monkeypatch):
    calls = []
    result = object()
    async def prepare(**kwargs):
        calls.append(kwargs)
        return result
    monkeypatch.setattr(trading.paper, "prepare_paper_plan", prepare)
    monkeypatch.setattr(trading, "_admission", lambda *_a, **_k: pytest.fail("LIVE loader entered PAPER"))
    broker, conn = object(), object()
    actual = asyncio.run(trading.prepare_trading_plan(conn=conn, broker=broker,
        base_url=PAPER, through="2026-10-30", expected_account="paper-id", warmup_sessions=252))
    assert actual is result
    assert calls[0]["broker"] is broker
    assert calls[0]["conn"] is conn
    assert calls[0]["warmup_sessions"] == 252


def test_explicit_paper_current_plan_api_refuses_live_before_database(monkeypatch):
    from sentinel.config import LiveEndpointRefused
    from sentinel.paper import preparation
    monkeypatch.setattr(preparation, '_state_and_plan_or_refuse',
        lambda _c: pytest.fail('PAPER current-plan owner entered LIVE'))
    with pytest.raises(LiveEndpointRefused, match='PAPER-only'):
        preparation.current_paper_plan(object(), base_url=LIVE)


def test_wrong_live_namespace_refuses_before_any_broker_access(monkeypatch):
    monkeypatch.setattr(trading, "_schema", lambda _c: None)
    monkeypatch.setattr(trading.journal, "writer_lock", lambda *_a, **_k: _scope())
    monkeypatch.setattr(trading.feed_inputs, "pinned", lambda *_a, **_k: _scope(SimpleNamespace(version=1)))
    monkeypatch.setattr(trading.binding, "require", lambda _c: SimpleNamespace(
        is_owned=True, broker="alpaca", broker_account_id="paper-id"))
    with pytest.raises(trading.TradingGatewayRefused, match="prebound alpaca-live"):
        asyncio.run(trading.prepare_trading_plan(conn=object(), broker=object(), base_url=LIVE,
            through="2026-10-30", expected_account="paper-id",
            dual_shadow_observation_id="test", dual_shadow_starting_cash="100"))


@pytest.mark.parametrize("verification,verdict", [("CANDIDATE", "SHADOW_GO"), ("VERIFIED", "NOT_DEPLOYABLE")])
def test_live_shadow_requires_actual_verified_go(monkeypatch, verification, verdict):
    from sentinel import shadow_runtime, shadow_segments
    monkeypatch.setattr(shadow_segments, "active_segment", lambda *_a: SimpleNamespace(index=0))
    monkeypatch.setattr(shadow_runtime, "verified_shadow_status", lambda *_a, **_k: SimpleNamespace(
        verification=verification, shadow_verdict=verdict, runtime_authority_sha256="a" * 64,
        session="2026-10-30"))
    with pytest.raises(trading.TradingGatewayRefused, match="verified shadow"):
        trading._shadow(object(), observation_id="test", starting_cash="100", session="2026-10-30")


def test_live_cannot_inherit_paper_post_gap_origin(monkeypatch):
    from sentinel import shadow_runtime, shadow_segments
    monkeypatch.setattr(shadow_segments, "active_segment", lambda *_a: SimpleNamespace(index=1))
    monkeypatch.setattr(shadow_runtime, "verified_shadow_status", lambda *_a, **_k: pytest.fail("origin guard removed"))
    with pytest.raises(trading.TradingGatewayRefused, match="PAPER post-gap"):
        trading._shadow(object(), observation_id="test", starting_cash="100")


def test_live_fresh_authority_dispatch_never_uses_paper_certificate(monkeypatch):
    from sentinel.authority import live_runtime
    calls = []
    result = object()
    monkeypatch.setattr(authority_gate.feed_inputs, "require_current", lambda _c: SimpleNamespace(version=17))
    monkeypatch.setattr(authority_gate.feed_inputs, "coherent", lambda _c: None)
    monkeypatch.setattr(authority_gate, "load_active_signed_certificate", lambda *_a, **_k: pytest.fail("PAPER cert loaded"))
    monkeypatch.setattr(live_runtime, "require_current_live_authority",
        lambda conn, **kwargs: calls.append((conn, kwargs)) or result)
    conn = object()
    assert authority_gate.require_current_authority(conn, runtime_identity={"runtime": 1},
        strategy_identity={"strategy": 2}, required_mode=RolloutMode.PINNED_1_00,
        required_operation="SUBMIT", paper_base_url=LIVE, current_publication_version=17) is result
    assert calls[0][0] is conn
    assert calls[0][1]["base_url"] == LIVE
    with pytest.raises(AuthorityRefused, match="publication changed"):
        authority_gate.require_current_authority(conn, runtime_identity={}, strategy_identity={},
            required_mode=RolloutMode.PINNED_1_00, required_operation="READ",
            paper_base_url=LIVE, current_publication_version=16)


def test_live_mutation_rejects_disabled_backup_before_grant_or_broker(monkeypatch):
    fixture = live_fixture()
    class Connection:
        def close(self): pass
    monkeypatch.setattr(authority_gate.backup_runtime_authority, "require", lambda *_a, **_k: {"enabled": False})
    guard = authority_gate.build_fresh_execution_guard(
        connection_factory=Connection, paper_base_url=LIVE,
        runtime_identity=lambda: {}, strategy_identity=lambda: {},
        validate_grant=lambda *_a: pytest.fail("disabled LIVE backup accepted"))
    grant = LiveExecutionGrant(subject=fixture.subject, operation_scope="EXECUTE",
        plan_id="plan", effective_session=date(2026, 11, 2), confirm_submit_live_orders=True)
    with pytest.raises(AuthorityRefused, match="enabled qualified backups"):
        asyncio.run(guard.before_mutation(grant, BrokerOperation.SUBMIT))


@pytest.mark.parametrize("scope", ["PREPARE", "RECOVER"])
@pytest.mark.parametrize("operation", [BrokerOperation.SUBMIT, BrokerOperation.CANCEL])
def test_live_read_only_scope_cannot_mutate(scope, operation):
    grant = LiveExecutionGrant(subject=live_fixture().subject, operation_scope=scope)
    with pytest.raises(AuthorityRefused, match="read-only"):
        authority_gate._authority_operation(grant, operation)


NEW_COMMANDS = {"prepare-trading-plan", "current-trading-plan", "execute-trading-plan",
    "recover-trading-account", "bind-empty-live-account", "activate-live-automation",
    "release-live-automation-kill-switch", "enroll-live-issuer-policy"}


def test_new_commands_have_exact_authorized_parser_routes():
    parser = cli.build_parser()
    commands = next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict))
    for command in NEW_COMMANDS:
        assert command in commands
        assert command in _shared.AUTHORIZED_RUNTIME_COMMANDS
        assert command in ROUTES
        assert command not in cli.ROUTES


@pytest.mark.parametrize("command", sorted(NEW_COMMANDS))
def test_direct_neutral_handler_checks_executable_capability(monkeypatch, command):
    monkeypatch.delenv(_shared.AUTHORIZED_RUNTIME_ENV, raising=False)
    monkeypatch.setattr(_shared, "_authorized_marker_bytes", lambda: None)
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": LIVE})
    assert asyncio.run(ROUTES[command](config, SimpleNamespace())) == _shared.EXIT_CONFIG


def test_explicit_paper_cli_refuses_live_before_current_plan_owner(monkeypatch):
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": LIVE})
    monkeypatch.setattr(cli, "require_authorized_runtime", lambda _c: None)
    monkeypatch.setattr(cli.SentinelConfig, "from_env", lambda: config)
    monkeypatch.setitem(cli.ROUTES, "current-paper-plan", lambda *_a: pytest.fail("PAPER owner entered LIVE"))
    assert cli.main(["current-paper-plan"]) == _shared.EXIT_CONFIG


def test_cli_url_selects_live_without_environment_flag(monkeypatch):
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": LIVE})
    monkeypatch.setattr(cli_trading, "_connect", lambda _c: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cli_trading, "_shadow_kwargs", lambda _c: {})
    seen = []
    monkeypatch.setattr(trading, "current_trading_plan", lambda conn, **kwargs:
        seen.append(kwargs) or {"database_authorities_match": True})
    assert asyncio.run(cli_trading._operate(config, SimpleNamespace(), "current")) == _shared.EXIT_OK
    assert seen == [{"base_url": LIVE}]


def test_live_consumer_reads_verified_shadow_independently_of_worker_enable_flag(monkeypatch):
    from decimal import Decimal
    from sentinel import automation_runtime
    from sentinel.automation.model import AutomationConfig
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ENABLED', '0')
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', 'canonical')
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', '50000')
    monkeypatch.delenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', raising=False)
    config = SentinelConfig.from_env({'ALPACA_BASE_URL': LIVE,
        'SENTINEL_DATABASE_URL': 'postgresql://offline/unused'})
    assert trading._shadow_config(None, None) == ('canonical', Decimal('50000'))
    assert cli_trading._shadow_kwargs(config) == {'dual_shadow_observation_id': 'canonical',
        'dual_shadow_starting_cash': Decimal('50000')}
    runtime = automation_runtime.ProductionAutomation(sentinel_config=config, automation_config=AutomationConfig())
    assert runtime._live_run_enabled is True
    assert runtime._shadow_observation_enabled is False
    assert runtime._shadow_observation_id == 'canonical'


def test_live_repeated_prepare_reuses_immutable_plan_without_resizing(monkeypatch):
    fixture = live_fixture()
    plan = SimpleNamespace(decision_session=date(2026, 10, 30))
    bound = SimpleNamespace(is_owned=True, broker="alpaca-live",
        broker_account_id=fixture.subject.account_id, identity=object())
    shadow = SimpleNamespace(session="2026-10-30",
        state=SimpleNamespace(state_hash="f" * 64, data_version=8))
    monkeypatch.setattr(trading, "_schema", lambda _c: None)
    monkeypatch.setattr(trading.journal, "writer_lock", lambda *_a, **_k: _scope())
    monkeypatch.setattr(trading.feed_inputs, "pinned", lambda *_a, **_k: _scope(SimpleNamespace(version=8)))
    monkeypatch.setattr(trading.feed_inputs, "frontier", lambda _c: "2026-10-30")
    monkeypatch.setattr(trading, "_bound", lambda *_a, **_k: bound)
    monkeypatch.setattr(trading, "_shadow", lambda *_a, **_k: shadow)
    monkeypatch.setattr(trading, "_readiness_or_refuse", lambda *_a, **_k: None)
    monkeypatch.setattr(trading, "load_rollout_state", lambda _c: object())
    monkeypatch.setattr(trading, "_manual_grant", lambda *_a, **_k: object())
    class Broker:
        async def account_snapshot(self):
            return object()  # A new NAV observation must not resize a retained plan.
    monkeypatch.setattr(trading, "_guard", lambda *_a, **_k: Broker())
    monkeypatch.setattr(trading, "_account_or_refuse", lambda *_a: None)
    monkeypatch.setattr(trading, "_action_lookup", lambda *_a: object())
    reconciliation = object()
    async def reconcile(**_kwargs): return reconciliation
    monkeypatch.setattr(trading.reconcile, "reconcile", reconcile)
    monkeypatch.setattr(trading, "_transport_observation_or_refuse", lambda _r: object())
    monkeypatch.setattr(trading.journal, "latest_plan", lambda _c: plan)
    proofs = []
    monkeypatch.setattr(trading.dual_plan_authority, "rederive_plan", lambda *a, **kw: proofs.append(kw))
    monkeypatch.setattr(trading, "build_execution_plan", lambda **_k: pytest.fail("retained economics resized"))
    result = asyncio.run(trading.prepare_trading_plan(conn=object(), broker=object(), base_url=LIVE,
        through="2026-10-30", expected_account=fixture.subject.account_id,
        dual_shadow_observation_id="test", dual_shadow_starting_cash="100"))
    assert result.plan is plan
    assert result.reconciliation is reconciliation
    assert len(proofs) == 1
    assert proofs[0]["expected_shadow_result"] is shadow


def test_live_global_kill_fences_manual_mutation_before_transport(monkeypatch):
    from sentinel.automation import store
    fixture = live_fixture()
    subject = fixture.subject
    bound = SimpleNamespace(is_owned=True, broker="alpaca-live", deployment_id=subject.deployment_id,
        broker_account_id=subject.account_id, takeover_epoch=subject.takeover_epoch)
    monkeypatch.setattr(trading, "_bound", lambda _c: bound)
    monkeypatch.setattr(trading.feed_inputs, "require_current", lambda _c: object())
    monkeypatch.setattr(trading.feed_inputs, "coherent", lambda _c: None)
    monkeypatch.setattr(trading, "load_rollout_state", lambda _c: object())
    monkeypatch.setattr(store, "load_control", lambda _c: SimpleNamespace(kill_switch_engaged=True))
    monkeypatch.setattr(trading, "_shadow", lambda *_a, **_k: pytest.fail("kill guard removed"))
    grant = LiveExecutionGrant(subject=subject, operation_scope="EXECUTE", plan_id="plan",
        effective_session=date(2026, 11, 2), confirm_submit_live_orders=True)
    with pytest.raises(trading.TradingGatewayRefused, match="kill switch"):
        trading._validate_grant(object(), grant, BrokerOperation.SUBMIT, None,
            base_url=LIVE, observation_id="test", starting_cash="100", now=fixture.now)


def test_live_preparation_uses_canonical_builder_and_real_immutable_sizing_proof(monkeypatch):
    from tests.sentinel.test_production_decision import (
        DECISION_SESSION, _account, _binding, _observation, _publication, _state,
    )
    from sentinel.authority import RolloutState
    from sentinel.core import catchup
    from sentinel.execution.contract import BrokerAccountIdentity
    fixture = live_fixture()
    bound = replace(_binding(fixture.subject.account_id), broker="alpaca-live")
    account = replace(_account(fixture.subject.account_id), status="ACTIVE", identity=BrokerAccountIdentity(
        broker="alpaca-live", account_id=fixture.subject.account_id))
    observation = replace(_observation(), account_identity=account.identity)
    shadow = SimpleNamespace(session=str(DECISION_SESSION), state=_state(),
        record_sha256="e" * 64, runtime_authority_sha256="f" * 64)
    pinned = _publication()
    rollout = RolloutState(mode=RolloutMode.CONTROLLER, version=1, certificate_sha256="c" * 64)
    committed = {"plan": None, "proof": None, "commits": 0}
    conn = SimpleNamespace(commit=lambda: committed.update(commits=committed["commits"] + 1))
    monkeypatch.setattr(trading, "_schema", lambda _c: None)
    monkeypatch.setattr(trading.journal, "writer_lock", lambda *_a, **_k: _scope())
    monkeypatch.setattr(trading.feed_inputs, "pinned", lambda *_a, **_k: _scope(pinned))
    monkeypatch.setattr(trading.feed_inputs, "frontier", lambda _c: str(DECISION_SESSION))
    monkeypatch.setattr(trading, "_bound", lambda *_a, **_k: bound)
    monkeypatch.setattr(trading, "_shadow", lambda *_a, **_k: shadow)
    monkeypatch.setattr(trading, "_readiness_or_refuse", lambda *_a, **_k: None)
    monkeypatch.setattr(trading, "load_rollout_state", lambda _c: rollout)
    monkeypatch.setattr(trading, "_manual_grant", lambda *_a, **_k: object())
    class Broker:
        async def account_snapshot(self): return account
    monkeypatch.setattr(trading, "_guard", lambda *_a, **_k: Broker())
    monkeypatch.setattr(trading, "_action_lookup", lambda *_a: object())
    async def reconcile(**_kwargs): return SimpleNamespace(observation=observation)
    monkeypatch.setattr(trading.reconcile, "reconcile", reconcile)
    monkeypatch.setattr(trading, "_transport_observation_or_refuse", lambda r: r.observation)
    monkeypatch.setattr(trading, "_load_marks_and_tickers", lambda *_a:
        ({"SENTINEL:BIL": "90"}, {"SENTINEL:BIL": "BIL"}))
    async def instruments(*_a, **_k): return {}
    monkeypatch.setattr(trading, "_instrument_map", instruments)
    monkeypatch.setattr(trading.journal, "latest_plan", lambda _c: committed["plan"])
    def adopt(_conn, plan, **_kwargs):
        committed["plan"] = plan
        return plan
    def record(_conn, proof, **_kwargs):
        committed["proof"] = proof
        return proof
    monkeypatch.setattr(trading.journal, "adopt_current_plan", adopt)
    monkeypatch.setattr(trading.dual_plan_authority, "record_authority", record)
    monkeypatch.setattr(trading.dual_plan_authority, "load_authority", lambda *_a, **_k: committed["proof"])
    monkeypatch.setattr(catchup, "resume_state", lambda *_a: pytest.fail("parallel catchup book entered LIVE"))
    result = asyncio.run(trading.prepare_trading_plan(conn=conn, broker=object(), base_url=LIVE,
        through=DECISION_SESSION, expected_account=fixture.subject.account_id,
        dual_shadow_observation_id="test", dual_shadow_starting_cash="2000"))
    assert result.plan.broker == "alpaca-live"
    assert result.plan.plan_id == "sentinel-" + result.plan.fingerprint()
    assert result.plan.shadow_snapshot_hash == shadow.state.state_hash
    assert committed["proof"]["account_snapshot"]["identity"]["broker"] == "alpaca-live"
    assert committed["commits"] == 1
    proof = trading.dual_plan_authority.rederive_plan(conn, plan=result.plan,
        binding=bound, rollout_state=rollout, expected_shadow_result=shadow)
    assert proof["verdict"] == "MATCH"


def test_production_live_policy_rechecks_actual_fresh_control_at_transport(monkeypatch):
    from sentinel.config import build_execution_broker
    from sentinel.execution import guarded
    fixture = live_fixture()
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": LIVE,
        "ALPACA_API_KEY": "offline-key", "ALPACA_SECRET_KEY": "offline-secret"})
    raw = build_execution_broker(config, resolve_security_id=lambda value: value,
        live_admission=fixture.admission)
    bound = SimpleNamespace(broker='alpaca-live', broker_account_id=fixture.subject.account_id)
    monkeypatch.setattr(trading, '_bound', lambda *_a, **_k: bound)
    state = {'kill': False, 'connections': 0, 'closed': 0, 'checks': 0}
    class Connection:
        def __init__(self): state['connections'] += 1
        def close(self): state['closed'] += 1
        def commit(self): pass
    monkeypatch.setattr(trading, '_fresh_connection_factory', lambda _c: Connection)
    monkeypatch.setattr(authority_gate.backup_runtime_authority, 'require', lambda *_a, **_k: {'enabled': True})
    monkeypatch.setattr(authority_gate.feed_inputs, 'require_current', lambda _c: SimpleNamespace(version=1))
    monkeypatch.setattr(authority_gate, 'load_rollout_state', lambda _c: SimpleNamespace(mode=RolloutMode.PINNED_1_00))
    monkeypatch.setattr(authority_gate, 'require_current_authority', lambda *_a, **_k: SimpleNamespace(certificate_sha256='a' * 64))
    monkeypatch.setattr(authority_gate.operational_evidence, 'record_backup_proof', lambda *_a, **_k: None)
    def validate(*_a, **_kw):
        state['checks'] += 1
        if state['kill']:
            raise AuthorityRefused('fresh emergency kill engaged')
    monkeypatch.setattr(trading, '_validate_grant', validate)
    monkeypatch.setattr(trading.identity, 'rehearsal_identity', lambda: {})
    monkeypatch.setattr(trading, '_strategy', lambda: {})
    grant = LiveExecutionGrant(subject=fixture.subject, operation_scope='EXECUTE',
        plan_id='plan', effective_session=date(2026, 11, 2), confirm_submit_live_orders=True)
    wrapped = trading._guard(object(), raw, base_url=LIVE, grant=grant,
        observation_id='test', starting_cash='100')
    assert type(wrapped) is guarded.GuardedExecutionBroker
    wrapped._live_policy._final_authority('SUBMIT')
    state['kill'] = True
    with pytest.raises(AuthorityRefused, match='fresh emergency kill'):
        wrapped._live_policy._final_authority('SUBMIT')
    assert state['checks'] == state['connections'] == state['closed'] == 2


def test_live_execution_reaches_same_executor_with_strict_reconciliation_and_issuer_gate(monkeypatch):
    from decimal import Decimal
    from sentinel.execution import issuer_runtime
    from sentinel.execution.states import RuntimeState
    fixture = live_fixture()
    plan = SimpleNamespace(plan_id='immutable', decision_session=date(2026, 10, 30),
        effective_session=date(2026, 11, 2))
    bound = SimpleNamespace(identity=object())
    state = object()
    actions, projected_actions = object(), object()
    target_actions = object()
    projection, observation, publication = object(), object(), object()
    preflight = SimpleNamespace(restricted_securities={})
    captured = {}
    monkeypatch.setattr(trading, '_schema', lambda _c: None)
    monkeypatch.setattr(trading.ProtectedLimitPolicy, 'from_env', lambda: object())
    monkeypatch.setattr(trading.journal, 'writer_lock', lambda *_a, **_k: _scope())
    monkeypatch.setattr(trading.feed_inputs, 'pinned', lambda *_a, **_k: _scope(publication))
    monkeypatch.setattr(trading, '_bound', lambda *_a: bound)
    monkeypatch.setattr(trading.journal, 'latest_plan', lambda _c: plan)
    monkeypatch.setattr(trading.journal, 'load_commands', lambda *_a: ())
    monkeypatch.setattr(trading, '_shadow', lambda *_a, **_k: SimpleNamespace(state=state))
    monkeypatch.setattr(trading, '_action_lookup', lambda *_a: actions)
    monkeypatch.setattr(trading, '_target_action_lookup', lambda *_a: target_actions)
    monkeypatch.setattr(trading, '_preopen_active_security_ids', lambda **_k: ())
    monkeypatch.setattr(trading, '_official_preopen_cutoff', lambda _p: fixture.now)
    monkeypatch.setattr(trading, '_preopen_views_or_none', lambda *_a, **_k: (None, projected_actions, target_actions))
    monkeypatch.setattr(trading, '_target_projection_or_refuse', lambda *_a, **_k: projection)
    projection = SimpleNamespace(target_basket={})
    async def reconcile(**kwargs):
        assert kwargs['actions'] is projected_actions
        assert kwargs.get('informational_current_book', False) is False
        return preflight
    monkeypatch.setattr(trading.reconcile, 'reconcile', reconcile)
    monkeypatch.setattr(trading, '_transport_observation_or_refuse', lambda r: observation)
    async def instruments(*_a, **_k): return {}
    monkeypatch.setattr(trading, '_instrument_map', instruments)
    class Broker:
        capabilities = SimpleNamespace(minimum_quantity_increment=Decimal(1))
        async def account_snapshot(self): return object()
    broker = Broker()
    def guard(*_a, **kwargs):
        captured['guard'] = kwargs
        return broker
    monkeypatch.setattr(trading, '_guard', guard)
    monkeypatch.setattr(trading, '_account_or_refuse', lambda *_a: None)
    class Issuer:
        def __init__(self, **_k): pass
        def final_check(self, **_k): pass
        def check_buy(self, **_k): pass
        def prepare_for_transport(self, **kwargs): captured['issuer'] = kwargs
    monkeypatch.setattr(issuer_runtime, 'PaperIssuerAdmission', Issuer)
    session = SimpleNamespace(runtime_state=RuntimeState.RUNNING, submitted=(), refused=(), deferred=())
    async def execute(**kwargs):
        captured['executor'] = kwargs
        await kwargs['mutation_authority'](preflight)
        return session
    monkeypatch.setattr(trading.executor, 'execute_session', execute)
    grant = LiveExecutionGrant(subject=fixture.subject, operation_scope='EXECUTE',
        plan_id=plan.plan_id, effective_session=plan.effective_session, confirm_submit_live_orders=True)
    result = asyncio.run(trading.execute_trading_plan(conn=object(), broker=object(), base_url=LIVE,
        confirm_account=fixture.subject.account_id, confirm_plan_id=plan.plan_id,
        confirm_effective_session=plan.effective_session, confirm_submit=True, grant=grant,
        dual_shadow_observation_id='test', dual_shadow_starting_cash='100'))
    assert result.plan is plan and result.session is session
    assert captured['executor']['broker'] is broker
    assert captured['executor']['target_projection'] is projection
    assert captured['executor']['actions'] is projected_actions
    assert captured['executor']['buy_admission'].__self__ is captured['guard']['issuer_admission_check'].__self__
    assert captured['guard']['actions']() is projected_actions
    assert captured['issuer']['publication'] is publication
    assert captured['issuer']['reconciliation'] is preflight
    assert captured['executor'].get('informational_current_book', False) is False
