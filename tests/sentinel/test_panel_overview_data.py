"""Read-only overview facts retain canonical ownership and native provenance."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect

import pytest
from pydantic import ValidationError

from sentinel.panel import model, overview_data, sources
from sentinel.paper_plan_preview import PlanPreview, PlannedLeg


NOW = datetime(2026, 10, 23, 5, tzinfo=timezone.utc)


def wealth_state():
    slots = {str(i): dict(slot_id=i, occupied_by=None, reserved_for=None,
        reserved_ticker=None, reserved_issuer=None, cooldown_sessions_elapsed=9)
        for i in range(20)}
    slots['0'].update(occupied_by='stock-a', cooldown_sessions_elapsed=None)
    slots['1'].update(reserved_for='stock-b', reserved_ticker='BBB',
        reserved_issuer='issuer-b', cooldown_sessions_elapsed=None)
    slots['2']['cooldown_sessions_elapsed'] = 20
    slots['3']['cooldown_sessions_elapsed'] = None
    episodes = {'0': dict(slot_id=0, security_id='stock-a', ticker='AAA',
        current_shares=12, exit_pending=True, exit_reason='EXIT_TRAILING_STOP')}
    return dict(cash='998', slots=slots, episodes=episodes)


def account(**changes):
    value = dict(broker='alpaca', account_id='paper-a', equity='50000.50',
                 cash='9635.82', buying_power='9635.82', observed_at=NOW)
    value.update(changes)
    return value


def preview():
    return PlanPreview(cycle_id='cycle', plan_id='next-plan', decision_session=date(2026,10,22),
        effective_session=date(2026,10,23), execute_at=NOW+timedelta(hours=8),
        created_at=NOW-timedelta(hours=8), observation_at=NOW-timedelta(hours=8),
        legs=[PlannedLeg(security_id='panw', ticker='PANW', current_quantity='0',
                        target_quantity='3', change_quantity='3', action='BUY'),
              PlannedLeg(security_id='ati', ticker='ATI', current_quantity='8',
                        target_quantity='0', change_quantity='-8', action='SELL')])


class Cursor:
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params): self.conn.executed.append((sql, params))
    def fetchall(self): return self.conn.rows


class Conn:
    def __init__(self, rows): self.rows, self.executed = rows, []
    def cursor(self): return Cursor(self)


def test_all_twenty_actual_slots_keep_identity_pending_exits_and_session_counters():
    wealth = wealth_state()
    before = deepcopy(wealth)
    slots = overview_data.shadow_slots(wealth)
    assert wealth == before
    assert [slot.slot_id for slot in slots] == list(range(20))
    assert slots[0].state == 'OCCUPIED' and slots[0].model_quantity == Decimal(12)
    assert slots[0].ticker == 'AAA' and slots[0].exit_pending
    assert slots[0].exit_reason == 'EXIT_TRAILING_STOP'
    assert slots[1].state == 'RESERVED' and slots[1].ticker == 'BBB'
    assert slots[1].model_quantity is None
    assert slots[2].state == 'COOLING' and slots[2].cooldown_remaining == 1
    assert slots[3].state == 'READY'
    assert slots[4].cooldown_elapsed == 9 and slots[4].cooldown_remaining == 12
    assert all(slot.cooldown_total == 21 for slot in slots)


def test_missing_slot_payload_is_unavailable_and_never_invented_as_ready():
    assert overview_data.shadow_slots(dict(episodes={})) == []
    with pytest.raises(ValueError):
        overview_data.shadow_slots(dict(slots={}, episodes={}))


@pytest.mark.parametrize('corruption', ['key', 'ownership', 'episode', 'double',
    'cooling-owned', 'boolean-clock', 'negative-clock', 'expired-clock', 'missing', 'extra-episode'])
def test_malformed_slot_facts_are_refused(corruption):
    wealth = wealth_state()
    if corruption == 'key': wealth['slots']['2']['slot_id'] = 3
    elif corruption == 'ownership': wealth['slots']['0']['occupied_by'] = 'other'
    elif corruption == 'episode': wealth['episodes']['0']['slot_id'] = 2
    elif corruption == 'double': wealth['slots']['0']['reserved_for'] = 'other'
    elif corruption == 'cooling-owned': wealth['slots']['0']['cooldown_sessions_elapsed'] = 1
    elif corruption == 'boolean-clock': wealth['slots']['2']['cooldown_sessions_elapsed'] = True
    elif corruption == 'negative-clock': wealth['slots']['2']['cooldown_sessions_elapsed'] = -1
    elif corruption == 'expired-clock': wealth['slots']['2']['cooldown_sessions_elapsed'] = 21
    elif corruption == 'missing': del wealth['slots']['3']
    elif corruption == 'extra-episode': wealth['episodes']['19'] = wealth['episodes']['0']
    with pytest.raises(ValueError): overview_data.shadow_slots(wealth)


def test_shadow_book_requires_complete_unique_slots_and_honest_cooldown_arithmetic():
    raw = dict(session='2026-10-22', cash='1000', receivables='0', nav='1000',
               pending_operations=0, holdings=[], slots=overview_data.shadow_slots(wealth_state()))
    model.ShadowBook(**raw)
    raw['slots'] = raw['slots'][:-1]
    # Missing the highest slot cannot be recognized without an expected count,
    # but a hole or duplicate is always invalid and cannot become a vacancy.
    raw['slots'][3] = raw['slots'][4]
    with pytest.raises(ValidationError): model.ShadowBook(**raw)
    with pytest.raises(ValidationError):
        model.ShadowSlot(slot_id=1, state='COOLING', cooldown_total=21,
                         cooldown_elapsed=20, cooldown_remaining=12)


def test_authenticated_holdings_projection_carries_slots_without_scaling_model_shares():
    wealth = wealth_state()
    state = dict(wealth_core=wealth, ledger=dict(receivables=[]), pending=[{}],
        feed=dict(series={'stock-a': dict(sessions=['2026-10-22'], raw_closes=[2])}))
    projected = sources._shadow_holdings(state, '2026-10-22', Decimal('1022'))
    assert len(projected.slots) == 20
    assert projected.holdings[0].quantity == projected.slots[0].model_quantity == 12
    assert projected.pending_operations == 1


def test_paper_account_values_are_exact_recorded_decimals_and_have_original_time():
    result = overview_data.account_overview(account(), expected_account_id='paper-a')
    assert result.cash == Decimal('9635.82') and result.equity == Decimal('50000.50')
    assert result.observed_at == NOW
    assert not hasattr(result, 'bil_value')  # No durable native mark: no invented allocation.


@pytest.mark.parametrize('changes', [dict(equity='NaN'), dict(cash='Infinity'),
    dict(cash='-1'), dict(cash='60000'), dict(buying_power='-1'),
    dict(equity='1e100'), dict(observed_at=NOW.replace(tzinfo=None))])
def test_malformed_account_economics_stay_unavailable(changes):
    with pytest.raises(ValidationError):
        overview_data.account_overview(account(**changes), expected_account_id='paper-a')


def assert_identity_guard(project):
    assert project(account(account_id='foreign'), expected_account_id='paper-a') is None


def test_account_identity_guard_falsifier_detects_its_removal():
    assert_identity_guard(overview_data.account_overview)
    source = inspect.getsource(overview_data.account_overview).replace(
        "if account.get('account_id') != expected_account_id:", 'if False:')
    scope = dict(model=model)
    exec(source, scope)
    with pytest.raises(AssertionError): assert_identity_guard(scope['account_overview'])


def test_prior_buy_preserves_exact_zero_fill_cancelled_state_without_invented_expiry():
    conn = Conn([('panw', 'PANW', 'client-123', 'native-123', 'BUY',
                  Decimal(3), Decimal(0), 'CANCELLED', NOW-timedelta(hours=9))])
    outcomes = sources._previous_buy_outcomes(conn, preview=preview())
    assert len(outcomes) == 1 and outcomes[0].state == 'CANCELLED'
    assert outcomes[0].quantity == 3 and outcomes[0].filled_quantity == 0
    assert outcomes[0].client_key == 'client-123' and outcomes[0].broker_order_id == 'native-123'
    assert outcomes[0].observed_at == NOW-timedelta(hours=9)
    sql, params = conn.executed[0]
    assert params == (['panw'], preview().created_at, preview().effective_session)
    for guard in ("b.ownership_state='SENTINEL_OWNED'", 'c.deployment_id=b.deployment_id',
        'c.broker=b.broker', 'c.broker_account_id=b.broker_account_id',
        'c.takeover_epoch=b.takeover_epoch', 'p.plan_id=c.plan_id',
        "c.side='BUY'", 'c.broker_order_id IS NOT NULL', 'p.effective_session<%s'):
        assert guard in sql
    assert sql.strip().startswith('SELECT')
    assert 'expired' not in outcomes[0].model_dump_json().lower()


@pytest.mark.parametrize('state,filled', [('UNKNOWN','0'), ('ACKNOWLEDGED','0'),
    ('PARTIALLY_FILLED','1'), ('CANCELLED','1'), ('REJECTED','0'), ('FILLED','3')])
def test_order_outcome_keeps_uncertainty_working_partial_and_terminal_facts(state, filled):
    result = model.PaperOrderOutcome(security_id='panw', ticker='PANW', client_key='key',
        broker_order_id='native', side='BUY', quantity='3', filled_quantity=filled,
        state=state, observed_at=NOW)
    assert result.state == state and result.filled_quantity == Decimal(filled)


@pytest.mark.parametrize('state,filled', [('FILLED','0'), ('PARTIALLY_FILLED','0'),
    ('PARTIALLY_FILLED','3'), ('CANCELLED','4'), ('EXPIRED','0')])
def test_invalid_order_economics_and_unretained_native_reason_are_refused(state, filled):
    with pytest.raises(ValidationError):
        model.PaperOrderOutcome(security_id='panw', ticker='PANW', client_key='key',
            broker_order_id='native', side='BUY', quantity='3', filled_quantity=filled,
            state=state, observed_at=NOW)


def test_unavailable_or_seller_only_preview_does_not_query_previous_buys():
    current = preview().model_copy(update={'legs': [preview().legs[1]]})
    conn = Conn([])
    assert sources._previous_buy_outcomes(conn, preview=current) == []
    assert conn.executed == []
