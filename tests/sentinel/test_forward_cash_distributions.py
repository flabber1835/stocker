from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from stock_strategy_shared.wealth_core.ledger import Ledger, EventType
from sentinel.core.cash_distributions import Inputs, Observation, apply, entitlement, observations

SID = 'permanent-owner'
EX = '2026-09-17'


def book(events=()):
    ledger = Ledger()
    # Establish a known accounting interval without claiming ownership of SID.
    ledger.post(session='2026-04-08', event_type=EventType.BUY, security_id='OTHER', cash_before=1000, shares_delta=1)
    for day, kind, shares in events:
        ledger.post(session=day, event_type=kind, security_id=SID, cash_before=1000, shares_delta=shares)
    return SimpleNamespace(ledger=ledger.to_dict(), state_hash='a'*64, last_processed_session='2026-10-06')


def reconcile(prior, rate='0.205', *, day='2026-10-07', version=2, **changes):
    ledger = Ledger.from_dict(prior.ledger)
    state = SimpleNamespace(cash=1000)
    payload = Inputs(prior_state_sha256=prior.state_hash, publication_version=version,
        session=day, observations=[Observation(security_id=SID, ticker='RENAMED', ex_date=EX,
            per_share=Decimal(rate), source_sha256='b'*64)]).model_dump(mode='json', by_alias=True)
    payload.update(changes)
    audit = apply(payload, prior=prior, published=SimpleNamespace(session=day, data_version=version),
                  state=state, ledger=ledger, lag=1)
    return ledger, audit


@pytest.mark.parametrize('events,expected', [
    ([], '0'),
    ([('2026-09-18', EventType.BUY, 200)], '0'),
    ([('2026-09-16', EventType.BUY, 100), ('2026-09-18', EventType.SELL, -100)], '100'),
    ([(EX, EventType.BUY, 200)], '0'),
    ([('2026-09-16', EventType.BUY, 100), (EX, EventType.SELL, -100)], '100'),
    ([('2026-09-16', EventType.BUY, 100), (EX, EventType.SPLIT, 100)], '200'),
    ([('2026-09-16', EventType.BUY, 100), ('2026-09-18', EventType.SPLIT, 100)], '100'),
])
def test_ex_date_ownership_is_independent_of_current_holdings(events, expected):
    prior = book(events)
    before = deepcopy(prior.ledger)
    ledger, audit = reconcile(prior)
    assert entitlement(Ledger.from_dict(prior.ledger), security_id=SID, ex_date=EX) == Decimal(expected)
    assert sum(Decimal(str(row['amount'])) for row in ledger.receivables) == Decimal(expected)*Decimal('.205')
    assert prior.ledger == before
    assert audit['observations'][0]['entitled_shares'] == expected


def test_restart_payment_and_amendment_are_incremental_and_do_not_rewrite_history():
    prior = book([('2026-09-16', EventType.BUY, 100), ('2026-09-18', EventType.SELL, -100)])
    ledger, _ = reconcile(prior)
    assert ledger.receivables[0]['amount'] == 20.5
    old = deepcopy(ledger.to_dict())
    restored = SimpleNamespace(**{**vars(prior), 'ledger': Ledger.from_dict(old).to_dict()})
    again, audit = reconcile(restored)
    assert again.to_dict() == old
    assert audit['observations'][0]['status'] == 'ALREADY_RECOGNIZED'
    revised, _ = reconcile(restored, '.25')
    assert [r['amount'] for r in revised.receivables] == [20.5, 4.5]
    reduced, audit = reconcile(restored, '.1')
    assert reduced.receivables[0]['amount'] == 10
    assert reduced.events[:len(old['events'])] == Ledger.from_dict(old).events
    assert audit['observations'][0]['status'] == 'CORRECTED_FORWARD'
    cash, payments = revised.settle_due(session='2026-10-08', cash=1000)
    assert cash == 1000 and not payments
    cash, payments = revised.settle_due(session='2026-10-09', cash=cash)
    assert cash == 1025 and len(payments) == 2


def test_pre_origin_entitlement_is_pending_without_cash_or_global_refusal():
    prior = book([('2026-10-01', EventType.BUY, 100)])
    prior.ledger['events'][0]['session'] = '2026-10-01'
    ledger, audit = reconcile(prior)
    assert not ledger.receivables
    assert audit['observations'][0]['status'] == 'ENTITLEMENT_PENDING'


def test_entitlement_multiplication_overflow_stays_pending_with_finite_json():
    import json
    prior = book([('2026-09-16', EventType.BUY, 100)])
    ledger, audit = reconcile(prior, '1e308')
    assert ledger.to_dict() == prior.ledger
    assert audit['observations'][0]['status'] == 'CASH_AMOUNT_PENDING'
    json.dumps({'ledger': ledger.to_dict(), 'audit': audit}, allow_nan=False)


def test_receivable_balance_overflow_cannot_poison_subsequent_settlement():
    prior = book([('2026-09-16', EventType.BUY, 1)])
    prior.ledger['receivables'] = [dict(security_id='OTHER', ticker='OTHER',
        amount=1e308, accrued_session=EX, due_in=1)]
    ledger, audit = reconcile(prior, '1e308')
    assert ledger.to_dict() == prior.ledger
    assert audit['observations'][0]['status'] == 'CASH_AMOUNT_PENDING'


def test_settlement_ages_from_knowledge_and_correction_is_scoped_to_one_ex_date():
    prior = book([('2026-09-16', EventType.BUY, 100)])
    ledger, _ = reconcile(prior)
    ledger.accrue_dividend(session='2026-09-18', security_id=SID, ticker='RENAMED',
                          shares=100, per_share=.3, cash=1000, due_in=1)
    prior.ledger = ledger.to_dict()
    corrected, _ = reconcile(prior, '.1')
    assert [(row['accrued_session'], row['amount']) for row in corrected.receivables] == [
        (EX, 10), ('2026-09-18', 30)]
    cash, paid = corrected.settle_due(session='2026-10-07', cash=1000)
    assert cash == 1000 and not paid
    restored = Ledger.from_dict(corrected.to_dict())
    cash, paid = restored.settle_due(session='2026-10-08', cash=cash)
    assert cash == 1040 and len(paid) == 2


@pytest.mark.parametrize('changes', [dict(prior_state_sha256='c'*64), dict(session='2026-10-08'), dict(publication_version=3)])
def test_unbound_cash_input_refuses(changes):
    with pytest.raises(ValueError, match='BINDING_CHANGED'):
        reconcile(book(), **changes)


def refs(rows):
    return SimpleNamespace(actions=[(str(i), row, None) for i, row in enumerate(rows)],
        resolver=SimpleNamespace(resolve=lambda ticker, day: SID))


def test_multiple_native_payments_aggregate_and_disappearance_is_not_cancellation():
    row = dict(action='dividend', ticker='RENAMED', date=EX, value='.1')
    current = refs([row, {**row, 'value': '.105'}])
    assert observations(refs([]), current, cursor='2026-10-06')[0].per_share == Decimal('.205')
    assert observations(current, refs([]), cursor='2026-10-06')[0].per_share == Decimal('.205')


@pytest.mark.parametrize('rate', [None, '0', '-.1', '1e500', 'NaN'])
def test_unusable_canonical_cash_stays_pending_and_does_not_cancel_known_terms(rate):
    known = dict(action='dividend', ticker='RENAMED', date=EX, value='.205')
    pending = []
    result = observations(refs([known]), refs([{**known, 'value': rate}]),
                          cursor='2026-10-06', pending=pending)
    assert result[0].per_share == Decimal('.205')
    assert any(row['reason'] == 'CASH_DISTRIBUTION_TERMS_PENDING' for row in pending)


def test_native_identity_union_retains_missing_payment_and_amends_only_named_payment():
    previous, current = refs([]), refs([])
    previous.cash_observations = [dict(id='one', ticker='RENAMED', date=EX, rate='.1'),
                                  dict(id='two', ticker='RENAMED', date=EX, rate='.105')]
    current.cash_observations = [dict(id='two', ticker='RENAMED', date=EX, rate='.15')]
    assert observations(previous, current, cursor='2026-10-06')[0].per_share == Decimal('.25')


def test_incomplete_native_components_cannot_cancel_a_legacy_aggregate():
    previous = refs([dict(action='dividend', ticker='RENAMED', date=EX, value='.205')])
    current = refs([])
    current.cash_observations = [dict(id='one', ticker='RENAMED', date=EX, rate='.1')]
    pending, floors, native = [], [], []
    result = observations(previous, current, cursor='2026-10-06', pending=pending,
                          floors=floors, knowledge=native)
    assert result[0].per_share == Decimal('.205')
    assert pending[0]['reason'] == 'CASH_DISTRIBUTION_NATIVE_COMPONENTS_UNKNOWN'
    retained = dict(source_observations=native, legacy_floors=[row.model_dump(mode='json') for row in floors])
    assert observations(refs([]), refs([]), cursor='2026-10-06', retained=retained)[0].per_share == Decimal('.205')


def test_outside_price_window_cash_identity_is_pending_without_global_failure():
    previous, current = refs([]), refs([])
    current.resolver = SimpleNamespace(resolve=lambda *_: None)
    current.cash_observations = [dict(id='outside', ticker='RENAMED', date='2024-09-17', rate='.2')]
    pending = []
    assert observations(previous, current, cursor='2026-10-06', pending=pending) == []
    assert pending[0]['reason'] == 'CASH_DISTRIBUTION_IDENTITY_UNRESOLVED'


def test_native_and_pending_knowledge_survives_multiple_absent_publications():
    previous, current = refs([]), refs([])
    current.cash_observations = [dict(id='one', ticker='RENAMED', date=EX, rate='.1'),
                                 dict(id='two', ticker='RENAMED', date=EX, rate='.105')]
    native = []
    initial = observations(previous, current, cursor='2026-10-06', knowledge=native)
    retained = dict(source_observations=native, observations=[dict(security_id=SID,
        ticker='RENAMED', entitlement_date=EX, per_share='.205')])
    empty = refs([])
    empty.resolver = SimpleNamespace(resolve=lambda *_: None)
    for _ in range(3):
        native = []
        again = observations(empty, empty, cursor='2026-10-06', retained=retained, knowledge=native)
        assert again[0].per_share == initial[0].per_share
        retained['source_observations'] = native
    pending = []
    changed = refs([])
    changed.cash_observations = [dict(id='one', ticker='RENAMED', date='2026-09-18', rate='.1')]
    result = observations(empty, changed, cursor='2026-10-06', retained=retained, pending=pending)
    assert [(row.ex_date, row.per_share) for row in result] == [(EX, Decimal('.205'))]
    assert pending[0]['reason'] == 'CASH_DISTRIBUTION_IDENTITY_CHANGED'


def test_reduced_paid_terms_debit_cash_once_and_insufficient_cash_is_pending():
    prior = book([('2026-09-16', EventType.BUY, 100)])
    ledger, _ = reconcile(prior)
    ledger.settle_due(session='2026-10-07', cash=1000)
    ledger.settle_due(session='2026-10-08', cash=1000)
    prior.ledger = ledger.to_dict()
    payload = Inputs(prior_state_sha256=prior.state_hash, publication_version=2, session='2026-10-07',
        observations=[Observation(security_id=SID, ticker='RENAMED', ex_date=EX,
                                 per_share=Decimal('.1'), source_sha256='b'*64)]).model_dump(mode='json', by_alias=True)
    for cash, expected in ((5, 'CORRECTION_PENDING'), (1000, 'CORRECTED_FORWARD')):
        state, restored = SimpleNamespace(cash=cash), Ledger.from_dict(prior.ledger)
        audit = apply(payload, prior=prior, published=SimpleNamespace(session='2026-10-07', data_version=2),
                      state=state, ledger=restored, lag=1)
        assert audit['observations'][0]['status'] == expected
        assert state.cash == (cash if cash == 5 else 989.5)
        Ledger.from_dict(restored.to_dict())
        if cash == 1000:
            next_prior = SimpleNamespace(**{**vars(prior), 'ledger': restored.to_dict()})
            again, audit = reconcile(next_prior, '.1')
            assert audit['observations'][0]['status'] == 'ALREADY_RECOGNIZED'


def converted_book():
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig, Op, Operation, apply_entry
    from stock_strategy_shared.wealth_core.terminal import TerminalTerms, TerminalKind, apply_terminal
    state, ledger, config = PortfolioState.fresh(5000), Ledger(), WealthCoreConfig()
    state.reserve_slot(0, 'OLD', 'OLD', 'issuer-old')
    before = state.cash
    apply_entry(state, op=Op(Operation.OPEN_SLOT_POSITION, None, 0, 'OLD', 'OLD', 100),
        session='2026-01-02', signal_session='2025-12-31', raw_open=10,
        split_adjusted_price=10, issuer_id='issuer-old', cfg=config)
    ledger.post(session='2026-01-02', event_type=EventType.BUY, cash_before=before,
        cash_delta=state.cash-before, security_id='OLD', ticker='OLD', shares_delta=100, price=10)
    terms = TerminalTerms(session='2026-02-02', security_id='OLD', kind=TerminalKind.CONVERSION,
        delivered_security_id=SID, delivered_ticker='RENAMED', delivered_issuer_id='issuer-new',
        exchange_ratio='.5', reference='reviewed-conversion')
    apply_terminal(state, terms, ledger=ledger, session=terms.session, cfg=config,
        source_signal_to_raw_scale=1, delivered_signal_to_raw_scale=1, delivered_raw_open=20)
    return state, ledger


def test_actual_conversion_credits_delivered_identity_and_removes_predecessor():
    state, ledger = converted_book()
    assert state.episodes[0].security_id == SID and state.episodes[0].current_shares == 50
    assert entitlement(ledger, security_id=SID, ex_date=EX) == 50
    assert entitlement(ledger, security_id='OLD', ex_date=EX) == 0
    assert entitlement(ledger, security_id=SID, ex_date='2026-02-02') == 0
    assert entitlement(ledger, security_id='OLD', ex_date='2026-02-02') == 100
    ledger.post(session='2026-09-18', event_type=EventType.SELL, security_id=SID,
                cash_before=state.cash, shares_delta=-50)
    restored = Ledger.from_dict(ledger.to_dict())
    assert entitlement(restored, security_id=SID, ex_date='2026-10-01') == 0


def test_forward_check_never_cancels_the_delivered_stocks_correct_dividend():
    state, ledger = converted_book()
    ledger.accrue_dividend(session=EX, security_id=SID, ticker='RENAMED',
        shares=50, per_share=1, cash=state.cash, due_in=1)
    prior = SimpleNamespace(ledger=ledger.to_dict(), state_hash='a'*64, last_processed_session='2026-10-06')
    checked, audit = reconcile(prior, '1')
    assert checked.to_dict() == ledger.to_dict()
    assert checked.receivable_total() == 50
    assert audit['observations'][0]['status'] == 'ALREADY_RECOGNIZED'


def test_multiple_conversion_legs_aggregate_existing_successor_ownership():
    _, ledger = converted_book()
    ledger.post(session='2026-01-05', event_type=EventType.BUY, cash_before=1000,
                security_id=SID, shares_delta=20)
    ledger.post(session='2026-01-06', event_type=EventType.BUY, cash_before=1000,
                security_id='SECOND', shares_delta=10)
    ledger.post(session='2026-03-02', event_type=EventType.CONVERSION, cash_before=1000,
        security_id='SECOND', shares_delta=20, detail={'shares_in':10, 'shares_delivered':30,
                                                     'delivered_security_id':SID})
    assert entitlement(ledger, security_id=SID, ex_date=EX) == 100
    assert entitlement(ledger, security_id='SECOND', ex_date=EX) == 0


def test_index_queries_do_not_rescan_lifetime_events_for_each_dividend():
    from sentinel.core.cash_distributions import OwnershipIndex
    class Counted(list):
        scans = 0
        def __iter__(self):
            self.scans += 1
            return super().__iter__()
    prior = book([('2026-09-16', EventType.BUY, 100)])
    ledger = Ledger.from_dict(prior.ledger)
    ledger.events = Counted(ledger.events)
    index = OwnershipIndex(ledger)
    for _ in range(100):
        assert index.entitlement(security_id=SID, ex_date=EX) == 100
    assert ledger.events.scans == 1
