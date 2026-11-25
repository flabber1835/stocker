"""The November 16 result stays visible while the next plan prepares."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from sentinel import local_paper, paper_plan_preview
from sentinel.execution import fractional_progress, journal
from sentinel.execution.contract import OrderTerms
from sentinel.panel import authority_reader, model, observer_codec, overview, presentation, sources
from sentinel.panel.verification_monitor import paper_unknown
from tests.sentinel.test_fractional_plan_preview import inputs
from tests.sentinel.test_panel_trading_run import historical_run_db, historical_run_dsn  # noqa: F401

OPENED = datetime(2026, 11, 16, 14, 30, tzinfo=timezone.utc)
ENDED = OPENED+timedelta(minutes=10)


@pytest.fixture
def terminal(monkeypatch):
    plan, sizing = inputs()
    plan.update(decision_session=date(2026, 11, 13), effective_session=date(2026, 11, 16),
        created_at=OPENED-timedelta(hours=48), execute_at=OPENED+timedelta(minutes=1),
        valid_until=ENDED+timedelta(hours=14))
    sizing.update(decision_session='2026-11-13')
    sizing['broker_observation']['observed_at'] = (OPENED-timedelta(hours=48)).isoformat()
    intent = paper_plan_preview.project_original_intent(plan, sizing)
    filled = model.RunOrder(security_id='mtd', ticker='MTD', client_key='mtd-command',
        broker_order_id='mtd-order', side='BUY', quantity=None, notional=Decimal('1340.19'),
        filled_quantity=Decimal('0.771706809'), state='FILLED', observed_at=ENDED-timedelta(minutes=2),
        filled_average_price=Decimal('1736.644'), order_terms=OrderTerms(order_type='market').to_dict())
    run = model.TradingRun(intent=intent, state='SUPERSEDED',
        updated_at=ENDED, completed_at=ENDED, orders=[filled])
    diagnostic = dict(clean=True, runtime_state='RUNNING', unresolved=[], foreign_orders=[],
        foreign_positions=[], restricted_securities={}, observation_id=528,
        expected={'mtd': '0.771706809'}, actionable_deltas=[dict(security_id='crl', remaining='0')])
    row = (ENDED-timedelta(seconds=1), 'RUNNING', 'COMPLETE')
    observation = dict(completeness='COMPLETE', broker=plan['broker'], account_id=plan['broker_account_id'],
        positions=[dict(security_id='mtd', quantity='0.771706809')], orders=[dict(state='FILLED')])
    conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: row))
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda _: True)
    monkeypatch.setattr(journal, 'load_observation_payload', lambda *_: observation)
    return conn, plan, run, diagnostic, observation


def proof(terminal):
    conn, plan, run, diagnostic, _ = terminal
    return sources._opening_cutoff_progress(conn, plan, run, ('528', model.OPENING_CUTOFF, diagnostic),
        {'crl': fractional_progress.purchase_notional(Decimal('1338.66'))})


@pytest.mark.parametrize('typed', [False, True])
def test_legacy_and_current_proof_show_filled_and_unsent_notional(terminal, typed):
    conn, plan, recorded, diagnostic, _ = terminal
    if typed:
        diagnostic['actionable_deltas'][0].update(side='BUY', remaining_notional='1337.66')
    unsent, fact = proof(terminal)
    assert unsent['crl'].notional == Decimal('1337.66')
    assert fact.opening.observation_id == 528
    run = model.TradingRun.model_validate({**recorded.model_dump(), 'unsent_at_cutoff': unsent})
    for key in ('trading_run', 'completed_trading_run'):
        row = model.Row(key, 'History', 'OPENING WINDOW CLOSED', model.WARN,
            as_of=ENDED, trading_run=run, operational_fact=fact, valid_until=fact.opening.deadline)
        page = model.Panel(now=ENDED+timedelta(hours=7), rows=[row])
        html = overview._run_html(page)
        assert 'Today’s run · partially completed' in html
        assert '0.771706809 shares filled' in html and 'avg $1,736.64' in html
        assert 'Unsent · opening window closed' in html and '$1,337.66 unsent' in html
        assert 'Awaiting submission' not in html


@pytest.mark.parametrize('fault', ['wrong_positions', 'working_broker_order', 'foreign_account',
    'unresolved', 'wrong_security', 'wrong_notional', 'wrong_side'])
def test_unproved_unsent_outcome_cannot_be_rendered_as_a_clean_cutoff(terminal, fault):
    _conn, _plan, _run, diagnostic, observation = terminal
    if fault == 'wrong_positions':
        observation['positions'][0]['quantity'] = '0.7'
    elif fault == 'working_broker_order':
        observation['orders'][0]['state'] = 'ACKNOWLEDGED'
    elif fault == 'foreign_account':
        observation['account_id'] = 'foreign'
    elif fault == 'unresolved':
        diagnostic['unresolved'] = ['pending']
    elif fault == 'wrong_security':
        diagnostic['actionable_deltas'][0]['security_id'] = 'foreign'
    elif fault == 'wrong_notional':
        diagnostic['actionable_deltas'][0]['remaining_notional'] = '1338.66'
    else:
        diagnostic['actionable_deltas'][0]['side'] = 'SELL'
    assert proof(terminal) is None


@pytest.mark.parametrize('fault', [None, 'missing_restore', 'wrong_restore',
    'same_client_native_order', 'native_order_without_key', 'exact_get_native_order'])
def test_planned_buy_needs_exact_no_transport_chain_and_no_native_order(terminal, fault):
    conn, plan, recorded, diagnostic, observation = terminal
    planned = model.RunOrder(security_id='crl', ticker='CRL', client_key='crl-command',
        broker_order_id=None, side='BUY', quantity=None, notional=Decimal('1337.66'),
        filled_quantity=Decimal(0), state='PLANNED', observed_at=ENDED,
        order_terms=OrderTerms(order_type='market').to_dict())
    run = recorded.model_copy(update={'orders': [*recorded.orders, planned]})
    events = [(None, 'PLANNED', Decimal(0), None, plan['execute_at']),
              ('PLANNED', 'SEND_PENDING', Decimal(0), None, ENDED-timedelta(seconds=2)),
              ('SEND_PENDING', 'PLANNED', Decimal(0),
               'PRE_TRANSPORT_CHECKPOINT_RESTORED: cutoff', ENDED-timedelta(seconds=1))]
    observation['orders'][0]['client_key'] = 'mtd-command'
    observation['exact_evidence'] = []
    if fault == 'missing_restore':
        events.pop()
    elif fault == 'wrong_restore':
        events[-1] = (*events[-1][:3], 'unproved reset', events[-1][4])
    elif fault == 'same_client_native_order':
        observation['orders'].append({'state': 'FILLED', 'client_key': 'crl-command'})
    elif fault == 'native_order_without_key':
        observation['orders'].append({'state': 'FILLED'})
    elif fault == 'exact_get_native_order':
        observation['exact_evidence'].append({
            'client_key':'crl-command', 'order':{'client_key':'crl-command'}})
    saved = conn.execute
    conn.execute = lambda sql, *args: (SimpleNamespace(fetchall=lambda: events)
        if 'sentinel_command_events' in sql else saved(sql, *args))
    value = sources._opening_cutoff_progress(conn, plan, run,
        ('528', model.OPENING_CUTOFF, diagnostic),
        {'crl': Decimal('1337.66')})
    assert (value is not None) is (fault is None)


@pytest.mark.parametrize('verified', [False, True])
def test_dated_cutoff_is_a_negative_outcome_not_a_failed_observer(terminal, verified):
    _, fact = proof(terminal)
    row = model.paper_reconciliation_row(state='CYCLE_FAILED', cycle_state='SUPERSEDED')
    if verified:
        row = replace(row, as_of=fact.opening.started_at, valid_until=fact.opening.deadline,
            operational_fact=model.OperationalFact(
                kind='PAPER_VERIFICATION', state='SUPERSEDED', opening=fact.opening))
    now = ENDED+timedelta(seconds=1)
    reader = authority_reader.Reader(expected_keys=frozenset({'paper_reconciliation'}),
        unknown_factory=paper_unknown, key_factory=lambda *_: 'a'*64,
        evidence_reader=lambda *_: None, clock=lambda: 0., wall_clock=lambda: now)
    reader.answer = ('a'*64, observer_codec.pack([row], [], observed_at=now), None, now)
    rows, _, _, errors = reader.read('private', allow_start=False)
    assert not errors and rows[0].effective_status(now) == model.FAIL
    assert (reader.failure_diagnostic is None) is verified
    assert (reader.negative_result is None) is verified


def test_database_keeps_partial_history_after_its_plan_is_superseded(historical_run_db):
    conn, calls = historical_run_db
    conn.execute("""UPDATE sentinel_automation_cycles
        SET state='SUPERSEDED',failure_code=%s,diagnostic=%s""",
        (model.OPENING_CUTOFF, Jsonb({'actionable_deltas': [{'security_id':'crl','remaining':'0'}]})))
    assert sources._current_trading_run(conn) is None
    assert sources._completed_trading_run(conn)['completed_history'] is True
    conn.execute("""UPDATE sentinel_automation_cycles
        SET control_generation=86,certificate_sha256='new-cert',config_sha256='new-config'""")
    assert sources._current_trading_run(conn) == {'cycle_id':'old-cycle','completed_history':False}
    assert sources._completed_trading_run(conn) is None
    conn.execute("UPDATE sentinel_automation_cycles SET diagnostic='{}'::jsonb")
    assert sources._current_trading_run(conn) is None
    assert len(calls) == 2


def test_saved_replacement_cannot_retire_opening_failure_before_admission(terminal):
    _conn, _plan, recorded, _diagnostic, _observation = terminal
    unsent, fact = proof(terminal)
    run = model.TradingRun.model_validate({**recorded.model_dump(), 'unsent_at_cutoff': unsent})
    history = model.Row('trading_run', 'History', 'OPENING WINDOW CLOSED', model.WARN,
        as_of=ENDED, trading_run=run, operational_fact=fact, valid_until=fact.opening.deadline)
    now = datetime(2026, 11, 16, 21, 34, 55, tzinfo=timezone.utc)
    preview = run.intent.model_copy(update=dict(cycle_id='next-cycle', plan_id='next-plan',
        decision_session=date(2026, 11, 16), effective_session=date(2026, 11, 17),
        execute_at=OPENED+timedelta(days=1, minutes=1)))
    next_plan = model.Row('paper_plan', 'Next', 'READY', model.OK, paper_plan=preview)
    cycle = dict(cycle_id='next-cycle', plan_id='next-plan', state='PLAN_READY')
    assert sources._opening_cutoff_current_status(history, next_plan, cycle, now=now).status == model.FAIL
    cycle['state'] = 'WAITING_OPEN'
    wrong_plan = dict(cycle, plan_id='foreign')
    assert sources._opening_cutoff_current_status(history, next_plan, wrong_plan, now=now).status == model.FAIL
    retained = sources._opening_cutoff_current_status(history, next_plan, cycle, now=now)
    assert retained.status == model.WARN and retained.trading_run == history.trading_run
    page = model.Panel(now=now, rows=[next_plan, retained])
    assert not presentation.health_facts(page)['warnings']
    html = overview.overview_html(page)
    assert 'Next trading plan' in html and '$1,337.66 unsent' in html
