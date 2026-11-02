"""Pure AST/typed/stub tests; no canonical runtime or financial replay imports."""
import ast
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import system_campaign_discovery_spinoff_deferral as d

RAW = (HERE.parents[1]/'sentinel/core/spinoffs.py').read_bytes()


class TermsRequired(ValueError):
    pass


@dataclass(frozen=True)
class Distribution:
    session: str = '2021-05-25'
    parent_ticker: str = 'PARENT'
    parent_security_id: str | None = 'P'
    child_ticker: str | None = None
    child_security_id: str | None = None
    source_row_id: str = 'a'*64
    value_evidence: str | None = 'UNTRUSTED_SOURCE_VALUE_NOT_CASH'
    child_shares_per_parent: str | None = None
    child_price: str | None = None
    cash_in_lieu_price: str | None = None
    policy: str = d.MISSING_POLICY


@dataclass
class Episode:
    security_id: str = 'P'
    ticker: str = 'PARENT'
    current_shares: int = 20
    slot_id: int = 0
    source_lots: list = field(default_factory=list)
    entry_split_adjusted_price: float = 10.0
    episode_peak_split_adjusted_close: float = 11.0


@dataclass
class Book:
    episodes: dict = field(default_factory=lambda: {0: Episode()})
    cash: float = 50.0
    slots: dict = field(default_factory=lambda: {0: 'P'})


@dataclass
class Ledger:
    events: list = field(default_factory=list)
    receivables: list = field(default_factory=list)

    def accrue_dividend(self, **kwargs):
        self.events.append(dict(STUB_ORDINARY_DIVIDEND=kwargs))
        return 'STUB_ORDINARY_DIVIDEND'


@dataclass(frozen=True)
class Bar:
    security_id: str
    ticker: str
    raw_open: float = 5.0
    session: str = '2021-05-25'
    tradeable: bool = True
    dividend_per_share: float = 0.0


@dataclass(frozen=True)
class Publication:
    spinoff_distributions: tuple
    session: str = '2021-05-25'


def fraction(value, label):
    try:
        result = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise TermsRequired('invalid '+label) from exc
    if result <= 0:
        raise TermsRequired('invalid '+label)
    return result


def original_stub(state, distributions, *, ledger, bars, config):
    """Only a transport witness, never a Core financial transition."""
    unknown = [e for e in distributions if e.policy == d.MISSING_POLICY
               and any(ep.security_id == e.parent_security_id for ep in state.episodes.values())]
    if unknown:
        e = unknown[0]
        raise TermsRequired(f'{d.REFUSAL}{e.parent_ticker} on {e.session}, source {e.source_row_id}; canonical state is unchanged pending reviewed child terms')
    ledger.events.append({'STUB_SUPPORTED_CALL': True})
    return ('STUB_SUPPORTED_AUDIT',)


@pytest.fixture
def modules(monkeypatch):
    for name in ('engine', 'ledger', 'shares'):
        module = ModuleType('stock_strategy_shared.wealth_core.'+name)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    sys.modules['stock_strategy_shared.wealth_core.engine'].exit_proceeds = lambda shares, price, config: shares*price
    sys.modules['stock_strategy_shared.wealth_core.ledger'].EventType = SimpleNamespace()
    sys.modules['stock_strategy_shared.wealth_core.shares'].as_json = lambda v: v
    return SimpleNamespace(SpinoffDistribution=Distribution, SpinoffTermsRequired=TermsRequired,
        Decimal=Decimal, Fraction=Fraction, math=math, _positive_fraction=fraction,
        LIQUIDATE_CHILD_AT_OPEN='LIQUIDATE_CHILD_AT_OPEN', apply_supported_entitlements=original_stub)


def context(tmp_path, events):
    state = dict(wealth_core=dict(episodes={}), ledger=dict(events=[]))
    prior = SimpleNamespace(state_hash='1'*64, pending=[dict(security_id='P')],
        median5=dict(selected=['P']), to_dict=lambda: deepcopy(state))
    run = SimpleNamespace(state=prior, input_sha256='2'*64)
    emitted = []
    def emit(kind, sid=None, **kwargs):
        emitted.append(dict(kind=kind, security_id=sid, **kwargs))
    return SimpleNamespace(output=tmp_path, current=(run, Publication(tuple(events))), emit=emit,
        commitment=lambda: dict(rows=len(emitted), bytes=10, prefix_sha256='3'*64, chain_sha256='4'*64),
        emitted=emitted)


def install(tmp_path, modules, events):
    ctx = context(tmp_path, events)
    adapter = d.SpinoffDeferral(ctx, bindings=modules, source_raw=RAW)
    adapter.preflight = d.compile_preflight(RAW, vars(modules))
    adapter.original = original_stub
    adapter.number = d.original_number((HERE.parent/'bounded_20y/run.py').read_bytes())
    adapter.native_source = dict(rows={e.source_row_id: dict(effective_session=e.session,
        ticker=e.parent_ticker, security_id=e.parent_security_id, vendor_value=e.value_evidence,
        action='spinoff') for e in events}, multiplicity={e.source_row_id: 1 for e in events}, ordinary_dividends=set())
    return adapter, ctx


def kwargs():
    return dict(ledger=Ledger(), bars=(Bar('P', 'PARENT'), Bar('K', 'KNOWN')), config={})


def known(**changes):
    return replace(Distribution(), child_ticker='KNOWN', child_security_id='K', source_row_id='b'*64,
        policy='LIQUIDATE_CHILD_AT_OPEN', child_shares_per_parent='1/2', **changes)


def test_actual_source_projection_retains_every_canonical_preflight_guard():
    tree = d.preflight_tree(RAW)
    text = ast.unparse(tree)
    assert 'unresolved.append(missing_contract(event))' in text
    assert 'ledger.post' not in text and 'state.cash =' not in text
    assert 'reference_scale' in text and 'ambiguous held spin-off opening bars' in text
    assert 'duplicate held spin-off child terms' in text and 'held spin-off economics are invalid' in text
    assert 'cash-in-lieu price' in text and '_positive_fraction(event.child_shares_per_parent' in text
    with pytest.raises(ValueError, match='EXACT_FROZEN'):
        d.preflight_tree(RAW+b'\n')


def test_unresolved_set_records_known_and_unknown_leg_without_book_change(tmp_path, modules):
    events = (known(), Distribution())
    adapter, ctx = install(tmp_path, modules, events)
    book, kw = Book(), kwargs()
    before = deepcopy((book, kw, events))
    assert adapter.apply(book, events, **kw) == ()
    assert (book, kw, events) == before
    proof = ctx.emitted[0]['entitlement_proof']
    assert len(proof['affected_held_legs']) == 2 and not proof['partial_application']
    supported, unknown = proof['affected_held_legs']
    assert supported['disposition'] == 'SUPPORTED_LEG_DEFERRED_WITH_COMPLETE_SET'
    claim = unknown['unresolved_claim']
    assert claim['roles'] == ['HELD', 'PENDING', 'LEADERSHIP']
    assert claim['entitlement_status'] == 'UNRESOLVED_UNVALUED_NOT_SETTLED'
    assert not {'child_quantity', 'cash_proceeds', 'allocated_basis'}.intersection(claim)
    assert proof['book_and_ledger_before_sha256'] == proof['book_and_ledger_after_sha256']


def test_complete_supported_set_uses_original_once(tmp_path, modules):
    event = known()
    adapter, ctx = install(tmp_path, modules, (event,))
    kw = kwargs()
    assert adapter.apply(Book(), (event,), **kw) == ('STUB_SUPPORTED_AUDIT',)
    assert kw['ledger'].events == [{'STUB_SUPPORTED_CALL': True}] and not ctx.emitted


@pytest.mark.parametrize('bad', [
    replace(Distribution(), policy='OTHER'),
    replace(Distribution(), child_shares_per_parent='MALFORMED'),
    replace(Distribution(), cash_in_lieu_price='0'),
    replace(Distribution(), child_price='99'),
    replace(Distribution(), child_security_id='P'),
    replace(Distribution(), source_row_id=''),
    replace(Distribution(), parent_security_id=None),
    replace(Distribution(), parent_ticker='WRONG'),
])
def test_missing_contract_does_not_hide_malformed_source(tmp_path, modules, bad):
    events = (Distribution(), bad)
    adapter, ctx = install(tmp_path, modules, events)
    kw, book = kwargs(), Book()
    before = deepcopy((book, kw))
    with pytest.raises(ValueError):
        adapter.apply(book, events, **kw)
    assert (book, kw) == before and not ctx.emitted


@pytest.mark.parametrize('case', ['ratio', 'bar', 'identity', 'duplicate_bar', 'price', 'fraction'])
def test_unknown_first_never_hides_later_known_sibling_guard(tmp_path, modules, case):
    event = known()
    kw = kwargs()
    if case == 'ratio': event = replace(event, child_shares_per_parent='-1')
    elif case == 'bar': kw['bars'] = (kw['bars'][0],)
    elif case == 'identity': kw['bars'] = (kw['bars'][0], replace(kw['bars'][1], ticker='WRONG'))
    elif case == 'duplicate_bar': kw['bars'] += (kw['bars'][1],)
    elif case == 'price': kw['bars'] = (kw['bars'][0], replace(kw['bars'][1], raw_open=float('nan')))
    elif case == 'fraction': event = replace(event, child_shares_per_parent='1/3')
    events = (Distribution(), event)
    adapter, ctx = install(tmp_path, modules, events)
    with pytest.raises(TermsRequired):
        adapter.apply(Book(), events, **kw)
    assert not ctx.emitted and kw['ledger'].events == []


def test_duplicate_unknown_child_refuses_even_with_different_source(tmp_path, modules):
    first = replace(Distribution(), child_ticker='UNKNOWN', child_security_id='U')
    events = (first, replace(first, source_row_id='b'*64))
    adapter, ctx = install(tmp_path, modules, events)
    with pytest.raises(TermsRequired, match='duplicate held'):
        adapter.apply(Book(), events, **kwargs())
    assert not ctx.emitted


def test_unresolved_child_identity_cannot_be_invented_beyond_native_codec(tmp_path, modules):
    event = replace(Distribution(), child_ticker='UNKNOWN', child_security_id='U')
    adapter, ctx = install(tmp_path, modules, (event,))
    with pytest.raises(ValueError, match='EACH_UNKNOWN_EXACT_NATIVE_SOURCE_ROW'):
        adapter.apply(Book(), (event,), **kwargs())
    assert not ctx.emitted


def test_distinct_raw_unknown_identity_legs_retain_unresolved_relationship(tmp_path, modules):
    first = replace(Distribution(), child_security_id=None, child_ticker=None)
    second = replace(first, source_row_id='c'*64, value_evidence='OTHER_RAW_VALUE_NOT_COMBINED')
    adapter, ctx = install(tmp_path, modules, (first, second))
    book, kw = Book(), kwargs()
    before = deepcopy((book, kw))
    assert adapter.apply(book, (first, second), **kw) == ()
    assert (book, kw) == before
    proof = ctx.emitted[0]['entitlement_proof']
    relation, = proof['indeterminate_child_identity_relations']
    assert relation['source_row_ids'] == [first.source_row_id, second.source_row_id]
    assert relation['no_deduplication_combination_or_entitlement_count']
    assert len(proof['affected_held_legs']) == 2
    assert all(leg['unresolved_claim']['child_security_id'] is None for leg in proof['affected_held_legs'])


def test_repeated_same_unknown_identity_source_row_still_refuses(tmp_path, modules):
    event = replace(Distribution(), child_security_id=None, child_ticker=None)
    adapter, ctx = install(tmp_path, modules, (event, event))
    with pytest.raises(TermsRequired, match='duplicate held'):
        adapter.apply(Book(), (event, event), **kwargs())
    assert not ctx.emitted


def test_known_child_duplicate_still_refuses_before_missing_sibling_deferral(tmp_path, modules):
    event = known()
    events = (Distribution(), event, replace(event, source_row_id='c'*64))
    adapter, ctx = install(tmp_path, modules, events)
    with pytest.raises(TermsRequired, match='duplicate held'):
        adapter.apply(Book(), events, **kwargs())
    assert not ctx.emitted


def test_unknown_probe_that_mutates_or_raises_another_error_cannot_be_deferred(tmp_path, modules):
    event = Distribution()
    adapter, ctx = install(tmp_path, modules, (event,))
    def bad(state, events, **kw):
        state.cash += 100
        return original_stub(state, events, **kw)
    adapter.original = bad
    with pytest.raises(ValueError, match='ORIGINAL_REFUSAL_ATOMIC'):
        adapter.apply(Book(), (event,), **kwargs())
    assert not ctx.emitted
    def other(*a, **kw):
        raise TermsRequired('held spin-off economics are invalid')
    adapter.original = other
    with pytest.raises(ValueError, match='ONLY_ORIGINAL_MISSING_CHILD_REFUSAL'):
        adapter.apply(Book(), (event,), **kwargs())


def test_first_actual_deferral_must_match_own_expected_source(tmp_path, modules):
    event = Distribution()
    adapter, ctx = install(tmp_path, modules, (event,))
    adapter.expected_first = dict(session=event.session, source_row_id='f'*64)
    with pytest.raises(ValueError, match='FIRST_EXPECTED_OWN'):
        adapter.apply(Book(), (event,), **kwargs())
    assert not ctx.emitted


def next_state(ctx, additions=()):
    run, publication = ctx.current
    body = dict(ledger=dict(events=list(additions)), wealth_core=dict(episodes={}))
    state = SimpleNamespace(to_dict=lambda: deepcopy(body), state_hash='5'*64,
        last_processed_session=publication.session)
    return run, SimpleNamespace(state=state)


def test_success_proof_written_only_after_actual_transition_once(tmp_path, modules):
    event = Distribution()
    adapter, ctx = install(tmp_path, modules, (event,))
    adapter.apply(Book(), (event,), **kwargs())
    assert not list(tmp_path.rglob('*.json'))
    run, result = next_state(ctx, [dict(event_type='BUY', security_id='OTHER')])
    adapter.after(run, result)
    paths = list(tmp_path.rglob('*.json'))
    assert len(paths) == 1
    assert json.loads(paths[0].read_bytes())['status'] == 'ACTUAL_CANONICAL_DIAGNOSTIC_SPINOFF_DEFERRAL_QUALIFIED'
    adapter.after(run, result)
    assert len(list(tmp_path.rglob('*.json'))) == 1


def settlement_case(tmp_path, modules):
    event = Distribution()
    adapter, ctx = install(tmp_path, modules, (event,))
    adapter.apply(Book(), (event,), **kwargs())
    run, result = next_state(ctx, [dict(event_type='SPINOFF_RECEIPT', security_id='U')])
    return adapter, run, result


def test_actual_postcondition_rejects_spinoff_cash_or_share_settlement(tmp_path, modules):
    adapter, run, result = settlement_case(tmp_path, modules)
    with pytest.raises(ValueError, match='NO_RECEIPT_LIQUIDATION'):
        adapter.after(run, result)
    assert not list(tmp_path.rglob('*.json'))


def test_actual_settlement_guard_removal_falsifier(tmp_path, modules):
    adapter, run, result = settlement_case(tmp_path, modules)
    owner, = [n for n in ast.parse(Path(d.__file__).read_bytes()).body
              if isinstance(n, ast.ClassDef) and n.name == 'SpinoffDeferral']
    method, = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'after']
    class RemoveGuard(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(n, ast.Constant)
                and n.value == 'SPINOFF_DIAGNOSTIC_NO_RECEIPT_LIQUIDATION_OR_SOURCE_SETTLEMENT'
                for n in ast.walk(node)):
                return None
            return self.generic_visit(node)
    method = RemoveGuard().visit(method)
    scope = dict(vars(d))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
        '<actual-spinoff-settlement-guard-removed>', 'exec'), scope)
    scope['after'](adapter, run, result)
    assert len(list(tmp_path.rglob('*.json'))) == 1


def test_exact_predecessors_have_distinct_own_scopes_and_all_tails():
    value = json.loads((HERE/'system-campaign-discovery-suffix-spinoff-predecessors.json').read_bytes())
    assert set(value['arms']) == {'P06', 'P07'}
    p6, p7 = (value['arms'][n] for n in ('P06', 'P07'))
    assert (p6['transitions'], p6['selected_session'], p6['next_session']) == (270, '2019-02-28', '2019-03-01')
    assert (p7['transitions'], p7['selected_session'], p7['next_session']) == (463, '2021-04-30', '2021-05-03')
    assert p6['strict_parent_outer_sha256'] != p7['strict_parent_outer_sha256']
    for spec in (p6, p7):
        assert len(spec['full_current_streams']) == 6
        assert spec['current_streams_include_unsent_tails']
        assert spec['preserved_unsent_tails']['daily']['bytes'] > 0
        assert spec['preserved_unsent_tails']['events']['bytes'] > 0
        assert spec['retained_source_anchors']['rows'] == 0


def proxy_case(tmp_path, modules):
    event = replace(Distribution(), child_security_id=None, child_ticker=None,
        value_evidence='84.549999999999997')
    adapter, ctx = install(tmp_path, modules, (event,))
    adapter.native_source['rows'][event.source_row_id]['action'] = 'spinoffdividend'
    kw = kwargs()
    kw['bars'] = (replace(kw['bars'][0], dividend_per_share=84.55), kw['bars'][1])
    return event, adapter, ctx, kw


def test_source_cash_proxy_defers_accrual_without_zero_or_cash_receivable(tmp_path, modules):
    event, adapter, ctx, kw = proxy_case(tmp_path, modules)
    book, before = Book(), deepcopy(kw)
    assert adapter.apply(book, (event,), **kw) == ()
    called = dict(session=event.session, security_id='P', ticker='PARENT', shares=20,
        per_share=84.55, cash=50.0, due_in=1)
    assert adapter.accrue(kw['ledger'], **called) is None
    assert kw == before and book.cash == 50.0
    assert ctx.emitted[-1]['kind'] == 'SPINOFF_CASH_PROXY_ACCRUAL_DEFERRED'
    run, result = next_state(ctx)
    adapter.after(run, result)
    proof, = list(tmp_path.rglob('*.json'))
    value = json.loads(proof.read_bytes())
    assert value['cash_proxy_obligations'][0]['source_raw_value'] == event.value_evidence
    assert value['cash_proxy_obligations'][0]['actual_deferred_accruals'] == [dict(shares=20, ticker='PARENT')]
    assert kw['bars'][0].dividend_per_share == 84.55


@pytest.mark.parametrize('case', ['combined_ordinary', 'mismatched_amount', 'missing_bar', 'second_proxy'])
def test_ambiguous_or_unbound_cash_proxy_refuses(tmp_path, modules, case):
    event, adapter, ctx, kw = proxy_case(tmp_path, modules)
    events = (event,)
    if case == 'combined_ordinary': adapter.native_source['ordinary_dividends'].add((event.session, 'P'))
    elif case == 'mismatched_amount': kw['bars'] = (replace(kw['bars'][0], dividend_per_share=84.56), kw['bars'][1])
    elif case == 'missing_bar': kw['bars'] = (kw['bars'][1],)
    else:
        other = replace(event, source_row_id='c'*64)
        events += (other,)
        adapter.native_source['rows'][other.source_row_id] = dict(adapter.native_source['rows'][event.source_row_id])
        adapter.native_source['multiplicity'][other.source_row_id] = 1
        ctx.current = (ctx.current[0], Publication(events))
    with pytest.raises(ValueError, match='PROXY'):
        adapter.apply(Book(), events, **kw)
    assert not ctx.emitted and kw['ledger'].events == []


def test_ordinary_dividend_accrual_still_uses_original(tmp_path, modules):
    adapter, ctx = install(tmp_path, modules, ())
    calls = []
    adapter.original_accrue = lambda ledger, **kw: calls.append(kw) or 'ORDINARY'
    assert adapter.accrue(Ledger(), session='2021-05-25', security_id='OTHER', per_share=1.0) == 'ORDINARY'
    assert len(calls) == 1 and not ctx.emitted


def test_proxy_postcondition_rejects_missing_hook_and_mislabeled_dividend_cash(tmp_path, modules):
    event, adapter, ctx, kw = proxy_case(tmp_path, modules)
    adapter.apply(Book(), (event,), **kw)
    run, result = next_state(ctx)
    with pytest.raises(ValueError, match='EVERY_SOURCE_PROXY_ACCRUAL'):
        adapter.after(run, result)
    adapter.accrue(kw['ledger'], session=event.session, security_id='P', ticker='PARENT',
        shares=20, per_share=84.55, cash=50.0, due_in=1)
    run, result = next_state(ctx, [dict(event_type='DIVIDEND_ACCRUED', security_id='P')])
    with pytest.raises(ValueError, match='NO_CURRENT_PROXY_ACCRUAL'):
        adapter.after(run, result)
    assert not list(tmp_path.rglob('*.json'))


def test_native_actions_gzip_and_original_parser_guards_are_real():
    with pytest.raises(ValueError, match='EXACT_NATIVE_ACTION_GZIP'):
        d.native_actions(b'not the pinned source')
    parser = d.original_number((HERE.parent/'bounded_20y/run.py').read_bytes())
    assert parser('84.549999999999997') == 84.55
    assert parser('') is None
    with pytest.raises(ValueError): parser('nan')


def test_context_factory_runs_after_guard_and_restores_both_hooks(tmp_path, modules, monkeypatch):
    event = Distribution()
    template, ctx = install(tmp_path, modules, (event,))
    adapter_type = d.SpinoffDeferral
    monkeypatch.setattr(d, 'hosted', lambda: None)
    monkeypatch.setattr(d, 'SpinoffDeferral', lambda value, expected_first=None: adapter_type(value,
        bindings=modules, source_raw=RAW, expected_first=expected_first,
        native_source=template.native_source, number=template.number, ledger_class=Ledger))
    class Base:
        def __init__(self):
            self.__dict__.update(vars(ctx))
        def __enter__(self):
            self.active = True
            return self
        def __exit__(self, *args):
            self.active = False
        def advance(self, run, published):
            self.current = (run, published)
            try:
                modules.apply_supported_entitlements(Book(), (event,), **kwargs())
                return next_state(ctx)[1]
            finally:
                self.current = None
    wrapped = d.context_class(Base, expected_first=dict(session=event.session, source_row_id=event.source_row_id))
    original_accrue = Ledger.accrue_dividend
    with wrapped() as value:
        run, publication = ctx.current
        result = value.advance(run, publication)
        assert result.state.last_processed_session == event.session
        assert value.spinoff_deferral.uses == 1
        assert modules.apply_supported_entitlements != original_stub
        assert Ledger.accrue_dividend != original_accrue
    assert not value.active
    assert modules.apply_supported_entitlements is original_stub
    assert Ledger.accrue_dividend is original_accrue


def test_actual_proxy_cash_guard_removal_falsifier(tmp_path, modules):
    event, adapter, ctx, kw = proxy_case(tmp_path, modules)
    adapter.apply(Book(), (event,), **kw)
    adapter.accrue(kw['ledger'], session=event.session, security_id='P', ticker='PARENT',
        shares=20, per_share=84.55, cash=50.0, due_in=1)
    run, result = next_state(ctx, [dict(event_type='DIVIDEND_ACCRUED', security_id='P')])
    owner, = [n for n in ast.parse(Path(d.__file__).read_bytes()).body
              if isinstance(n, ast.ClassDef) and n.name == 'SpinoffDeferral']
    method, = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'after']
    class RemoveGuard(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(n, ast.Constant)
                and n.value == 'SPINOFF_DIAGNOSTIC_NO_CURRENT_PROXY_ACCRUAL_CASH_OR_RECEIVABLE'
                for n in ast.walk(node)):
                return None
            return self.generic_visit(node)
    method = RemoveGuard().visit(method)
    scope = dict(vars(d))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
        '<actual-spinoff-proxy-cash-guard-removed>', 'exec'), scope)
    scope['after'](adapter, run, result)
    assert len(list(tmp_path.rglob('*.json'))) == 1
