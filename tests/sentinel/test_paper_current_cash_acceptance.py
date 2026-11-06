"""Selected PAPER cash observations earn no fill/close/LIVE authority."""
import ast
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import inspect
import textwrap

import pytest

from sentinel.execution import alpaca, broker_cash, certification
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import Completeness, resolved_capability_graph
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, PaperPreparationGrant)
from tests.sentinel.test_alpaca_boundary_overlay import (
    ACCOUNT_NUMBER, Httpx, Response, account_payload, activity_event, sse)
from tests.sentinel.test_journal_and_reconcile import pg
from tests.support.postgres import drop_public_tables
from sentinel import binding, schema
from sentinel.feed import store

UTC = timezone.utc
NOW = datetime(2026, 8, 20, tzinfo=UTC)
PATH = '/v2beta1/events/activities'


@pytest.fixture
def conn(pg):
    value = store.connect(pg.sync_dsn)
    drop_public_tables(value)
    schema.ensure_schema(value)
    binding.bind(value, deployment_id='cash-acceptance', broker='alpaca', broker_account_id=ACCOUNT_NUMBER)
    value.execute("UPDATE sentinel_account_binding SET established_at='2026-02-12T00:00:00Z' WHERE id=1")
    value.commit()
    yield value
    value.close()


async def no_op(*_): pass


def selected(*, events=None, routes=None, created_at='2026-02-12T00:00:00Z'):
    account = dict(account_payload(), created_at=created_at)
    event = activity_event(activity_type='DIV', activity_subtype='CDIV', net_amount='75.89')
    event.pop('account_id')
    http = Httpx(routes={'/v2/account': account,
        PATH: Response(text=sse(event) if events is None else events), **(routes or {})})
    inner = AssetIdAlpacaExecutionBroker(api_key='fixture', secret_key='fixture',
        base_url='https://paper-api.alpaca.markets', http_provider=lambda: http)
    certification.certify_adapter(inner, name='alpaca', mode='ALPACA_PAPER')
    wrapped = GuardedExecutionBroker(inner=inner,
        grant=PaperPreparationGrant(ACCOUNT_NUMBER, NOW.date()),
        guard=ExecutionBrokerGuard(no_op, no_op, no_op))
    return wrapped, http


def test_selected_cash_graph_and_guard_without_fill_or_finality_claims():
    broker, http = selected()
    graph = resolved_capability_graph(broker)
    assert graph['cash_observable'] and broker.supports_account_cash_activities
    assert broker.financial_activity_sse
    assert not broker.supports_account_fill_interval_evidence
    assert not broker.supports_account_close_valuation
    assert not broker.capabilities.recent_fill_history
    batch = asyncio.run(broker.account_cash_activities(after=NOW, through=NOW))
    assert batch.completeness is Completeness.COMPLETE
    assert batch.activities[0].net_amount == Decimal('75.89')
    assert len([path for _, path, _ in http.calls if path == PATH]) == 2
    assert certification.require_certified_adapter(broker).conformance_suite.split('+wrapper:', 1)[0] == 'sentinel.alpaca-paper-conformance/2'
    assert 'cash_observable' not in certification._CERTIFIED_CAPABILITIES['alpaca-live']


@pytest.mark.parametrize('created_at', [None, '', '2026-02-11T23:59:59Z', '2026-08-21T00:00:00Z'])
def test_unknown_or_outside_history_account_creation_refuses_before_stream(created_at):
    broker, http = selected(created_at=created_at)
    with pytest.raises(alpaca.MalformedBrokerPayload, match='creation|predates'):
        asyncio.run(broker.account_cash_activities(after=NOW, through=NOW))
    assert PATH not in [path for _, path, _ in http.calls]


def test_initial_snapshot_change_is_not_a_current_cash_baseline():
    count = 0
    def snapshots(_):
        nonlocal count
        count += 1
        return Response(text='' if count == 1 else sse(activity_event()))
    broker, _ = selected(routes={PATH: snapshots})
    with pytest.raises(alpaca.MalformedBrokerPayload, match='replay disagreed'):
        asyncio.run(broker.account_cash_activities(after=NOW, through=NOW))


def test_actual_guarded_ingestion_and_restart_retains_exact_native_cash(conn):
    broker, http = selected()
    first = asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker,
        broker='alpaca', account_id=ACCOUNT_NUMBER, through=NOW))
    conn.commit()
    assert first.balance_total == Decimal('75.89')
    assert first.activity_identity_scheme == broker_cash.ACTIVITY_IDENTITY_SCHEME
    second = asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker,
        broker='alpaca', account_id=ACCOUNT_NUMBER, through=NOW.replace(second=1)))
    assert second.balance_total == first.balance_total
    assert second.last_activity_id == first.last_activity_id
    assert second.last_event_id == first.last_event_id
    assert conn.execute('SELECT COUNT(*) FROM sentinel_cash_flows').fetchone()[0] == 1
    assert not broker_cash.PlanCashBaseline('p', 'alpaca', ACCOUNT_NUMBER,
        NOW.date(), NOW, first.balance_total, first.last_activity_id,
        first.activity_identity_scheme).close_cash_finality_authoritative


@pytest.mark.parametrize('fault', ['malformed', 'correction', 'credentials', 'transport'])
def test_cash_boundary_preserves_structural_authority_and_transient_errors(conn, fault):
    from sentinel.execution.guarded import BrokerAuthorityRefused
    from sentinel.paper import cash
    from sentinel.paper.model import PaperActivationRefused, PaperRetryableRefused
    bad = activity_event(activity_type='DIV', activity_subtype='CDIV', net_amount='75.89')
    routes = {}
    if fault == 'malformed': bad['currency'] = 'EUR'
    if fault == 'correction': bad['previous_id'] = 'native-prior-reference'
    if fault in {'credentials', 'transport'}:
        routes[PATH] = Response(status_code=403 if fault == 'credentials' else 503)
    broker, _ = selected(events=sse(bad), routes=routes)
    expected = (BrokerAuthorityRefused if fault == 'credentials' else
                PaperRetryableRefused if fault == 'transport' else PaperActivationRefused)
    with pytest.raises(expected) as refused:
        asyncio.run(cash._broker_cash_state_or_refuse(conn, broker=broker,
            binding=binding.require(conn), through=NOW))
    assert isinstance(refused.value, PaperRetryableRefused) is (fault == 'transport')
    assert conn.execute('SELECT COUNT(*) FROM sentinel_cash_flows').fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['malformed', 'correction'])
def test_removed_structural_cash_classification_is_detected(conn, monkeypatch, fault):
    from sentinel.paper import cash
    tree = ast.parse(textwrap.dedent(inspect.getsource(cash._broker_cash_state_or_refuse)))
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Tuple)
        and any(isinstance(x, ast.Name) and x.id == 'MalformedBrokerEvidence' for x in n.type.elts)]
    assert len(matches) == 1
    matches[0].type = ast.Attribute(ast.Name('broker_cash', ast.Load()), 'BrokerCashAuthorityRefused', ast.Load())
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, '<removed-structural-cash-classification>', 'exec'), vars(cash), namespace)
    monkeypatch.setattr(cash, '_broker_cash_state_or_refuse', namespace['_broker_cash_state_or_refuse'])
    with pytest.raises(AssertionError):
        test_cash_boundary_preserves_structural_authority_and_transient_errors(conn, fault)


@pytest.mark.parametrize('guard', ['capability', 'bootstrap_replay', 'account_creation'])
def test_acceptance_oracle_detects_removed_guard(monkeypatch, guard):
    if guard == 'capability':
        original = AssetIdAlpacaExecutionBroker.__init__
        def missing(self, **kwargs):
            original(self, **kwargs)
            self.capabilities = replace(self.capabilities, account_cash_activity_evidence=False)
        monkeypatch.setattr(AssetIdAlpacaExecutionBroker, '__init__', missing)
        with pytest.raises(AssertionError):
            test_selected_cash_graph_and_guard_without_fill_or_finality_claims()
    else:
        method = (alpaca.AlpacaExecutionBroker.account_cash_activities
                  if guard == 'bootstrap_replay' else alpaca.AlpacaExecutionBroker._bounded_activity_events)
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        if guard == 'bootstrap_replay':
            matches = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == 'verify_snapshot_replay']
            assert len(matches) == 1
            matches[0].value = ast.Constant(False)
        else:
            matches = [n for n in ast.walk(tree) if isinstance(n, ast.If) and ast.unparse(n.test) == 'self.financial_activity_sse']
            assert len(matches) == 1
            matches[0].test = ast.Constant(False)
        ast.fix_missing_locations(tree)
        namespace = {}
        exec(compile(tree, '<removed-cash-acceptance-guard>', 'exec'), vars(alpaca), namespace)
        monkeypatch.setattr(alpaca.AlpacaExecutionBroker, method.__name__, namespace[method.__name__])
        with pytest.raises(pytest.fail.Exception):
            if guard == 'bootstrap_replay': test_initial_snapshot_change_is_not_a_current_cash_baseline()
            else: test_unknown_or_outside_history_account_creation_refuses_before_stream('2026-02-11T23:59:59Z')
