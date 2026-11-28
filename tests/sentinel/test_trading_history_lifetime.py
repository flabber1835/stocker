"""A dated display record expires without manufacturing a durable incident."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
from zoneinfo import ZoneInfo

import pytest

from sentinel.panel import model, presentation, review
from sentinel.paper_plan_preview import PlannedLeg
from tests.sentinel.test_dashboard_review import conn, panel, pg  # noqa: F401
from tests.sentinel.test_historical_cash_skip_transition import historical_row
from tests.sentinel.test_panel_opening_cutoff import proof, terminal  # noqa: F401

TICK = timedelta(microseconds=1)


@pytest.fixture(params=['cash', 'cutoff', 'success'])
def history(request, terminal):
    return history_row(request.param, terminal)


def history_row(outcome, terminal):
    if outcome == 'cash':
        return historical_row()
    _, plan, run, _, _ = terminal
    # The generic cutoff fixture deliberately uses an earlier expiry. This
    # replay needs the source's genuine exchange-day display boundary.
    plan['valid_until'] = datetime.combine(run.intent.effective_session+timedelta(days=1),
        datetime.min.time(), tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    filled_sales = [model.RunOrder(security_id=leg.security_id, ticker=leg.ticker,
        client_key='sale-'+leg.security_id, broker_order_id='native-'+leg.security_id,
        side='SELL', quantity=-leg.change_quantity, filled_quantity=-leg.change_quantity,
        filled_average_price=Decimal(20), state='FILLED', observed_at=run.updated_at,
        order_terms=run.orders[0].order_terms) for leg in run.intent.legs if leg.action == 'SELL']
    run = model.TradingRun.model_validate({**run.model_dump(), 'orders': [*run.orders, *filled_sales]})
    terminal = (terminal[0], plan, run, terminal[3], terminal[4])
    unsent, fact = proof(terminal)
    if outcome == 'cutoff':
        run = model.TradingRun.model_validate({**run.model_dump(), 'unsent_at_cutoff': unsent})
    else:
        run = model.TradingRun.model_validate({**run.model_dump(), 'state': 'SUCCEEDED'})
    return model.Row('trading_run', 'Recorded run', run.state,
        model.WARN if outcome == 'cutoff' else model.OK,
        as_of=run.updated_at, valid_until=fact.opening.deadline,
        trading_run=run, operational_fact=fact if outcome == 'cutoff' else None)


@pytest.fixture(params=['trading_run', 'completed_trading_run'])
def card(request, history):
    return replace(history, key=request.param)


def page_at(card, now):
    # Keep independent current facts current throughout the saved-card replay.
    base = panel()
    return replace(base, now=now, rows=[replace(row, as_of=now) for row in base.rows]+[card])


def test_same_cached_card_then_removal_never_creates_a_new_condition(card):
    boundary = card.valid_until
    for now in (boundary-timedelta(seconds=1), boundary, boundary+TICK,
                boundary+timedelta(seconds=10), boundary+timedelta(days=3)):
        page = page_at(card, now)
        assert presentation.health_facts(page) == {'active': [], 'warnings': []}, now
        if now > boundary:
            assert not card.can_show_trading_run(now)
        removed = replace(page, rows=page.rows[:-1])
        assert presentation.health_facts(removed) == presentation.health_facts(page)


@pytest.mark.parametrize('retained', [False, True])
def test_both_cards_share_retirement_without_clearing_other_warnings(history, retained):
    page = page_at(history, history.valid_until+TICK)
    other = replace(history, key='completed_trading_run')
    warning = model.Row('shadow_worker', 'Independent warning', 'ATTENTION', model.WARN,
                        as_of=page.now, valid_until=page.now+timedelta(minutes=1))
    page = replace(page, rows=[*page.rows, other, warning])
    if retained:
        page = replace(page, observation_current=False, observation_retained=True,
            observation_display_keys=tuple(row.key for row in page.rows))
    assert presentation.health_facts(page) == {'active': [], 'warnings': ['shadow_worker']}


@pytest.mark.parametrize('day', [date(2026, 3, 6), date(2026, 3, 9),
                                date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 27)])
def test_original_exchange_boundary_handles_dst_weekend_and_early_close(card, day):
    midnight = datetime.combine(day+timedelta(days=1), datetime.min.time(),
                                tzinfo=ZoneInfo('America/New_York'))
    boundary = (midnight-TICK).astimezone(timezone.utc)
    delta = boundary-card.valid_until
    run = card.trading_run
    intent = run.intent.model_copy(update=dict(effective_session=day,
        decision_session=day-timedelta(days=1), execute_at=run.intent.execute_at+delta,
        created_at=run.intent.created_at+delta,
        observation_at=run.intent.observation_at+delta if run.intent.observation_at else None))
    run = run.model_copy(update=dict(intent=intent, updated_at=run.updated_at+delta,
        completed_at=run.completed_at+delta if run.completed_at else None,
        orders=[order.model_copy(update={'observed_at': order.observed_at+delta}) for order in run.orders]))
    fact = card.operational_fact
    if fact is not None:
        opening = fact.opening
        fact = fact.model_copy(update={'opening': opening.model_copy(update=dict(
            started_at=opening.started_at+delta, deadline=boundary,
            reconciled_at=opening.reconciled_at+delta if opening.reconciled_at else None))})
    moved = replace(card, as_of=card.as_of+delta, valid_until=boundary,
                    trading_run=run, operational_fact=fact)
    for now in (boundary, midnight, midnight+timedelta(seconds=10)):
        assert presentation.health_facts(page_at(moved, now)) == {'active': [], 'warnings': []}


@pytest.mark.parametrize('bad', ['early_expiry', 'late_expiry', 'required', 'failed',
    'missing_run', 'future_run', 'future_order', 'unknown_order', 'working_order',
    'cancel_pending', 'unfilled_sale'])
def test_expiry_never_hides_unproved_or_unresolved_work(card, bad):
    assert_unproved_or_unresolved_work(card, bad)


@pytest.mark.parametrize('key', ['trading_run', 'completed_trading_run'])
@pytest.mark.parametrize(('outcome', 'bad'), [
    (outcome, bad) for outcome in ('cash', 'cutoff')
    for bad in ('unproved', 'wrong_plan', 'wrong_terminal_time', 'wrong_deadline')
] + [('cutoff', bad) for bad in ('unsent_sale', 'native_planned_buy')])
def test_retirement_specific_proof_cannot_hide_unproved_work(terminal, key, outcome, bad):
    card = replace(history_row(outcome, terminal), key=key)
    assert_unproved_or_unresolved_work(card, bad)


def assert_unproved_or_unresolved_work(card, bad):
    run, fact = card.trading_run, card.operational_fact
    changes = {}
    if bad == 'early_expiry':
        changes['valid_until'] = card.valid_until-timedelta(minutes=1)
    elif bad == 'late_expiry':
        changes['valid_until'] = card.valid_until+TICK
    elif bad == 'required':
        changes['required_current'] = True
    elif bad == 'failed':
        changes['status'] = model.FAIL
    elif bad == 'missing_run':
        changes['trading_run'] = None
    elif bad == 'future_run':
        changes['trading_run'] = run.model_copy(update={'updated_at': card.valid_until+timedelta(seconds=1)})
    elif bad == 'future_order':
        order = terminal_order(run).model_copy(update={'observed_at': card.valid_until+timedelta(seconds=1)})
        changes['trading_run'] = run.model_copy(update={'orders': [order, *run.orders[1:]]})
    elif bad in {'unknown_order', 'working_order', 'cancel_pending'}:
        state = {'unknown_order': 'UNKNOWN', 'working_order': 'ACKNOWLEDGED',
                 'cancel_pending': 'CANCEL_PENDING'}[bad]
        changes['trading_run'] = run.model_copy(update={'orders': [
            terminal_order(run).model_copy(update={'state': state}), *run.orders[1:]]})
    elif bad == 'unfilled_sale':
        sale = PlannedLeg(security_id='sale', ticker='SALE', current_quantity=Decimal(1),
            target_quantity=Decimal(0), change_quantity=Decimal(-1), action='SELL')
        changes['trading_run'] = run.model_copy(update={'intent': run.intent.model_copy(
            update={'legs': [*run.intent.legs, sale]})})
    elif bad == 'unproved':
        changes['operational_fact'] = None
    elif bad in {'wrong_plan', 'wrong_terminal_time', 'wrong_deadline'}:
        field, value = {'wrong_plan': ('plan_id', 'other-plan'),
            'wrong_terminal_time': ('started_at', fact.opening.started_at-TICK),
            'wrong_deadline': ('deadline', fact.opening.deadline+TICK)}[bad]
        changes['operational_fact'] = fact.model_copy(update={'opening': fact.opening.model_copy(update={field: value})})
    elif bad == 'unsent_sale':
        security = next(iter(run.unsent_at_cutoff))
        changes['trading_run'] = run.model_copy(update={'unsent_at_cutoff': {
            security: model.UnsentOpeningDelta(side='SELL', quantity=Decimal(1))}})
    else:
        security = next(iter(run.unsent_at_cutoff))
        order = terminal_order(run).model_copy(update=dict(security_id=security, state='PLANNED',
            broker_order_id='already-submitted', filled_quantity=Decimal(0)))
        changes['trading_run'] = run.model_copy(update={'orders': [order, *run.orders[1:]]})
    broken = replace(card, **changes)
    page = page_at(broken, card.valid_until+timedelta(seconds=10))
    assert not presentation._retired_trading_day(page, broken)
    facts = presentation.health_facts(page)
    assert broken.key in facts['active']+facts['warnings']


def terminal_order(run):
    if run.orders:
        return run.orders[0]
    from sentinel.execution.contract import OrderTerms
    return model.RunOrder(security_id='buy', ticker='BUY', client_key='buy',
        broker_order_id='native-buy', side='BUY', quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal(1), state='FILLED', observed_at=run.updated_at,
        order_terms=OrderTerms().to_dict())


def test_durable_acknowledgement_survives_rollover_and_card_removal(card, conn):
    owner = review.Recorder()
    before = page_at(card, card.valid_until-timedelta(seconds=1))
    first = owner.observe(before, conn.info.dsn)
    assert first.status == 'REVIEW' and first.token
    clean = owner.acknowledge(before, conn.info.dsn, first.token, actor='qualification')
    assert clean.status == 'CLEAN'
    for now in (card.valid_until, card.valid_until+TICK, card.valid_until+timedelta(seconds=10)):
        page = page_at(card, now)
        observed = owner.observe(page, conn.info.dsn)
        assert observed.status == 'CLEAN' and observed.head == clean.head
        assert presentation.dashboard_health(replace(page, operator_review=observed))['color'] == 'green'
    removed = replace(page, rows=page.rows[:-1])
    assert owner.observe(removed, conn.info.dsn).head == clean.head
    failed = replace(page, rows=[replace(row, status=model.FAIL) if row.key == 'authority'
                                else row for row in page.rows])
    assert owner.observe(failed, conn.info.dsn).status == 'FAILED'
    recovered = owner.observe(removed, conn.info.dsn)
    assert recovered.status == 'REVIEW' and recovered.head > clean.head


def test_retirement_guard_has_an_executed_falsifier(monkeypatch, card):
    source = inspect.getsource(presentation._classify_health_rows)
    broken = source.replace('if _retired_trading_day(panel, row):', 'if False:')
    assert broken != source
    namespace = dict(vars(presentation))
    exec(compile(broken, '<removed history-lifetime guard>', 'exec'), namespace)
    monkeypatch.setattr(presentation, '_classify_health_rows', namespace['_classify_health_rows'])
    with pytest.raises(AssertionError):
        test_same_cached_card_then_removal_never_creates_a_new_condition(card)


def workflow_history():
    current = historical_row()
    keys = ('automation_cycle', 'automation_step_transport',
            'automation_step_reconcile', 'automation_step_complete')
    original = [model.Row(key, key, 'SUPERSEDED', model.FAIL,
        as_of=current.as_of, required_current=True,
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='SUPERSEDED'))
        for key in keys]
    rows = model.project_retirement_history([current, *original], now=current.as_of)
    assert all(row.status == model.WARN and not row.required_current for row in rows)
    return current, rows[1:]


def test_exact_related_workflow_history_retires_with_its_run(conn):
    current, companions = workflow_history()
    owner = review.Recorder()
    page = page_at(current, current.valid_until-timedelta(seconds=1))
    page = replace(page, rows=[*page.rows, *companions])
    value = owner.observe(page, conn.info.dsn)
    clean = owner.acknowledge(page, conn.info.dsn, value.token, actor='qualification')
    for now in (current.valid_until, current.valid_until+TICK, current.valid_until+timedelta(seconds=10)):
        after = page_at(current, now)
        after = replace(after, rows=[*after.rows, *companions])
        assert presentation.health_facts(after) == {'active': [], 'warnings': []}
        observed = owner.observe(after, conn.info.dsn)
        assert observed.status == 'CLEAN' and observed.head == clean.head
    removed = replace(after, rows=[row for row in after.rows if row not in [current, *companions]])
    assert owner.observe(removed, conn.info.dsn).head == clean.head


@pytest.mark.parametrize('bad', ['failed', 'required', 'other_cycle', 'early_expiry', 'missing_proof'])
def test_related_workflow_cannot_hide_independent_work(bad):
    current, companions = workflow_history()
    page = page_at(current, current.valid_until+TICK)
    row = companions[0]
    if bad == 'failed':
        row = replace(row, status=model.FAIL)
    elif bad == 'required':
        row = replace(row, required_current=True)
    elif bad == 'other_cycle':
        row = replace(row, as_of=row.as_of+timedelta(seconds=1))
    elif bad == 'early_expiry':
        row = replace(row, valid_until=row.valid_until-timedelta(minutes=1))
    else:
        page = replace(page, rows=[replace(r, operational_fact=None) if r is current else r for r in page.rows])
    page = replace(page, rows=[*page.rows, row])
    facts = presentation.health_facts(page)
    assert row.key in facts['active']+facts['warnings']


@pytest.mark.parametrize(('guard', 'bad'), [
    ('not run.required_sales_filled()', 'unfilled_sale'),
    ('row.valid_until != boundary', 'late_expiry'),
    ('order.state not in settled', 'unknown_order'),
])
def test_history_safety_guards_have_executed_falsifiers(monkeypatch, terminal, guard, bad):
    # A successful card has no separate retirement proof that could mask a
    # broken sales, boundary or command-state check.
    card = history_row('success', terminal)
    source = inspect.getsource(presentation._retired_trading_day)
    broken = source.replace(guard, 'False')
    assert broken != source
    namespace = dict(vars(presentation))
    exec(compile(broken, '<broken history safety guard>', 'exec'), namespace)
    monkeypatch.setattr(presentation, '_retired_trading_day', namespace['_retired_trading_day'])
    with pytest.raises(AssertionError):
        test_expiry_never_hides_unproved_or_unresolved_work(card, bad)
