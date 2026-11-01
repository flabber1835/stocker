"""Metadata/stub checks only. Actual canonical integration must run hosted."""
import ast
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_', 'numpy', 'pandas')):
            raise ImportError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0, Fence())
import system_campaign_discovery_context as d


class Status(str, Enum):
    CURRENT = 'CURRENT'
    STALE = 'STALE'
    PENDING_TERMS_CARRIED = 'PENDING_TERMS_CARRIED'


@dataclass(frozen=True)
class Mark:
    status: Status
    stale_raw_close: float | None = None
    carried_raw_close: float | None = None

    @property
    def resolves_equity(self):
        return self.status is not Status.STALE


@dataclass
class Episode:
    security_id: str = 'S'
    current_shares: int = 10


@dataclass
class Core:
    episodes: dict = field(default_factory=lambda: {0: Episode()})
    cash: float = 1000.0
    sessions_since_valid_mark: dict = field(default_factory=dict)
    last_valid_mark_session: dict = field(default_factory=lambda: {'S': '2025-01-31'})

    def shares_by_security(self):
        return {v.security_id: v.current_shares for v in self.episodes.values()}

    def equity_view(self, marks, *, noncash_assets=0.0):
        return dict(marks=marks, noncash_assets=noncash_assets)


class TermsIncomplete(ValueError):
    pass


@dataclass(frozen=True)
class Term:
    security_id: str = 'S'
    complete: bool = False
    probe_refuses: bool = False
    cash_per_share: float = 12.5

    def completeness(self, shares):
        return self.complete, '' if self.complete else 'MISSING_CASH_PER_SHARE'


@dataclass(frozen=True)
class Publication:
    session: str = '2025-02-03'
    terminal_events: tuple = ()


def bindings():
    def apply(state, terms, *, ledger, counters=None):
        if terms.probe_refuses:
            state.cash += 777  # A partial mutation on the disposable probe.
            ledger.append('UNCOMMITTED_PROBE')
            raise TermsIncomplete('MISSING_CONVERSION_OPENING_VALUE')
        if not terms.complete:
            raise AssertionError('INCOMPLETE_TERMS_MUST_NOT_REACH_SETTLEMENT')
        state.cash += 125
        state.episodes.clear()
        ledger.append('CASH_MERGER')
        if counters is not None:
            counters['applied'] = counters.get('applied', 0)+1
        return dict(applied=True)

    def values(*, prior, published):
        term, = published.terminal_events
        if not term.complete:
            raise ValueError('incomplete leadership cash terminal: '+term.security_id)
        return {term.security_id: term.cash_per_share}

    def witness(state, **kwargs):
        return deepcopy(state), dict(observed_members=len(state['selected']))

    def original_advance(run, published):
        state = deepcopy(run.state)
        state.ledger['events'].append(dict(event_type='BUY', security_id='REAL_QUOTED_FILL'))
        state.last_decision = dict(target_core_exposure=1.0)
        state.state_hash = 'c'*64
        return SimpleNamespace(state=state, input_sha256=run.input_sha256)

    return SimpleNamespace(terminal=SimpleNamespace(apply_terminal=apply,
        sweep_orphans=lambda *args, **kwargs: ['ORPHAN_WRITE_OFF'], TermsIncomplete=TermsIncomplete),
        state=SimpleNamespace(PortfolioState=Core), marks=SimpleNamespace(MarkStatus=Status),
        terminal_returns=SimpleNamespace(values=values), median5=SimpleNamespace(witness=witness),
        kernel=SimpleNamespace(plan_session=lambda **kw: SimpleNamespace(leadership_candidates=[])),
        runtime=SimpleNamespace(advance=original_advance))


def prior():
    return SimpleNamespace(input_sha256='a'*64, state=SimpleNamespace(
        wealth_core=dict(episodes={'0': dict(security_id='S')}),
        pending=[dict(security_id='S')], median5=dict(selected=['S']),
        ledger=dict(events=[]), state_hash='b'*64))


@pytest.fixture
def scope(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'hosted', lambda: None)
    modules = bindings()
    with d.DiscoveryContext(tmp_path, source_sha256='d'*64, bindings=modules) as context:
        context.current = (prior(), Publication())
        yield context, modules


def events(context):
    return [json.loads(raw)['event'] for raw in (context.output/'discovery-events.jsonl').read_bytes().splitlines()]


def test_incomplete_terminal_does_not_pay_release_or_change_inputs(scope):
    context, modules = scope
    core, ledger, counters = Core(), [], {}
    term = Term()
    before = deepcopy((core, ledger, counters, term))
    result = modules.terminal.apply_terminal(core, term, ledger=ledger, counters=counters)
    assert not result['applied'] and result['pending']
    assert (core, ledger, counters, term) == before
    record, = events(context)
    assert record['kind'] == 'TERMINAL_APPLICATION_BYPASSED'
    assert record['roles'] == ['HELD', 'PENDING', 'LEADERSHIP']
    assert record['context']['source_term']['cash_per_share'] == 12.5
    assert record['context']['refusal'] == 'INCOMPLETE_TERMS:MISSING_CASH_PER_SHARE'


def test_probe_refusal_cannot_partially_mutate_diagnostic_book(scope):
    _, modules = scope
    core, ledger = Core(), []
    result = modules.terminal.apply_terminal(core, Term(complete=True, probe_refuses=True), ledger=ledger)
    assert result['pending'] and core.cash == 1000 and len(core.episodes) == 1 and ledger == []


def test_supported_cash_applies_once_and_preserves_original_counter(scope):
    _, modules = scope
    core, ledger, counters = Core(), [], {}
    result = modules.terminal.apply_terminal(core, Term(complete=True), ledger=ledger, counters=counters)
    assert result == dict(applied=True) and core.cash == 1125
    assert not core.episodes and ledger == ['CASH_MERGER'] and counters == dict(applied=1)


def test_unrecognized_engineering_exception_is_not_a_bypass(scope):
    context, _ = scope
    def broken(*args, **kwargs):
        raise ValueError('ENGINEERING_SCHEMA_ERROR')
    context.original_apply = broken
    with pytest.raises(ValueError, match='ENGINEERING_SCHEMA_ERROR'):
        context.apply_terminal(Core(), Term(complete=True), ledger=[])


def test_stale_sizing_carry_never_changes_mark_or_claims_a_price(scope):
    context, modules = scope
    mark = Mark(Status.STALE, stale_raw_close=100.0)
    original = {'S': mark}
    result = Core().equity_view(original, noncash_assets=10)
    carried = result['marks']['S']
    assert mark.status is Status.STALE and original['S'] is mark
    assert carried.status is Status.PENDING_TERMS_CARRIED and carried.carried_raw_close == 100
    record, = events(context)
    assert record['context']['source_print_session'] == '2025-01-31'
    assert record['context']['convention'].endswith('NO_SETTLEMENT')


@pytest.mark.parametrize('value', [None, 0.0, -1.0, float('nan'), float('inf')])
def test_no_positive_source_mark_refuses_without_zero_fallback(scope, value):
    with pytest.raises(ValueError, match='NO_POSITIVE_PRIOR_MARK'):
        Core().equity_view({'S': Mark(Status.STALE, stale_raw_close=value)})


def test_orphan_sweep_carries_instead_of_a_writeoff(scope):
    context, modules = scope
    core, ledger = Core(sessions_since_valid_mark={'S': 100}), []
    assert modules.terminal.sweep_orphans(core, ledger=ledger, session='2025-02-03') == []
    assert core.cash == 1000 and len(core.episodes) == 1 and ledger == []
    assert events(context)[0]['kind'] == 'ABSENT_HOLDING_RETAINED'


def test_leadership_gap_omits_observation_without_assuming_a_return(scope):
    context, modules = scope
    publication = Publication(terminal_events=(Term(), Term(security_id='Q', complete=True)))
    assert modules.terminal_returns.values(prior=context.current[0].state, published=publication) == {'Q': 12.5}
    selected = dict(selected=['S', 'Q'], selected_closes={'S': 100., 'Q': 10.})
    before = deepcopy(selected)
    result, report = modules.median5.witness(selected, session=publication.session,
        closes={}, terminal_values={'Q': 12.5})
    assert selected == before and result['selected'] == ['Q'] and report['observed_members'] == 1
    assert [r['kind'] for r in events(context)] == ['LEADERSHIP_TERMINAL_REFUSAL',
        'UNOBSERVABLE_WITNESS_RETURN_OMITTED', 'DIAGNOSTIC_WITNESS_DENOMINATOR']


def test_hooks_restore_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'hosted', lambda: None)
    modules = bindings()
    original = [modules.terminal.apply_terminal, Core.equity_view,
                modules.terminal_returns.values, modules.runtime.advance]
    with pytest.raises(RuntimeError, match='fixture failure'):
        with d.DiscoveryContext(tmp_path, source_sha256='d'*64, bindings=modules):
            raise RuntimeError('fixture failure')
    assert original == [modules.terminal.apply_terminal, Core.equity_view,
                        modules.terminal_returns.values, modules.runtime.advance]


def test_actual_transition_captures_fill_and_event_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'hosted', lambda: None)
    modules = bindings(); run = prior()
    with d.DiscoveryContext(tmp_path, source_sha256='d'*64, bindings=modules) as context:
        after = modules.runtime.advance(run, Publication())
        assert context.transitions == 1 and after.state.state_hash == 'c'*64
        record, = events(context)
        assert record['kind'] == 'CORE_TRANSITION_COMMITTED'
        assert record['context']['new_ledger_events'][0]['security_id'] == 'REAL_QUOTED_FILL'
        assert record['context']['account_performance_computed'] is False
    assert run.state.ledger['events'] == [] and run.state.state_hash == 'b'*64


def test_discovery_checkpoint_has_distinct_schema_and_cannot_be_financial():
    raw = dict(state=dict(last_processed_session='2025-02-03'))
    value = d.discovery_checkpoint(raw, parent_outer_sha256='a'*64,
        cursor='2025-02-03', transitions=1, event_chain_sha256='b'*64)
    assert value['runtime_checkpoint'] == raw and value['runtime_checkpoint'] is not raw
    assert value['schema'] == d.CHECKPOINT and value['financial_authority'] is False
    with pytest.raises(ValueError, match='CANNOT_ENTER_FINANCIAL_REPLAY'):
        d.require_strict_checkpoint(value)
    # A nested runtime payload is not an outer financial checkpoint either.
    with pytest.raises(ValueError, match='OUTER_SCHEMA_REQUIRED'):
        d.require_strict_checkpoint(value['runtime_checkpoint'])


def test_actual_guard_removal_falsifier():
    source = ast.parse((HERE/'system_campaign_discovery_context.py').read_bytes())
    fn, = [v for v in source.body if isinstance(v, ast.FunctionDef) and v.name == 'require_strict_checkpoint']
    fn.body = [ast.Return(value=ast.Name(id='value', ctx=ast.Load()))]
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-discovery-admission-guard>', 'exec'), namespace)
    payload = dict(schema=d.CHECKPOINT, authority=d.TAINT, financial_authority=False)
    def scenario(validator):
        with pytest.raises(ValueError, match='CANNOT_ENTER_FINANCIAL_REPLAY'):
            validator(payload)
    scenario(d.require_strict_checkpoint)
    with pytest.raises(pytest.fail.Exception):
        scenario(namespace['require_strict_checkpoint'])


def test_local_runtime_entry_is_fenced(tmp_path):
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        with d.DiscoveryContext(tmp_path, source_sha256='d'*64):
            pass
