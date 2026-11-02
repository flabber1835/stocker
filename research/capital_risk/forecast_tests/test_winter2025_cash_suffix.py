"""Inert source/metadata guards only; canonical integration remains hosted."""
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_', 'numpy', 'pandas')):
            raise ImportError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:' + fullname)
        return None


sys.meta_path.insert(0, Fence())
import system_campaign_winter2025_cash_parent as parent
import system_campaign_winter2025_cash_gate as positive
import system_campaign_p02_winter2025_cash_job as job
import system_campaign_pxd_financial_body as body
from full_system_benchmark import need

sha = lambda raw: hashlib.sha256(raw).hexdigest()


def literal(filename, name):
    node, = [n for n in ast.parse((HERE / filename).read_bytes()).body
             if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    return ast.literal_eval(node.value)


def catalog_validator():
    path = HERE / 'system_campaign_winter2025_cash_facts.py'
    tree = ast.parse(path.read_bytes())
    literals = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('CATALOG', 'EXPECTED')}
    catalog = json.loads((HERE / literals['CATALOG']).read_bytes())
    source = ast.parse((HERE / 'system_campaign_cash_calendar.py').read_bytes())
    term, = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'validate_term']
    scope = dict(need=need, math=math, PREOPEN='CONFIRMED_PREOPEN_COMPLETION',
                 NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
    exec(compile(ast.Module(body=[term], type_ignores=[]), '<original-pure-term-contract>', 'exec'), scope)
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'validate']
    scope = dict(need=need, sha=sha, Path=Path, **literals,
        STEM=catalog['commitment_group']['reference_stem'],
        original=SimpleNamespace(original=SimpleNamespace(
            __file__=str(HERE / 'system_campaign_cash_calendar.py'),
            validate_term=scope['validate_term'], PREOPEN='CONFIRMED_PREOPEN_COMPLETION',
            NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<actual-winter-fact-guards>', 'exec'), scope)
    return catalog, scope['validate'], fn, scope


def test_actual_own40_financial_parent_and_original_receipt_binding():
    spec = json.loads((HERE / parent.SPEC).read_bytes())
    assert parent.scope(spec) == spec
    ref = parent.reference(spec)
    assert (ref['run_id'], ref['artifact_id']) == (41250116694, 13061755679)
    assert spec['selected_session'] == '2025-01-31' and spec['measured_closes'] == 1781
    assert len(spec['repairs']) == 40 and spec['parent_certificate_rows'] == 1327
    assert spec['full_client_admission']['all215_actual_members_readback_verified'] is True


@pytest.mark.parametrize('key,value', [('selected_session', '2025-02-14'),
    ('measured_closes', 1791), ('outer_sha256', '0' * 64), ('review_only', True)])
def test_diagnostic_or_forged_predecessor_refuses(key, value):
    spec = json.loads((HERE / parent.SPEC).read_bytes()); spec[key] = value
    with pytest.raises(ValueError):
        parent.scope(spec)


def test_exact_eleven_terms_have_no_public_price_payload_and_keep_physical_roles():
    catalog, validate, _, _ = catalog_validator()
    assert validate(catalog) == catalog
    terms = {v['ticker']: v for v in catalog['terms']}
    assert len(terms['CDMO']['provider_rows_proof']['selected_row_sha256']) == 5
    assert len(terms['ZUO']['provider_rows_proof']['selected_row_sha256']) == 5
    assert terms['EMKR']['actual_completion_date'] == '2025-02-28'
    assert terms['EMKR']['added']['session'] == '2025-03-03'
    assert terms['INFN']['primary_extraction']['all_holders_mandatory_cash'] is False
    for term in terms.values():
        assert not {'raw_open', 'raw_close', 'signal_close', 'reported_volume'} & set(term['identity_witness'])


@pytest.mark.parametrize('mutation', ['amount', 'duplicate', 'provider', 'blanket_infn',
    'elective_scope', 'emkr_preopen', 'emkr_actual_date', 'emkr_convention', 'quote', 'consumed'])
def test_wrong_facts_or_scope_refuse(mutation):
    catalog, validate, _, _ = catalog_validator()
    terms = {v['ticker']: v for v in catalog['terms']}
    if mutation == 'amount': terms['NARI']['added']['cash_per_share'] = 79.
    elif mutation == 'duplicate': catalog['terms'][-1] = deepcopy(catalog['terms'][0])
    elif mutation == 'provider': terms['CDMO']['provider_rows_proof']['selected_row_sha256'].pop()
    elif mutation == 'blanket_infn': terms['INFN']['primary_extraction']['all_holders_mandatory_cash'] = True
    elif mutation == 'elective_scope': terms['INFN']['cash_scope'] = 'ELECT_STOCK'
    elif mutation == 'emkr_preopen': terms['EMKR']['preopen_completion_confirmed'] = True
    elif mutation == 'emkr_actual_date': terms['EMKR']['actual_completion_date'] = '2025-03-03'
    elif mutation == 'emkr_convention': terms['EMKR']['primary_extraction']['retained_next_session_convention_explicit'] = False
    elif mutation == 'quote': catalog['same_day_quote_claims'] = [dict(session='2025-02-19')]
    else: terms['CDMO']['native_session'] = '2025-01-31'
    with pytest.raises(ValueError):
        validate(catalog)


def test_actual_infn_scope_guard_removal_falsifier():
    catalog, validate, fn, scope = catalog_validator()
    term, = [v for v in catalog['terms'] if v['ticker'] == 'INFN']
    term['primary_extraction']['all_holders_mandatory_cash'] = True
    with pytest.raises(ValueError, match='WINTER2025_INFN_NO_BLANKET_CASH_OR_INVENTED_ELECTION'):
        validate(catalog)

    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, node):
            if any(isinstance(x, ast.Constant) and x.value == 'WINTER2025_INFN_NO_BLANKET_CASH_OR_INVENTED_ELECTION'
                   for x in ast.walk(node)):
                self.count += 1
                return ast.Pass()
            return self.generic_visit(node)
    remove = Remove(); modified = remove.visit(deepcopy(fn)); assert remove.count == 1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[modified], type_ignores=[])),
                 '<actual-infn-guard-removed>', 'exec'), scope)
    assert scope['validate'](catalog) == catalog


def test_passive_shape_and_actual_guard_removal_falsifier():
    shape = dict(fields=deepcopy(positive.PASSIVE_FIELDS), api=deepcopy(positive.PASSIVE_API))
    positive.require_passive_shape(shape)
    shape['fields']['HoldingEpisode'].append('affirmative_merger_election')
    with pytest.raises(ValueError, match='WITHOUT_ELECTION_OPERATION'):
        positive.require_passive_shape(shape)
    fn, = [n for n in ast.parse(Path(positive.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'require_passive_shape']
    fn.body = [ast.Pass()]; scope = dict(vars(positive))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-passive-scope-guard-removed>', 'exec'), scope)
    assert scope['require_passive_shape'](shape) is None


def test_complete_request_retains_all321_source_bytes_and_original_boundaries():
    request = job.expected_request()
    prior = json.loads((HERE / 'system-campaign-p02-lbph-cash-request.json').read_bytes())
    assert request == json.loads((HERE / job.REQUEST).read_bytes())
    assert len(request['sources']) == len(job.SOURCES) == len(set(job.SOURCES)) == 333
    assert all(request['sources'][n] == value for n, value in prior['sources'].items())
    for which in ('morf', 'lbph'):
        name = 'system-campaign-p02-' + which + '-cash-predecessor.json'
        assert sha((HERE / name).read_bytes()) == request['retained_' + which + '_original_spec_sha256']


@pytest.mark.parametrize('cash', [3.65, 6.65, 80.])
def test_actual_positive_guard_and_removed_guard_falsifier(cash):
    core = SimpleNamespace(cash=9000. + 10. * cash, episodes={})
    ledger = SimpleNamespace(events=[SimpleNamespace(security_id='S',
        event_type=SimpleNamespace(value='CASH_MERGER'), price=cash,
        cash_delta=10. * cash, shares_delta=-10.)])
    positive.require_positive(core, ledger, 'S', cash); core.cash -= 1
    with pytest.raises(ValueError, match='WINTER2025_CANONICAL_POSITIVE_CASH_REMOVAL'):
        positive.require_positive(core, ledger, 'S', cash)
    fn, = [n for n in ast.parse(Path(positive.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'require_positive']
    fn.body[-1] = ast.Pass(); scope = dict(vars(positive))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-positive-result-guard-removed>', 'exec'), scope)
    assert scope['require_positive'](core, ledger, 'S', cash) is None


def test_actual_emkr_convention_guard_removal_falsifier():
    catalog, validate, fn, scope = catalog_validator()
    term, = [v for v in catalog['terms'] if v['ticker'] == 'EMKR']
    term['primary_extraction']['retained_next_session_convention_explicit'] = False
    with pytest.raises(ValueError, match='WINTER2025_EMKR_ACTUAL_CLOSE_DAY_AND_RETAINED_NEXT_SESSION'):
        validate(catalog)
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, node):
            if any(isinstance(v, ast.Constant) and v.value == 'WINTER2025_EMKR_ACTUAL_CLOSE_DAY_AND_RETAINED_NEXT_SESSION'
                   for v in ast.walk(node)):
                self.count += 1; return ast.Pass()
            return self.generic_visit(node)
    remove = Remove(); changed = remove.visit(deepcopy(fn)); assert remove.count == 1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[])),
                 '<actual-emkr-convention-guard-removed>', 'exec'), scope)
    assert scope['validate'](catalog) == catalog


def test_registry_restore_and_actual_override_guard_removal():
    filename = 'system_campaign_winter2025_cash_context.py'
    cls, = [n for n in ast.parse((HERE / filename).read_bytes()).body
            if isinstance(n, ast.ClassDef) and n.name == 'CashRegistry']
    group = json.loads((HERE / literal(filename, 'FILE')).read_bytes())['groups'][0]
    registry = SimpleNamespace(registrations=lambda driver=None: [])
    class Prior:
        duplicate = False
        def __init__(self, driver): self.driver = driver
        def registrations(self, driver):
            return [dict(reference_stem='prior-lbph/1/')] + ([deepcopy(group)] if self.duplicate else [])
        def __enter__(self): self.saved = registry.registrations; registry.registrations = self.registrations
        def __exit__(self, *args): registry.registrations = self.saved
    scope = dict(PriorRegistry=Prior, registry=registry, need=need, Path=Path, json=json,
        re=re, deepcopy=deepcopy, sha=sha, FILE=literal(filename, 'FILE'), STEM=group['reference_stem'])
    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<actual-winter-registry>', 'exec'), scope)
    saved = registry.registrations
    with scope['CashRegistry'](HERE):
        assert registry.registrations(HERE) == [dict(reference_stem='prior-lbph/1/'), group]
    assert registry.registrations is saved
    Prior.duplicate = True
    with pytest.raises(ValueError, match='WINTER2025_NO_PRIOR_REGISTRATION_OVERRIDE'):
        scope['CashRegistry'](HERE)
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, node):
            if any(isinstance(v, ast.Constant) and v.value == 'WINTER2025_NO_PRIOR_REGISTRATION_OVERRIDE'
                   for v in ast.walk(node)):
                self.count += 1; return ast.Pass()
            return self.generic_visit(node)
    remove = Remove(); changed = remove.visit(deepcopy(cls)); assert remove.count == 1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[])),
                 '<actual-registry-override-guard-removed>', 'exec'), scope)
    assert len(scope['CashRegistry'](HERE).registrations(HERE)) == 3


def test_canonical_call_lifecycle_and_four_original_boundaries():
    filename = 'system_campaign_p02_winter2025_cash_run.py'
    economic = body.tree('system_campaign_p02_q4_cash_run.py', 'economic', literal(filename, 'ECONOMIC'),
                         insert_after='actual_packets_and_own_cash_gate')
    review = body.tree('system_campaign_p02_q4_cash_run.py', 'review', literal(filename, 'REVIEW'),
                       keywords=literal(filename, 'REVIEW_KEYS'))
    actualjob = body.tree('system_campaign_p02_close_job.py', 'main', job.JOB_SITES,
                         expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED': 2})
    for node in (economic, review, actualjob): compile(node, '<actual-inert-bound-body>', 'exec')
    original, = [n for n in ast.parse((HERE / 'system_campaign_p02_q4_cash_run.py').read_bytes()).body
                 if isinstance(n, ast.FunctionDef) and n.name == 'economic']
    calls = lambda node: [ast.dump(n) for n in ast.walk(node) if isinstance(n, ast.Call)
        and any(isinstance(v, ast.Attribute) and ast.unparse(v) == 'backtest.main' for v in n.args)]
    assert calls(original) == calls(economic)
    assert 'all40_old_descriptors_preserved=True' in ast.unparse(review)
    assert ast.unparse(economic).count('preserve_all_checkpoints(old, out)') == 1
    boundaries = literal(filename, 'BOUNDARIES')
    assert boundaries['morf'][-1] == '2024-07-31' and boundaries['lbph'][-1] == '2024-10-31'
    text = (HERE / filename).read_text()
    assert 'retained.cash_boundary(root, old, request)' in text
    assert 'admitted.five_cash_boundary(root, cp, request)' in text
    assert "old / 'spec.json'" not in text


def test_fresh_locked_metadata_closure_without_financial_imports():
    code = "import sys,json;sys.path.insert(0,sys.argv[1]);import system_campaign_winter2025_cash_import_probe as p;r=p.qualify(json.load(open(sys.argv[2])));assert r['source_files']==333;print(r['status'])"
    result = subprocess.run([sys.executable, '-B', '-c', code, str(HERE), str(HERE / job.REQUEST)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'WINTER2025_METADATA_AND_EXACT_REQUEST_QUALIFIED'
