"""Focused historical transport, metric, and restart falsifiers."""
from dataclasses import asdict
from decimal import Decimal as D
import json
import math
from types import SimpleNamespace

import pytest

from research.main_cagr import metrics, runtime, storage
from research.main_cagr.inputs import Packet, apply_repair
from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.session import SessionState
from sentinel.core.window_material import compile_rows
from sentinel.feed.calendar import previous_sessions
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


def fresh():
    config, strategy = production_strategy()
    return SessionState.fresh(starting_cash=50000, controller=Controller(config), strategy_identity=strategy)


def test_daily_drawdown_and_calendar_cagr_survive_restart():
    state, baseline = metrics.measure(None, '2020-01-31', 100)
    assert baseline['cagr'] is None
    state, _ = metrics.measure(state, '2020-02-10', 80)
    state = json.loads(json.dumps(state))
    _, result = metrics.measure(state, '2021-01-31', 120)
    assert D(result['multiple']) == D('1.2')
    assert D(result['maxdd']) == D('.2')
    assert result['cagr'] == pytest.approx(1.2**(365.2425/366)-1)
    with pytest.raises(ValueError, match='advance'):
        metrics.measure(state, '2020-02-10', 81)
    for bad in ('nan', 'inf', '0', '-1'):
        with pytest.raises(ValueError, match='positive'):
            metrics.measure(None, '2020-01-31', bad)


@pytest.fixture
def buffered():
    days = previous_sessions('2026-09-14', 300)
    buffer = runtime.Buffer('a'*64)
    for i, day in enumerate(days):
        bars, meta = [], {}
        for sid in ('A', 'B', 'GAP'):
            if sid == 'GAP' and i % 17 == 0:
                continue
            price = 100*math.exp(.001*i+.01*math.sin(i*.7))
            bars.append(VendorBar(day, sid, sid, price*2, price*2, 1e6, signal_close=price))
            meta[sid] = SecurityMeta(sid, sid, 'Domestic Common Stock', sid, first_session=days[0])
        buffer.append(Packet(day, tuple(bars), meta, {}, str(100+i*.1), {}, (), ()))
    return buffer


def test_compact_transport_equals_fully_typed_production_compiler(buffered):
    prior = SimpleNamespace(state_hash='b'*64, wealth_core={}, pending=[],
        median5={'selected':['A']}, last_processed_session=None,
        feed={'series':{'A':{'signal_basis_anchor':[buffered.axis[-2], 1]}}})
    published = buffered.prepare(prior, 1, formation=True)
    material = compile_rows(prior=prior,
        manifest=SimpleNamespace(snapshot_id=digest(dict(source='a'*64, session=buffered.axis[-1])),
                                 window=SimpleNamespace(sessions=list(buffered.axis))),
        metadata=buffered.metadata,
        resolve_identity=lambda ticker, day:buffered.aliases[day].get(ticker),
        publication_version=1, session=buffered.axis[-1],
        rows=(r.canonical() for sid in sorted(buffered.rows) for r in buffered.rows[sid]))
    assert published.window_features == material.model_dump(mode='json', by_alias=True)
    buffered.aliases[buffered.axis[-1]]['A'] = 'WRONG'
    with pytest.raises(ValueError, match='IDENTITY'):
        buffered.prepare(prior, 1, formation=True)


def test_observer_does_not_change_canonical_transition(buffered):
    prior = fresh()
    config, identity = production_strategy()
    published = buffered.prepare(prior, 1, formation=True)
    expected = advance_session(prior, published, controller_config=config, strategy_identity=identity)
    with runtime.observe_core() as evidence:
        actual = advance_session(prior, published, controller_config=config, strategy_identity=identity)
    assert expected.state_hash == actual.state_hash
    assert evidence['counters'] and 'terminal_results' in evidence


def saved(root):
    state = fresh()
    storage.append(root, 'daily.jsonl', {'session':'2020-01-31'})
    binding = {'source':'a'*64}
    path = storage.checkpoint(root, dict(binding=digest(binding), cursor='2020-01-31',
        state=state.to_dict(), state_sha256=state.state_hash))
    return binding, state, path


def test_restore_preserves_uncommitted_suffix_and_exact_canonical_state(tmp_path):
    binding, state, _ = saved(tmp_path)
    prefix = (tmp_path/'daily.jsonl').read_bytes()
    storage.append(tmp_path, 'daily.jsonl', {'uncommitted':True})
    _, restored = storage.restore(tmp_path, binding)
    assert restored.state_hash == state.state_hash
    assert (tmp_path/'daily.jsonl').read_bytes() == prefix
    assert len(list(tmp_path.glob('daily.jsonl.uncommitted-*'))) == 1


@pytest.mark.parametrize('fault', ['binding', 'checkpoint', 'output'])
def test_restore_rejects_changed_inputs_without_truncating(tmp_path, fault):
    binding, _, path = saved(tmp_path)
    if fault == 'binding':
        binding = {'source':'b'*64}
    elif fault == 'checkpoint':
        path.write_bytes(path.read_bytes()+b'changed')
    else:
        (tmp_path/'daily.jsonl').write_text('changed\n')
    before = (tmp_path/'daily.jsonl').read_bytes()
    with pytest.raises(ValueError, match='changed'):
        storage.restore(tmp_path, binding)
    assert (tmp_path/'daily.jsonl').read_bytes() == before


def test_terminal_repair_requires_exact_retained_event():
    old = TerminalTerms(session='2020-01-31', security_id='A', kind=TerminalKind.CASH_MERGER)
    new = TerminalTerms(session='2020-02-03', security_id='A', kind=TerminalKind.CASH_MERGER, cash_per_share=10)
    repair = dict(schema='terminal-repair/1', source_evidence=[{'sha256':'a'*64}],
        suppress=[dict(session=old.session, security_id='A', term_sha256=digest(asdict(old)))], add=[asdict(new)])
    source = {old.session:[old]}
    actual = apply_repair(source, repair)
    assert source == {old.session:[old]} and actual[new.session] == [new]
    repair['suppress'][0]['term_sha256'] = 'b'*64
    with pytest.raises(ValueError, match='identity changed'):
        apply_repair(source, repair)


def test_source_binding_normalizes_only_text_line_endings(tmp_path, monkeypatch):
    from research.main_cagr import run
    path = tmp_path/'source.py'
    path.write_bytes(b'x = 1\r\n')
    expected = run.source_hash(path)
    path.write_bytes(b'x = 1\n')
    assert run.source_hash(path) == expected
    path.write_bytes(b'x = 2\n')
    assert run.source_hash(path) != expected
    source = {'revision':run.BASE, 'files':{'source.py':expected}}
    monkeypatch.setattr(run.json, 'loads', lambda _:source)
    with pytest.raises(ValueError, match='source changed'):
        run.verify_source(tmp_path)
