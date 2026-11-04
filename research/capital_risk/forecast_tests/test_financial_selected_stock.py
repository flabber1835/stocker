"""Own fresh pending-stock source and ratio guards; no canonical runtime."""
import ast
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_partial as p


def raw_term():
    return deepcopy(json.loads((f.HERE / f.OWN_CASH_CATALOG).read_bytes())['terms'][-1])


def pending():
    _, _, terms = f.selected('P00', cursor='2018-08-31'); term, = terms
    sid = term['security_id']; position, = term['parent_positions']
    episode = dict(position, security_id=sid, current_shares=position['quantity'], exit_pending=False)
    episode.pop('quantity')
    w = dict(episodes={'1': episode}, slots={'1': dict(occupied_by=sid)},
        terminal_pending_sessions={sid: 0}, terminal_pending_terms={sid: dict(stale_at_event=0, terms=term['native'])},
        unresolved_terminals={})
    return dict(sha256=term['parent_outer_sha256'], source_cursor='2018-08-31',
                run=dict(state=dict(wealth_core=w))), term, sid


def test_original_raw_stock_term_and_proxy_are_preserved_exactly():
    raw = raw_term(); saved = deepcopy(raw)
    f.retained_primary(raw)
    selected = f.selected_stock_term(raw)
    assert raw == saved and raw['added']['exchange_ratio'] == '.165'
    assert selected['added']['exchange_ratio'] == 0.165
    assert Fraction(str(selected['added']['exchange_ratio'])) == Fraction(33, 200)
    assert selected['proxy']['actual_settlement_rate_observed'] is False
    assert selected['identity_witness']['security_type_eligible'] == '1'
    assert selected['delivered_identity_witness']['issuer_id'] == 'SEC_CIK:1524358'
    assert selected['source_capture']['independent_data_review_sha256'] == 'a2d2223b0cb6d27d5088893d3a7eee58198b79eb6e09919600983993bbb46ec8'


def test_only_new_future_completion_is_added_and_consumed_native_is_preserved():
    cp, term, sid = pending(); saved = deepcopy(cp)
    assert f.suppressions(cp, [term]) == []
    assert cp == saved
    codec, _, _ = f.selected('P00', cursor='2018-08-31')
    material = dict(terms=[term], catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha, selector_sha256='a'*64,
        original_validator_description=codec.validator_description)
    cp['run']['checkpoint_sha256'] = 'b'*64
    document = f.document(cp, material, 'c'*64)
    assert document['suppress'] == [] and document['add'] == [term['added']]
    assert document['add'][0]['session'] == '2018-09-04'
    assert sid == '278081346388915134'


@pytest.mark.parametrize('change', ['root', 'shares', 'age', 'stale', 'native', 'slot', 'exit',
                                   'delivery_held', 'unresolved', 'clock', 'date'])
def test_wrong_pending_parent_or_source_scope_refuses(change):
    cp, term, sid = pending(); w = cp['run']['state']['wealth_core']
    if change == 'root': cp['sha256'] = '0'*64
    elif change == 'shares': w['episodes']['1']['current_shares'] = 91
    elif change == 'age': w['terminal_pending_sessions'][sid] = 1
    elif change == 'stale': w['terminal_pending_terms'][sid]['stale_at_event'] = 1
    elif change == 'native': w['terminal_pending_terms'][sid]['terms']['cash_per_share'] = 14.75
    elif change == 'slot': w['slots']['1']['occupied_by'] = None
    elif change == 'exit': w['episodes']['1']['exit_pending'] = True
    elif change == 'delivery_held': w['episodes']['2'] = dict(w['episodes']['1'], security_id=term['added']['delivered_security_id'])
    elif change == 'unresolved': w['unresolved_terminals'][sid] = {}
    elif change == 'clock': term['source_capture']['run_id'] = 0
    else: term['added']['session'] = cp['source_cursor']
    with pytest.raises(ValueError): f.suppressions(cp, [term])


def without_guard(name, label):
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    sites = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and any(isinstance(a, ast.Constant) and a.value == label for a in n.value.args)]
    assert len(sites) == 1; fn.body.remove(sites[0]); ns = dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-selected-stock-guard>', 'exec'), ns)
    return ns[name]


def test_pending_guard_removal_accepts_another_holding_quantity():
    cp, term, sid = pending(); cp['run']['state']['wealth_core']['episodes']['1']['current_shares'] = 91
    with pytest.raises(ValueError): f.pending_source_completion(cp, term)
    without_guard('pending_source_completion', 'FUTURE_EXACT_SOURCE_BOUND_OWN_PENDING_STOCK_COMPLETION')(cp, term)


@pytest.mark.parametrize('change', ['cash', 'ratio', 'proxy', 'metadata', 'source_hash', 'effective'])
def test_retained_stock_primary_literal_cannot_change(change):
    term = raw_term()
    if change == 'cash': term['added']['cash_per_share'] = 15.
    elif change == 'ratio': term['added']['exchange_ratio'] = '.166'
    elif change == 'proxy': term['proxy']['actual_settlement_rate_observed'] = True
    elif change == 'metadata': term['added']['delivered_issuer_id'] = 'WRONG'
    elif change == 'source_hash': term['retained_primary_catalog']['sha256'] = '0'*64
    else: term['added']['session'] = '2018-08-31'
    with pytest.raises(ValueError): f.retained_primary(term)


def test_ratio_normalization_cannot_silently_lose_literal_precision():
    term = raw_term(); term['added']['exchange_ratio'] = '.16500000000000000001'
    with pytest.raises(ValueError): f.selected_stock_term(term)
    broken = without_guard('selected_stock_term', 'OWN_INPUT_EXACT_RETAINED_STOCK_RIGHT_AND_RATIO_NORMALIZATION')
    assert broken(term)['added']['exchange_ratio'] == 0.165


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'diagnostic', 'unapplied'])
def test_selected_stock_must_apply_once_in_actual_canonical_step(change):
    term = raw_term()['added']; record = dict(session=term['session'], stock=[dict(
        security_id=term['security_id'], actual_context_call=True, applied=True)])
    if change == 'missing': record['stock'] = []
    elif change == 'duplicate': record['stock'] *= 2
    elif change == 'diagnostic': record['stock'][0]['actual_context_call'] = False
    else: record['stock'][0]['applied'] = False
    with pytest.raises(ValueError): f.actual_stock_phase(record, [term])


def test_removed_actual_stock_call_guard_accepts_missing_canonical_application():
    term = raw_term()['added']; record = dict(session=term['session'], stock=[])
    with pytest.raises(ValueError): f.actual_stock_phase(record, [term])
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'actual_stock_phase')
    loop, = [n for n in fn.body if isinstance(n, ast.For)]
    guard, = [n for n in loop.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
    loop.body.remove(guard); ns = dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-actual-stock-call-guard>', 'exec'), ns)
    ns['actual_stock_phase'](record, [term])
