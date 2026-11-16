"""A missing future action term may not rewrite the completed experiment."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal as D
import json

import pytest

from research.main_cagr import recovery, spinoff_repair, storage
from sentinel.feed.rolling_contract import digest
from sentinel.core.spinoffs import SpinoffTermsRequired, apply_supported_entitlements
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from test_in_kind_distributions import bars, complete_event, held_state
from test_main_cagr import fresh


@pytest.fixture
def repair(tmp_path):
    event = complete_event(child_price='31.90', cash_in_lieu_price='')
    source = tmp_path/'primary.html'
    source.write_text('Retained primary evidence for the test distribution.')
    document = dict(schema='research-spinoff-cash-repair/1',
        policy='FRACTIONAL_CIL_AT_CHILD_OPEN_LESS_COST_V1', session=event.session,
        source_row_id=event.source_row_id, term_sha256=digest(asdict(event)),
        raw_child_open='31.90', transaction_cost_bps=10, cash_in_lieu_price='31.86810',
        assumption='Modeled same-session liquidation, not an observed payment.',
        source_evidence=[dict(file=source.name, url='https://example.test/primary',
                              sha256=spinoff_repair.sha256(source))])
    path = tmp_path/'repair.json'
    path.write_text(json.dumps(document))
    return event, path, document


def test_fractional_child_cash_is_conserved_and_parent_quantity_is_unchanged(repair):
    event, path, _ = repair
    state, ledger = held_state(shares=1.501427006632), Ledger()
    original = deepcopy(state.to_dict())
    with pytest.raises(SpinoffTermsRequired, match='cash-in-lieu'):
        apply_supported_entitlements(state, [event], bars=bars(), ledger=ledger,
                                     config=WealthCoreConfig())
    assert state.to_dict() == original and not ledger.events
    schedule = {event.session:[event]}
    corrected, evidence = spinoff_repair.apply(schedule, path)
    audit = apply_supported_entitlements(state, corrected[event.session], bars=bars(),
                                         ledger=ledger, config=WealthCoreConfig())
    assert schedule[event.session] == [event] and event.cash_in_lieu_price == ''
    assert state.episodes[0].current_shares == 1.501427006632
    assert state.cash == pytest.approx(float(D('1000') + D('1.501427006632')*D('31.90')*D('.999')), abs=1e-10)
    assert audit[0]['whole_child_shares'] == 1
    assert ledger.events[-1].detail['cash_in_lieu'] == pytest.approx(float(D('.501427006632')*D('31.8681')))
    assert evidence['original_event'] == asdict(event)


@pytest.mark.parametrize('fault', ['term', 'evidence', 'price', 'net', 'policy', 'existing'])
def test_repair_refuses_changed_or_unreviewed_terms(repair, fault):
    event, path, document = repair
    if fault == 'term':
        event = replace(event, child_shares_per_parent='2')
    elif fault == 'evidence':
        (path.parent/'primary.html').write_text('changed')
    elif fault == 'price':
        document['raw_child_open'] = '32'
    elif fault == 'net':
        document['cash_in_lieu_price'] = '32'
    elif fault == 'policy':
        document['policy'] = 'INVENT_A_PRICE'
    else:
        event = replace(event, cash_in_lieu_price='31.9')
        document['term_sha256'] = digest(asdict(event))
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        spinoff_repair.apply({event.session:[event]}, path)


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    previous, target = tmp_path/'previous', tmp_path/'next'
    previous.mkdir()
    target.mkdir()
    original = dict(source_identity='a'*64, strategy={'fixed':'unchanged'},
        harness={name:'b'*64 for name in (*recovery.UNCHANGED_HARNESS, 'run.py', 'storage.py')})
    monkeypatch.setattr(recovery, 'PREDECESSOR_BINDING', digest(original))
    storage.write_json(previous/'identity.json', {'binding':original})
    state = fresh()
    storage.append(previous, 'daily.jsonl', {'session':'2015-06-30', 'nav':'12345.67'})
    saved = dict(binding=digest(original), cursor='2015-06-30', measured=2245,
        state=state.to_dict(), state_sha256=state.state_hash, formation=None,
        economics={'nav':'12345.67'}, metrics={'peak':'20000'}, counters={'retained':3})
    storage.checkpoint(previous, saved)
    storage.write_json(previous/'refusal.json', dict(last_completed_session='2015-06-30',
        attempted_session='2015-07-01', measured_sessions=2245))
    repair = {'document':{'session':'2015-07-01'}}
    binding = {**deepcopy(original), 'prospective_spinoff_repair':repair,
        'effective_source_identity':digest(dict(predecessor=original['source_identity'], spinoff_repair=repair))}
    binding['harness']['run.py'] = 'c'*64
    return previous, target, original, binding, saved


def test_recovery_preserves_original_bytes_and_exact_state_and_accounting(predecessor):
    previous, target, original, binding, saved = predecessor
    prefix = (previous/'daily.jsonl').read_bytes()
    storage.append(previous, 'daily.jsonl', {'uncommitted':'must not be copied or removed'})
    before = {p.name:p.read_bytes() for p in previous.iterdir()}
    lineage = recovery.fork(previous, target, {'binding':binding})
    actual, state = storage.restore(target, binding)
    assert {p.name:p.read_bytes() for p in previous.iterdir()} == before
    assert (target/'daily.jsonl').read_bytes() == prefix
    assert state.state_hash == saved['state_sha256']
    for key in ('state', 'metrics', 'economics', 'counters', 'measured', 'cursor'):
        assert actual[key] == saved[key]
    assert lineage['predecessor_binding'] == digest(original)
    with pytest.raises(ValueError, match='binding changed'):
        storage.restore(target, original)


@pytest.mark.parametrize('fault', ['predecessor', 'past', 'same_day', 'source', 'strategy', 'accounting', 'prefix', 'refusal'])
def test_recovery_refuses_other_changes_before_copying(predecessor, fault):
    previous, target, original, binding, _ = predecessor
    if fault == 'predecessor':
        original['extra'] = 'unreviewed'
        storage.write_json(previous/'identity.json', {'binding':original})
    elif fault in ('past', 'same_day'):
        binding['prospective_spinoff_repair']['document']['session'] = '2015-06-29' if fault == 'past' else '2015-06-30'
        binding['effective_source_identity'] = digest(dict(predecessor=original['source_identity'],
            spinoff_repair=binding['prospective_spinoff_repair']))
    elif fault == 'source':
        binding['effective_source_identity'] = 'changed'
    elif fault == 'strategy':
        binding['strategy'] = {'fixed':'changed'}
    elif fault == 'accounting':
        binding['harness']['metrics.py'] = 'changed'
    elif fault == 'prefix':
        (previous/'daily.jsonl').write_text('changed\n')
    else:
        storage.write_json(previous/'refusal.json', dict(last_completed_session='2015-06-29',
            attempted_session='2015-07-01', measured_sessions=2245))
    with pytest.raises(ValueError):
        recovery.fork(previous, target, {'binding':binding})
    assert not list(target.iterdir())


@pytest.fixture
def terminal_predecessor(predecessor, monkeypatch):
    previous, target, _, prior, saved = predecessor
    prior = deepcopy(prior)
    prior['harness']['spinoff_repair.py'] = 'd'*64
    monkeypatch.setattr(recovery, 'TERMINAL_PREDECESSOR_BINDING', digest(prior))
    storage.write_json(previous/'identity.json', {'binding':prior})
    saved.update(binding=digest(prior), cursor='2018-11-30', measured=3108)
    selected = storage.checkpoint(previous, saved)
    storage.append(previous, 'daily.jsonl', {'session':'2018-12-07', 'pending_merger':True})
    latest = {**saved, 'cursor':'2018-12-07', 'measured':3112}
    storage.checkpoint(previous, latest)
    storage.write_json(previous/'refusal.json', dict(last_completed_session='2018-12-07',
        attempted_session='2018-12-10', measured_sessions=3112))
    repairs = [{'document':{'suppress':[{'session':'2018-12-07'}],
                            'add':[{'session':'2018-12-07'}]}}]
    binding = {**deepcopy(prior), 'prospective_terminal_repairs':repairs,
        'effective_source_identity':digest(dict(predecessor=prior['effective_source_identity'],
                                                terminal_repairs=repairs))}
    return previous, target, prior, binding, saved, selected


def test_selected_checkpoint_preserves_later_predecessor_rows(terminal_predecessor):
    previous, target, _, binding, saved, selected = terminal_predecessor
    before = {p.name:p.read_bytes() for p in previous.iterdir()}
    lineage = recovery.fork(previous, target, {'binding':binding}, selected.name)
    actual, state = storage.restore(target, binding)
    assert {p.name:p.read_bytes() for p in previous.iterdir()} == before
    assert state.state_hash == saved['state_sha256']
    assert actual['cursor'] == '2018-11-30' and actual['measured'] == 3108
    for key in ('state', 'economics', 'metrics', 'counters'):
        assert actual[key] == saved[key]
    assert b'pending_merger' not in (target/'daily.jsonl').read_bytes()
    assert b'pending_merger' in (previous/'daily.jsonl').read_bytes()
    assert lineage['predecessor_checkpoint']['file'] == selected.name
    assert lineage['latest_predecessor_checkpoint']['session'] == '2018-12-07'


@pytest.mark.parametrize('fault', ['latest', 'past_suppress', 'past_add', 'prior_assumption',
                                  'prior_assumption_code', 'corrupt', 'future_only', 'no_replacement'])
def test_terminal_recovery_cannot_hide_past_changes(terminal_predecessor, fault):
    previous, target, prior, binding, _, selected = terminal_predecessor
    name = selected.name
    if fault == 'latest':
        name = None
    elif fault in ('past_suppress', 'past_add'):
        leg = 'suppress' if fault == 'past_suppress' else 'add'
        binding['prospective_terminal_repairs'][0]['document'][leg][0]['session'] = '2018-11-30'
    elif fault == 'prior_assumption':
        binding['prospective_spinoff_repair']['document']['extra'] = 'changed'
    elif fault == 'prior_assumption_code':
        binding['harness']['spinoff_repair.py'] = 'changed'
    elif fault == 'corrupt':
        selected.write_bytes(selected.read_bytes()+b'changed')
    elif fault == 'future_only':
        for leg in ('suppress', 'add'):
            binding['prospective_terminal_repairs'][0]['document'][leg][0]['session'] = '2020-01-01'
    else:
        binding['prospective_terminal_repairs'][0]['document']['suppress'] = []
    binding['effective_source_identity'] = digest(dict(predecessor=prior['effective_source_identity'],
        terminal_repairs=binding['prospective_terminal_repairs']))
    with pytest.raises(ValueError):
        recovery.fork(previous, target, {'binding':binding}, name)
    assert not list(target.iterdir())


@pytest.mark.parametrize('name', ['../checkpoint.json.gz', 'checkpoint-unknown.json.gz', '/tmp/checkpoint.json.gz'])
def test_selected_checkpoint_requires_a_content_address(name, predecessor):
    previous, _, original, _, _ = predecessor
    with pytest.raises(ValueError, match='filename'):
        storage.read_checkpoint(previous, original, name)
