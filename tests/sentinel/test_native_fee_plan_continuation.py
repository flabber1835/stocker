"""Native fee policy uses retained membership, not a numeric cash exception."""
import ast
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import inspect
import json
import textwrap
from types import SimpleNamespace
from uuid import UUID

import pytest
import psycopg

from sentinel import binding
from sentinel.execution import broker_cash, journal, protected_funding, protected_limits, target_reprojection
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerInstrument,
    BrokerObservation, OrderTerms, Side)
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import store
from sentinel.paper import cash
from sentinel.paper.model import PaperActivationRefused
from tests.sentinel.test_alpaca_boundary_overlay import Response, activity_event, sse
from tests.sentinel.test_paper_current_cash_acceptance import (
    ACCOUNT_NUMBER, NOW, PATH, conn, pg, selected)  # noqa: F401


def event(number, kind, amount):
    value = activity_event(activity_type=kind, activity_subtype=None,
        event_id=f"01J5R00000000000000000{number:03d}",
        ref_id=str(UUID(int=number)), net_amount=amount)
    value.pop('account_id')
    return value


def ingest(conn, events, *, hours=0):
    def activities(params):
        bounded = events
        if 'since_id' in params:
            bounded = [item for item in events
                if params['since_id'] <= item['event_id'] <= params['until_id']]
        return Response(text=sse(*bounded))
    broker, _ = selected(routes={PATH: activities})
    return asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker,
        broker='alpaca', account_id=ACCOUNT_NUMBER,
        through=NOW + timedelta(hours=hours)))


@pytest.fixture
def case(conn):
    old = event(1, 'DIV', '25')
    initial = ingest(conn, [old])
    bound = binding.require(conn)
    plan = ExecutionPlan('immutable-native-fee-plan', NOW.date(), NOW.date(), D(1),
        {'SEC-A': D(1)}, deployment_id=bound.deployment_id,
        broker=bound.broker, broker_account_id=bound.broker_account_id,
        takeover_epoch=bound.takeover_epoch, account_cash=D(1000), account_nav=D(2000))
    journal.save_plan(conn, plan)
    baseline = broker_cash.record_plan_baseline(conn, plan_id=plan.plan_id,
        decision_session=plan.decision_session, activity_state=initial)
    conn.commit()
    identity = BrokerAccountIdentity('alpaca', ACCOUNT_NUMBER)
    return dict(old=old, plan=plan, deployment=bound.identity, baseline=baseline,
        initial=initial, account=BrokerAccountSnapshot(identity=identity,
            cash=D(1000), equity=D(2000), buying_power=D(1000), multiplier=D(1),
            status='ACTIVE'), observation=BrokerObservation(NOW, account_identity=identity))


def check(conn, case, state, *, actual=None, recovery=False):
    value = actual if actual is not None else D(1000) + state.balance_total - D(25)
    return cash._cash_authority_or_refuse(conn, plan=case['plan'],
        deployment=case['deployment'], account=replace(case['account'], cash=value,
            buying_power=value), observation=case['observation'],
        activity_state=state, permit_new_activity=recovery)


def baseline_json(conn, case):
    return conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
        (broker_cash.PLAN_BASELINE_PREFIX + case['plan'].plan_id,)).fetchone()[0]


def fee_state(conn, case):
    return ingest(conn, [case['old'], event(2, 'FEE', '-0.04')], hours=1)


def test_multiple_fees_continue_exact_intents_and_survive_restart(conn, pg, case):
    original_plan = case['plan'].to_dict()
    original_fingerprint = case['plan'].fingerprint()
    original_baseline = baseline_json(conn, case)
    assert original_baseline['kind'] == 'broker-cash-plan/v4'
    assert len(original_baseline['activity_membership']) == 1
    events = [case['old'], event(2, 'FEE', '-0.04'), event(3, 'FEE', '-3.17')]
    state = ingest(conn, events, hours=1)
    for recovery in (False, True):
        assert check(conn, case, state, recovery=recovery) is False
    conn.commit()
    with store.connect(pg.sync_dsn) as restarted:
        replay = ingest(restarted, events, hours=2)
        assert check(restarted, case, replay) is False
        assert check(restarted, case, replay, recovery=True) is False
        assert broker_cash.load_plan_baseline(restarted, plan_id=case['plan'].plan_id) == case['baseline']
        assert baseline_json(restarted, case) == original_baseline
        retained = journal.load_plan(restarted, case['plan'].plan_id)
        assert retained.to_dict() == original_plan
        assert retained.fingerprint() == original_fingerprint
        assert journal.load_commands(restarted, case['deployment']) == ()
        assert restarted.execute('SELECT COUNT(*) FROM sentinel_cash_flows').fetchone()[0] == 3


@pytest.mark.parametrize('amount', ['-0.00000000000000000001', '-25', '-999'])
def test_fee_policy_has_no_cents_threshold(conn, case, amount):
    state = ingest(conn, [case['old'], event(2, 'FEE', amount)], hours=1)
    assert check(conn, case, state) is False


@pytest.mark.parametrize('events', [
    [('FEE', '0.04')], [('DIV', '-0.04')], [('WH', '-0.04')],
    [('CFEE', '-0.04')], [('CSD', '-0.04')],
    [('FEE', '-0.04'), ('DIV', '-0.01')],
    [('FEE', '-0.04'), ('FEE', '0.04')],
    [('FEE', '-1'), ('DIV', '0.50')],
])
def test_every_non_fee_credit_or_mixed_set_retains_retirement(conn, case, events):
    rows = [case['old']] + [event(i + 2, kind, value)
        for i, (kind, value) in enumerate(events)]
    state = ingest(conn, rows, hours=1)
    with pytest.raises(PaperActivationRefused, match='event set is durably explained'):
        check(conn, case, state)
    assert check(conn, case, state, recovery=True) is True


@pytest.mark.parametrize('damage', ['session', 'detail', 'amount', 'deleted', 'member_hash'])
def test_original_membership_cannot_be_changed_or_deleted(conn, case, damage):
    state = fee_state(conn, case)
    key = broker_cash.broker_flow_id(broker='alpaca', account_id=ACCOUNT_NUMBER,
        activity_id=case['old']['ref_id'])
    if damage == 'deleted':
        conn.execute('DELETE FROM sentinel_cash_flows WHERE flow_id=%s', (key,))
    elif damage == 'member_hash':
        raw = baseline_json(conn, case)
        raw['activity_membership'][key] = '0' * 64
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
            (json.dumps(raw), broker_cash.PLAN_BASELINE_PREFIX + case['plan'].plan_id))
    elif damage == 'detail':
        conn.execute("UPDATE sentinel_cash_flows SET detail=replace(detail,'type=DIV','type=INT') WHERE flow_id=%s", (key,))
    elif damage == 'amount':
        conn.execute('UPDATE sentinel_cash_flows SET amount=amount+1 WHERE flow_id=%s', (key,))
    else:
        conn.execute("UPDATE sentinel_cash_flows SET session=session+1 WHERE flow_id=%s", (key,))
    with pytest.raises(PaperActivationRefused, match='evidence is inconsistent'):
        check(conn, case, state)


@pytest.mark.parametrize('damage', ['class', 'type', 'id', 'unknown'])
def test_new_malformed_or_unknown_classification_never_earns_fee_policy(conn, case, damage):
    state = fee_state(conn, case)
    key = broker_cash.broker_flow_id(broker='alpaca', account_id=ACCOUNT_NUMBER,
        activity_id=str(UUID(int=2)))
    replacement = {'class': ('class=INTERNAL', 'class=EXTERNAL'),
        'type': ('type=FEE', 'type=INT'), 'id': ('id=', 'id=wrong-'),
        'unknown': ('type=FEE', 'type=FUTURE_CASH')}[damage]
    conn.execute('UPDATE sentinel_cash_flows SET detail=replace(detail,%s,%s) WHERE flow_id=%s',
        (*replacement, key))
    with pytest.raises(PaperActivationRefused):
        check(conn, case, state)


@pytest.mark.parametrize('damage', ['prior_edit', 'prior_deleted', 'offsetting_additions'])
def test_unchanged_total_and_last_id_cannot_hide_membership_changes(conn, case, damage):
    key = broker_cash.broker_flow_id(broker='alpaca', account_id=ACCOUNT_NUMBER,
        activity_id=case['old']['ref_id'])
    if damage == 'prior_edit':
        conn.execute('UPDATE sentinel_cash_flows SET session=session+1 WHERE flow_id=%s', (key,))
    elif damage == 'prior_deleted':
        conn.execute('DELETE FROM sentinel_cash_flows WHERE flow_id=%s', (key,))
    else:
        for number, kind, amount in [(2, 'FEE', '-0.04'), (3, 'DIV', '0.04')]:
            broker_cash._insert_activity(conn, broker='alpaca', account_id=ACCOUNT_NUMBER,
                activity=broker_cash.BrokerCashActivity(str(UUID(int=number)), kind,
                    NOW.date(), D(amount), {}))
    assert broker_cash.load_activity_state(conn, broker='alpaca', account_id=ACCOUNT_NUMBER) == case['initial']
    with pytest.raises(PaperActivationRefused, match='evidence is inconsistent'):
        check(conn, case, case['initial'])


@pytest.mark.parametrize('fault', ['missing_cursor', 'forged_total', 'scheme', 'account', 'clock', 'last_id'])
def test_current_native_cursor_is_required(conn, case, fault):
    state = fee_state(conn, case)
    if fault == 'missing_cursor':
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',
            (broker_cash.ACTIVITY_CURSOR_PREFIX + 'alpaca:' + ACCOUNT_NUMBER,))
    else:
        state = replace(state, **{
            'forged_total': dict(balance_total=D('24.95')),
            'scheme': dict(activity_identity_scheme=None),
            'account': dict(account_id='OTHER'),
            'clock': dict(processed_through=NOW - timedelta(seconds=1)),
            'last_id': dict(last_activity_id=case['old']['ref_id'])}[fault])
    with pytest.raises(PaperActivationRefused):
        check(conn, case, state)


@pytest.mark.parametrize('offset', ['0.01', '-0.01', '1', '-1'])
def test_fee_continuation_requires_exact_cash_not_old_generic_tolerance(conn, case, offset):
    state = fee_state(conn, case)
    with pytest.raises(PaperActivationRefused, match='exact fresh cash equation'):
        check(conn, case, state, actual=D('999.96') + D(offset))


def test_legacy_baseline_is_readable_but_never_backfilled(conn, case):
    raw = baseline_json(conn, case)
    raw['kind'] = 'broker-cash-plan/v3'
    del raw['activity_membership']
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
        (json.dumps(raw), broker_cash.PLAN_BASELINE_PREFIX + case['plan'].plan_id))
    old = broker_cash.load_plan_baseline(conn, plan_id=case['plan'].plan_id)
    assert old.activity_membership is None
    assert broker_cash.record_plan_baseline(conn, plan_id=case['plan'].plan_id,
        decision_session=case['plan'].decision_session, activity_state=case['initial']) == old
    assert baseline_json(conn, case) == raw
    state = fee_state(conn, case)
    with pytest.raises(PaperActivationRefused, match='event set is durably explained'):
        check(conn, case, state)
    assert check(conn, case, state, recovery=True) is True
    assert baseline_json(conn, case) == raw


@pytest.mark.parametrize('fault', ['missing', 'null', 'unknown_member', 'bad_hash', 'missing_last'])
def test_v4_membership_missing_or_malformed_never_becomes_legacy(conn, case, fault):
    raw = baseline_json(conn, case)
    if fault == 'missing':
        del raw['activity_membership']
    elif fault == 'null':
        raw['activity_membership'] = None
    elif fault == 'unknown_member':
        raw['activity_membership'] = {'broker-cash:v1:alpaca:OTHER:native': '0' * 64}
    elif fault == 'bad_hash':
        raw['activity_membership'] = {next(iter(raw['activity_membership'])): 'unknown'}
    else:
        raw['last_activity_id'] = 'missing-native'
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
        (json.dumps(raw), broker_cash.PLAN_BASELINE_PREFIX + case['plan'].plan_id))
    with pytest.raises(PaperActivationRefused, match='baseline is inconsistent'):
        check(conn, case, case['initial'])


def test_empty_plan_time_ledger_can_prove_its_first_native_fee(conn):
    initial = ingest(conn, [])
    baseline = broker_cash.record_plan_baseline(conn, plan_id='empty-plan',
        decision_session=NOW.date(), activity_state=initial)
    assert baseline.activity_membership == ()
    state = ingest(conn, [event(2, 'FEE', '-0.04')], hours=1)
    assert broker_cash.plan_activity_is_debit_fees_only(conn, baseline=baseline,
        activity_state=state) is True


def test_fee_does_not_grant_money_or_bypass_actual_cash_and_unknown_reservations(conn, case):
    state = fee_state(conn, case)
    assert check(conn, case, state) is False
    instrument = BrokerInstrument('SEC-A', 'AAA', 'native-a')
    candidate = Command(CommandIdentity(case['deployment'], case['plan'].plan_id, 'SEC-A'),
        instrument, Side.BUY, D(1), state=CommandState.SEND_PENDING,
        order_terms=OrderTerms(order_type='limit', limit_price=D(999)))
    values = dict(basis_cash=D(1000), commands=[candidate], candidate=candidate,
        deployment=case['deployment'], plan_id=case['plan'].plan_id)
    assert protected_funding.available_for_purchase(account=case['account'], **values) == D(1000)
    with pytest.raises(protected_funding.ProtectedFundingNotReady, match='reserved paper cash'):
        protected_funding.available_for_purchase(account=replace(case['account'],
            cash=D('999.96'), buying_power=D('999.96')), **values)
    unknown = replace(candidate, identity=CommandIdentity(case['deployment'], 'other-plan', 'SEC-A'),
        state=CommandState.UNKNOWN)
    with pytest.raises(protected_funding.ProtectedFundingNotReady, match='in-flight obligation'):
        protected_funding.available_for_purchase(account=case['account'],
            **dict(values, commands=[candidate, unknown]))


def mutant(monkeypatch, module, function, needle):
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(module, function))))
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.If)
        and needle in ast.unparse(node.test)]
    assert len(matches) == 1
    matches[0].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, '<removed-native-fee-guard>', 'exec'), vars(module), namespace)
    monkeypatch.setattr(module, function, namespace[function])


@pytest.mark.parametrize('guard', ['negative_fee', 'prior_member', 'exact_cash', 'unchanged_tuple'])
def test_guard_omission_is_detected(conn, case, monkeypatch, guard):
    if guard == 'negative_fee':
        mutant(monkeypatch, broker_cash, '_debit_fee_membership', 'row[1] >= 0')
        with pytest.raises(pytest.fail.Exception):
            test_every_non_fee_credit_or_mixed_set_retains_retirement(conn, case, [('FEE', '0.04')])
    elif guard == 'prior_member':
        mutant(monkeypatch, broker_cash, '_debit_fee_membership', 'commitment')
        with pytest.raises(pytest.fail.Exception):
            test_original_membership_cannot_be_changed_or_deleted(conn, case, 'session')
    elif guard == 'exact_cash':
        mutant(monkeypatch, cash, '_require_exact_fee_cash', 'Fraction(account.cash) != exact_expected')
        with pytest.raises(pytest.fail.Exception):
            test_fee_continuation_requires_exact_cash_not_old_generic_tolerance(conn, case, '0.01')
    else:
        tree = ast.parse(textwrap.dedent(inspect.getsource(cash._cash_authority_or_refuse)))
        matches = [node for node in ast.walk(tree) if isinstance(node, ast.If)
            and 'baseline.activity_membership is not None' in ast.unparse(node.test)]
        assert len(matches) == 1
        matches[0].test = ast.BoolOp(ast.And(), [ast.Name('activity_changed', ast.Load()), matches[0].test])
        ast.fix_missing_locations(tree)
        namespace = {}
        exec(compile(tree, '<restored-two-field-cash-shortcut>', 'exec'), vars(cash), namespace)
        monkeypatch.setattr(cash, '_cash_authority_or_refuse', namespace['_cash_authority_or_refuse'])
        with pytest.raises(pytest.fail.Exception):
            test_unchanged_total_and_last_id_cannot_hide_membership_changes(conn, case, 'prior_edit')


def earn_funding(conn, case, monkeypatch, *, state=None, limit='99'):
    monkeypatch.setenv('SENTINEL_PAPER_BUY_POLICY', protected_limits.PROTECTED_MODE)
    monkeypatch.setenv('SENTINEL_PAPER_BUY_CAP_BPS', '100')
    plan = case['plan']
    state = state or case['initial']
    amount = D(1000) + state.balance_total - D(25)
    snapshot = replace(case['account'], cash=amount, buying_power=amount)
    instrument = BrokerInstrument('SEC-A', 'AAA', 'native-a')
    candidate = Command(CommandIdentity(case['deployment'], plan.plan_id, 'SEC-A'),
        instrument, Side.BUY, D(1), state=CommandState.SEND_PENDING,
        order_terms=OrderTerms(order_type='limit', limit_price=D(limit)), created_at=NOW)
    projection = target_reprojection.TargetProjection(plan.plan_id, plan.fingerprint(),
        plan.effective_session, {}, (), {}, plan.target_basket)
    target_reprojection.record_projection(conn, projection)
    observed = replace(case['observation'], observed_at=state.processed_through,
        started_at=state.processed_through - timedelta(seconds=1))
    sequence = journal.record_observation(conn, observed, RuntimeState.RUNNING.value)
    reconciliation = ReconciliationResult(RuntimeState.RUNNING,
        observation=observed, observation_id=sequence)
    # Exact authenticated source/terms generation is independently covered by
    # the protected-limit tests; cash membership, journal, writer, basis and
    # current monetary admission here are all actual production owners.
    monkeypatch.setattr(protected_limits, 'submission_protection', lambda *_args, **_kwargs:
        (SimpleNamespace(source_provider='ALPACA_OPENFIGI', symbols={'SEC-A': 'AAA'},
            provider_asset_ids={'SEC-A': 'native-a'}),
         SimpleNamespace(for_security=lambda _sid: candidate.order_terms)))
    broker, _ = selected()
    with journal.writer_lock(conn, recovery_only=True):
        basis = protected_funding.record_quiescent_basis(conn, plan=plan,
            projection=projection, binding=binding.require(conn), reconciliation=reconciliation,
            account=snapshot, activity_state=state, observed_at=state.processed_through,
            paper_base_url='https://paper-api.alpaca.markets', broker=broker)
        journal.save_command(conn, candidate)
    assert isinstance(basis, protected_funding.NativeFeeFundingBasis)
    # The journal owns creation metadata; retain its actual original receipt.
    candidate = journal.load_commands(conn, case['deployment'],
        client_keys=[candidate.client_key])[0]
    return dict(basis=basis, candidate=candidate, broker=broker, projection=projection)


def funded_submit(conn, case, funded, state, *, actual=None):
    amount = actual if actual is not None else D(1000) + state.balance_total - D(25)
    candidate = funded['candidate']
    with journal.writer_lock(conn, recovery_only=True):
        return protected_funding.validate_submission(conn,
            client_key=candidate.client_key, instrument=candidate.instrument,
            quantity=candidate.quantity, order_terms=candidate.order_terms,
            account=replace(case['account'], cash=amount, buying_power=amount),
            activity_state=state, broker=funded['broker'])


def test_actual_funding_owner_continues_post_basis_fee_without_renewal(conn, pg, case, monkeypatch):
    funded = earn_funding(conn, case, monkeypatch)
    original_basis = funded['basis'].model_dump(mode='json')
    state = fee_state(conn, case)
    assert funded_submit(conn, case, funded, state) is None
    conn.commit()
    with store.connect(pg.sync_dsn) as restarted:
        assert funded_submit(restarted, case, funded, state) is None
        assert protected_funding.load_basis(restarted, plan_id=case['plan'].plan_id).model_dump(mode='json') == original_basis
        assert journal.load_plan(restarted, case['plan'].plan_id).fingerprint() == case['plan'].fingerprint()
        retained = journal.load_commands(restarted, case['deployment'])
        assert retained == (funded['candidate'],)


def test_actual_funding_owner_refuses_fee_that_consumes_immutable_maximum(conn, case, monkeypatch):
    funded = earn_funding(conn, case, monkeypatch, limit='999')
    state = fee_state(conn, case)
    assert check(conn, case, state) is False
    with pytest.raises(protected_funding.ProtectedFundingNotReady, match='reserved paper cash'):
        funded_submit(conn, case, funded, state)


@pytest.mark.parametrize('fault', ['mixed', 'credit', 'unproved', 'plan_v3', 'basis_v1', 'wrong_cash', 'unknown'])
def test_actual_funding_owner_keeps_all_negative_boundaries(conn, case, monkeypatch, fault):
    funded = earn_funding(conn, case, monkeypatch)
    events = [case['old'], event(2, 'FEE', '-0.04')]
    if fault == 'mixed':
        events.append(event(3, 'DIV', '-0.01'))
    if fault == 'credit':
        events = [case['old'], event(2, 'FEE', '0.04')]
    state = ingest(conn, events, hours=1)
    if fault == 'unproved':
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',
            (broker_cash.ACTIVITY_CURSOR_PREFIX + 'alpaca:' + ACCOUNT_NUMBER,))
    if fault == 'plan_v3':
        raw = baseline_json(conn, case)
        raw['kind'] = 'broker-cash-plan/v3'
        del raw['activity_membership']
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
            (json.dumps(raw), broker_cash.PLAN_BASELINE_PREFIX + case['plan'].plan_id))
    if fault == 'basis_v1':
        raw = funded['basis'].model_dump(mode='json')
        raw['schema'] = 'sentinel.protected-buy-funding/1'
        del raw['cash_activity_boundary']
        raw['funding_sha256'] = protected_funding._sha(raw)
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
            (json.dumps(raw), protected_funding.PREFIX + case['plan'].plan_id))
    if fault == 'unknown':
        candidate = funded['candidate']
        journal.save_command(conn, replace(candidate,
            identity=CommandIdentity(case['deployment'], 'old-plan', 'SEC-OTHER'),
            instrument=BrokerInstrument('SEC-OTHER', 'BBB', 'native-b'),
            state=CommandState.UNKNOWN))
    with pytest.raises(protected_funding.ProtectedFundingRefused):
        funded_submit(conn, case, funded, state,
            actual=D('999.97') if fault == 'wrong_cash' else None)


def test_funding_members_include_fees_already_present_when_basis_was_earned(conn, case, monkeypatch):
    before = fee_state(conn, case)
    funded = earn_funding(conn, case, monkeypatch, state=before)
    state = ingest(conn, [case['old'], event(2, 'FEE', '-0.04'), event(3, 'FEE', '-0.03')], hours=2)
    old_fee = broker_cash.broker_flow_id(broker='alpaca', account_id=ACCOUNT_NUMBER, activity_id=str(UUID(int=2)))
    new_fee = broker_cash.broker_flow_id(broker='alpaca', account_id=ACCOUNT_NUMBER, activity_id=str(UUID(int=3)))
    conn.execute('DELETE FROM sentinel_cash_flows WHERE flow_id=%s', (old_fee,))
    conn.execute('UPDATE sentinel_cash_flows SET amount=%s WHERE flow_id=%s', (D('-0.07'), new_fee))
    # The plan boundary alone still sees only preserved old DIV + new debit FEE.
    assert cash.native_fee_plan_continuation(conn, plan=case['plan'], deployment=case['deployment'],
        account=replace(case['account'], cash=D('999.93')), activity_state=state) is True
    with pytest.raises(protected_funding.ProtectedFundingRefused, match='membership is inconsistent'):
        funded_submit(conn, case, funded, state)


def test_actual_funding_owner_checks_members_when_activity_hash_is_unchanged(conn, case, monkeypatch):
    funded = earn_funding(conn, case, monkeypatch)
    key = broker_cash.broker_flow_id(broker='alpaca', account_id=ACCOUNT_NUMBER,
        activity_id=case['old']['ref_id'])
    conn.execute('UPDATE sentinel_cash_flows SET session=session+1 WHERE flow_id=%s', (key,))
    with pytest.raises(protected_funding.ProtectedFundingRefused, match='membership is inconsistent'):
        funded_submit(conn, case, funded, case['initial'])


@pytest.mark.parametrize('guard', ['funding_constituents', 'funding_unchanged', 'fee_only'])
def test_actual_funding_owner_omission_falsifiers(conn, case, monkeypatch, guard):
    if guard == 'funding_constituents':
        original = inspect.getsource(protected_funding._assert_native_fee_evidence)
        needle = 'baselines=(basis.cash_activity_boundary.baseline(plan), plan_boundary)'
        assert original.count(needle) == 1
        namespace = {}
        exec(compile(original.replace(needle, 'baselines=(plan_boundary,)'), '<removed-funding-membership>', 'exec'),
            vars(protected_funding), namespace)
        monkeypatch.setattr(protected_funding, '_assert_native_fee_evidence', namespace['_assert_native_fee_evidence'])
        with pytest.raises(pytest.fail.Exception):
            test_funding_members_include_fees_already_present_when_basis_was_earned(conn, case, monkeypatch)
    elif guard == 'funding_unchanged':
        original = inspect.getsource(protected_funding._assert_native_fee_evidence)
        needle = ('broker_cash.plan_activity_is_debit_fees_only(conn,\n'
                  '                baseline=basis.cash_activity_boundary.baseline(plan), activity_state=activity_state)')
        assert original.count(needle) == 1
        namespace = {}
        exec(compile(original.replace(needle, 'pass'), '<removed-unchanged-funding-membership>', 'exec'),
            vars(protected_funding), namespace)
        monkeypatch.setattr(protected_funding, '_assert_native_fee_evidence', namespace['_assert_native_fee_evidence'])
        with pytest.raises(pytest.fail.Exception):
            test_actual_funding_owner_checks_members_when_activity_hash_is_unchanged(conn, case, monkeypatch)
    else:
        mutant(monkeypatch, protected_funding, '_assert_native_fee_evidence', 'not all(fees)')
        with pytest.raises(pytest.fail.Exception):
            test_actual_funding_owner_keeps_all_negative_boundaries(conn, case, monkeypatch, 'mixed')


@pytest.mark.parametrize('changed', [False, True])
def test_one_funding_admission_reads_current_native_ledger_once(conn, case, monkeypatch, changed):
    funded = earn_funding(conn, case, monkeypatch)
    state = fee_state(conn, case) if changed else case['initial']
    counts = dict(cursor=0, ledger=0, commands=0)
    class CountingCursor(psycopg.Cursor):
        def execute(self, query, params=None, **kwargs):
            sql = ' '.join(str(query).split())
            if sql.startswith('SELECT flow_id,session,amount,detail FROM sentinel_cash_flows'):
                counts['ledger'] += 1
            if sql.startswith('SELECT') and 'FROM sentinel_commands WHERE TRUE' in sql:
                counts['commands'] += 1
            if (sql.startswith('SELECT state FROM sentinel_processed_sessions')
                    and params == (broker_cash.ACTIVITY_CURSOR_PREFIX + 'alpaca:' + ACCOUNT_NUMBER,)):
                counts['cursor'] += 1
            return super().execute(query, params, **kwargs)
    original = conn.cursor_factory
    conn.cursor_factory = CountingCursor
    try:
        assert funded_submit(conn, case, funded, state) is None
    finally:
        conn.cursor_factory = original
    assert counts == dict(cursor=1, ledger=1, commands=1)


def test_restoring_per_boundary_native_reads_fails_execution_count_oracle(conn, case, monkeypatch):
    original = inspect.getsource(broker_cash.activity_boundaries_are_debit_fees_only)
    assignment = '    rows = _current_cash_ledger(conn, activity_state=activity_state)\n'
    assert original.count(assignment) == original.count('rows=rows)') == 1
    changed = original.replace(assignment, '').replace('rows=rows)',
        'rows=_current_cash_ledger(conn, activity_state=activity_state))')
    namespace = {}
    exec(compile(changed, '<restored-duplicate-native-reads>', 'exec'), vars(broker_cash), namespace)
    monkeypatch.setattr(broker_cash, 'activity_boundaries_are_debit_fees_only',
        namespace['activity_boundaries_are_debit_fees_only'])
    with pytest.raises(AssertionError):
        test_one_funding_admission_reads_current_native_ledger_once(conn, case, monkeypatch, True)


@pytest.mark.parametrize('wrong_cash', [False, True])
def test_reused_account_journal_filters_older_plan_fills_from_current_cash(conn, case, monkeypatch, wrong_cash):
    funded = earn_funding(conn, case, monkeypatch)
    previous = replace(funded['candidate'],
        identity=CommandIdentity(case['deployment'], 'already-accounted-old-plan', 'SEC-OLD'),
        instrument=BrokerInstrument('SEC-OLD', 'OLD', 'native-old'), side=Side.SELL,
        state=CommandState.FILLED, filled_quantity=D(1), filled_average_price=D(50),
        broker_order_id='old-fill', order_terms=OrderTerms())
    journal.save_command(conn, previous)
    state = fee_state(conn, case)
    if wrong_cash:
        with pytest.raises(protected_funding.ProtectedFundingRefused, match='not exactly explained'):
            funded_submit(conn, case, funded, state, actual=D('1049.96'))
    else:
        assert funded_submit(conn, case, funded, state) is None


@pytest.mark.parametrize('guard', ['command_reuse', 'cash_plan_filter', 'promise_account_scope'])
def test_command_reuse_and_scope_omission_falsifiers(conn, case, monkeypatch, guard):
    if guard == 'cash_plan_filter':
        mutant(monkeypatch, cash, '_plan_fill_cash', 'command.identity.plan_id != plan.plan_id')
        with pytest.raises(pytest.fail.Exception):
            test_reused_account_journal_filters_older_plan_fills_from_current_cash(conn, case, monkeypatch, True)
        return
    if guard == 'command_reuse':
        module, function = protected_funding, '_assert_native_fee_evidence'
        needle, replacement = ('baseline=plan_boundary, commands=commands',
                               'baseline=plan_boundary, commands=None')
    else:
        module, function = protected_funding, 'validate_submission'
        needle = 'commands = journal.load_commands(conn, binding.identity)'
        replacement = 'commands = journal.load_commands(conn, binding.identity, plan_id=plan.plan_id)'
    original = inspect.getsource(getattr(module, function))
    assert original.count(needle) == 1
    namespace = {}
    exec(compile(original.replace(needle, replacement), '<removed-owned-journal-reuse>', 'exec'),
        vars(module), namespace)
    monkeypatch.setattr(module, function, namespace[function])
    if guard == 'command_reuse':
        with pytest.raises(AssertionError):
            test_one_funding_admission_reads_current_native_ledger_once(conn, case, monkeypatch, True)
    else:
        with pytest.raises(pytest.fail.Exception):
            test_actual_funding_owner_keeps_all_negative_boundaries(conn, case, monkeypatch, 'unknown')
