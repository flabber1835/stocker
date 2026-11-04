"""Own pending native and extra identity source capture; DATA/synthetic only."""
import ast
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import make_dataclass
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from research.capital_risk.forecast_tests.test_financial_source_witnesses import source_fixture, spec
import system_campaign_financial_future as f
import system_campaign_financial_partial as p


def pending_fixture():
    cp, scope, natives, rows = source_fixture()
    cp['source_cursor'] = scope['parent_cursor'] = natives[0]['session']
    sid = natives[0]['security_id']
    w = cp['run']['state']['wealth_core']
    w.update(terminal_pending_sessions={sid: 0}, terminal_pending_terms={sid: dict(stale_at_event=0, terms=deepcopy(natives[0]))},
             unresolved_terminals={})
    scope['terms'][0]['pending_at_parent'] = dict(pending_sessions=0, stale_at_event=0,
        native_term_sha256=f.digest(natives[0]), unresolved=False)
    extra = dict(session='2022-07-22', security_id='child', ticker='CHILD', issuer_id='SOURCE:unchanged-child',
        listing_first_session='2012-01-03', security_type_eligible='0', raw_open='123.45')
    scope['additional_rows'] = [dict(session=extra['session'], security_id=extra['security_id'], ticker=extra['ticker'],
        source_observation_sha256=f.digest(extra), parent_positions=[])]
    return cp, scope, natives, rows, [extra]


def test_exact_pending_and_additional_rows_preserve_parent_and_source_metadata():
    cp, scope, natives, rows, extra = pending_fixture(); before = deepcopy((cp, scope, natives, rows, extra))
    value = f.witness_payload(cp, 'P04', scope, natives, rows, extra)
    assert f.validate_witness_capture(value, spec(cp), scope) == value
    assert value['schema'] == f.SOURCE_WITNESS_PENDING_SCHEMA
    assert value['terms'][0]['pending_context'] == scope['terms'][0]['pending_at_parent']
    assert value['additional_rows'][0]['source_row'] == extra[0]
    assert value['additional_rows'][0]['identity_witness']['security_type_eligible'] == '0'
    assert value['financial_sessions_advanced'] == 0 and value['financial_authority'] is value['input_adopted'] is False
    assert (cp, scope, natives, rows, extra) == before


@pytest.mark.parametrize('change', ['older', 'sessions', 'stale', 'missing', 'unresolved', 'native', 'held', 'undeclared', 'future'])
def test_pending_scope_refuses_any_other_native_or_parent_state(change):
    cp, scope, natives, rows, extra = pending_fixture(); w = cp['run']['state']['wealth_core']; sid = natives[0]['security_id']
    if change == 'older': cp['source_cursor'] = scope['parent_cursor'] = '2022-07-22'
    elif change == 'sessions': w['terminal_pending_sessions'][sid] = 1
    elif change == 'stale': w['terminal_pending_terms'][sid]['stale_at_event'] = 1
    elif change == 'missing': w['terminal_pending_terms'] = {}
    elif change == 'unresolved': w['unresolved_terminals'][sid] = {'unknown': True}
    elif change == 'native': w['terminal_pending_terms'][sid]['terms']['cash_per_share'] = 203.
    elif change == 'held': w['episodes'] = {}
    elif change == 'undeclared': scope['terms'][0].pop('pending_at_parent')
    else: cp['source_cursor'] = scope['parent_cursor'] = '2022-06-30'
    with pytest.raises(ValueError): f.witness_payload(cp, 'P04', scope, natives, rows, extra)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'extra', 'sid', 'ticker', 'price', 'issuer', 'eligibility', 'role'])
def test_additional_rows_require_exact_full_digest_and_own_parent_role(change):
    cp, scope, natives, rows, extra = pending_fixture()
    if change == 'missing': extra = []
    elif change == 'duplicate': extra.append(deepcopy(extra[0]))
    elif change == 'extra': extra.append(dict(extra[0], security_id='other'))
    elif change == 'sid': extra[0]['security_id'] = 'other'
    elif change == 'ticker': extra[0]['ticker'] = 'OTHER'
    elif change == 'price': extra[0]['raw_open'] = '123.46'
    elif change == 'issuer': extra[0]['issuer_id'] = 'UPGRADED'
    elif change == 'eligibility': extra[0]['security_type_eligible'] = '1'
    else: cp['run']['state']['wealth_core']['episodes']['8'] = dict(slot_id=8, ticker='CHILD', security_id='child', current_shares=2, entry_date='2022-07-01')
    with pytest.raises(ValueError): f.witness_payload(cp, 'P04', scope, natives, rows, extra)


@pytest.mark.parametrize('change', ['schema', 'pending', 'row', 'authority'])
def test_pending_payload_reconstruction_refuses_downgrade_or_tampering(change):
    cp, scope, natives, rows, extra = pending_fixture(); value = f.witness_payload(cp, 'P04', scope, natives, rows, extra)
    if change == 'schema': value['schema'] = f.SOURCE_WITNESS_SCHEMA
    elif change == 'pending': value['terms'][0]['pending_context']['pending_sessions'] = 1
    elif change == 'row': value['additional_rows'][0]['source_row']['raw_open'] = '124'
    else: value['financial_authority'] = True
    with pytest.raises(ValueError): f.validate_witness_capture(value, spec(cp), scope)


def test_pending_parent_guard_removal_falsifier():
    cp, scope, natives, rows, extra = pending_fixture(); term = scope['terms'][0]
    pending = dict(term['pending_at_parent'], pending_sessions=1)
    with pytest.raises(ValueError): f.source_terms(scope, natives, rows, [term['parent_positions']], [pending])
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'source_terms')
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(a, ast.Constant) and a.value == 'SOURCE_WITNESS_ONLY_EXACT_OWN_PENDING_NATIVE_AT_PARENT' for a in node.value.args):
                self.count += 1; return ast.Pass()
            return self.generic_visit(node)
    remove = Remove(); fn = remove.visit(fn); assert remove.count == 1
    ns = dict(vars(f)); exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-pending-parent-guard>', 'exec'), ns)
    assert ns['source_terms'](scope, natives, rows, [term['parent_positions']], [pending])[0]['pending_context']['pending_sessions'] == 1


def test_additional_row_digest_guard_removal_falsifier():
    _, scope, _, _, extra = pending_fixture(); extra[0]['raw_open'] = '123.46'
    with pytest.raises(ValueError): f.additional_source_rows(scope, extra, [[]])
    fn = next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'additional_source_rows')
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(a, ast.Constant) and a.value == 'SOURCE_WITNESS_UNMODIFIED_ADDITIONAL_ROW_AND_PARENT_ROLE' for a in node.value.args):
                self.count += 1; return ast.Pass()
            return self.generic_visit(node)
    remove = Remove(); fn = remove.visit(fn); assert remove.count == 1
    ns = dict(vars(f)); exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-additional-row-digest>', 'exec'), ns)
    assert ns['additional_source_rows'](scope, extra, [[]])[0]['source_row']['raw_open'] == '123.46'


def test_hosted_pending_capture_scans_one_year_once_for_both_rows(tmp_path, monkeypatch):
    cp, scope, natives, rows, extra = pending_fixture(); calls = []
    Native = make_dataclass('Native', [(k, object) for k in natives[0]])
    actions = SimpleNamespace(terminal={natives[0]['session']: (Native(**natives[0]),)})
    def scan(archive, name): calls.append(name); yield from (rows + extra)
    module = ModuleType('research.pooled_input_support'); module.inputs = SimpleNamespace(load_actions=lambda path: actions, _archive_rows=scan)
    monkeypatch.setitem(sys.modules, module.__name__, module); monkeypatch.setattr(f, 'hosted', lambda: None)
    monkeypatch.setattr(f.zipfile, 'ZipFile', lambda path: nullcontext(object()))
    before = deepcopy(cp); result = f.capture_source_witnesses(cp, tmp_path, 'P04', scope)
    assert cp == before and calls == ['observations-2022.csv.gz']
    assert len(result['terms']) == len(result['additional_rows']) == 1


def test_fresh_root_has_only_own_origin_continuation_authority():
    root = p.root_spec('P00'); a = root['root_admission']
    assert root['archive_format'] == p.FRESH_FORMAT and root['measured_closes'] == 169
    assert a['initial_empty_origin_verified'] is True and a['initial_formation_records'] == 126
    assert a['parent_root_admission_sha256'] is None and a['historical_p00_state_or_returns_reused'] is False
    assert a['financial_continuation_authorized'] is True and a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is False
    assert root['financial_authority'] is root['financial_predecessor_admitted'] is False
    p.validate_root_spec(root)
