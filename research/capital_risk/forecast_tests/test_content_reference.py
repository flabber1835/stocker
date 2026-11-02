"""Exact metadata retention only; no hosted admission or financial replay."""
import ast
from copy import deepcopy
from pathlib import Path

import pytest

import system_campaign_content_reference as module


def fixture():
    value = dict(arm='P02', stage='campaign-factual-suffix',
        receipt_schema='research.system-p02-uncertainty-suffix-receipt/1',
        run_id=123, head='1'*40, artifact_id=456, zip_bytes=1627012590,
        zip_sha256='2'*64, receipt_sha256='3'*64,
        encrypted_output=dict(sha256='4'*64, manifest_sha256='5'*64),
        outer_sha256='6'*64, inner_sha256='7'*64, state_sha256='8'*64, input_sha256='9'*64,
        selected_file=dict(sha256='a'*64), source_binding_sha256='b'*64,
        review_sha256='c'*64, interval_review_sha256='d'*64,
        journals={'daily': {'bytes': 17, 'prefix_sha256': 'e'*64}},
        repairs=[{'sha256': 'f'*64}], base={'retained': 'exact'},
        inspections={'economic-worker-inspect.json': {'exit_code': 1},
                     'independent-review-stop/worker-inspect.json': {'exit_code': 0}})
    value['private_content_archive'] = dict(schema='research.private-parent-content-archive/1',
        run_id=123, head='1'*40, artifact_id=456, selected_outer_sha256='6'*64,
        complete_member_index_sha256='a'*64, independent_review_sha256='b'*64,
        inventory_members=180, all_cipher_gcm_inventory_verified=True,
        all_unique_content_and_older_opaque_evidence_verified=True,
        raw_outer_transport_zip_copy_claimed=False)
    return value


def test_reference_binds_all_evidence_without_claiming_another_zip_copy():
    spec = fixture(); before = deepcopy(spec)
    value = module.reference(spec)
    assert spec == before and value['schema'] == module.SCHEMA
    assert value['parent_spec_sha256'] == module.digest(spec)
    assert value['complete_journals_sha256'] == module.digest(spec['journals'])
    assert not value['duplicate_parent_transport_bytes_included']
    assert not value['new_physical_parent_zip_copy_claimed']
    assert not value['archive']['raw_outer_transport_zip_copy_claimed']


@pytest.mark.parametrize('field', ['arm', 'review_refusal', 'wrong_archive', 'missing_inventory',
                                 'unknown_worker', 'failed_review', 'boolean_exit', 'transport_claim'])
def test_unreviewed_or_foreign_content_cannot_be_referenced(field):
    spec = fixture()
    if field == 'arm': spec['arm'] = 'P03'
    elif field == 'review_refusal': spec['review_refusal'] = 'unresolved'
    elif field == 'wrong_archive': spec['private_content_archive']['selected_outer_sha256'] = '0'*64
    elif field == 'missing_inventory': spec['private_content_archive']['all_cipher_gcm_inventory_verified'] = False
    elif field == 'unknown_worker': spec['inspections']['economic-worker-inspect.json']['exit_code'] = None
    elif field == 'failed_review': spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code'] = 1
    elif field == 'boolean_exit': spec['inspections']['economic-worker-inspect.json']['exit_code'] = True
    else: spec['private_content_archive']['raw_outer_transport_zip_copy_claimed'] = True
    with pytest.raises(ValueError): module.reference(spec)


def test_any_economic_descriptor_or_prefix_change_changes_reference():
    first = fixture(); before = module.reference(first)
    for key in ('journals', 'repairs', 'base'):
        changed = deepcopy(first)
        changed[key] = {'changed': True}
        after = module.reference(changed)
        assert after['parent_spec_sha256'] != before['parent_spec_sha256']
        expected = {'journals': 'complete_journals_sha256', 'repairs': 'complete_repairs_sha256',
                    'base': 'base_sha256'}[key]
        assert after[expected] != before[expected]


def test_actual_archive_binding_guard_removal_falsifier():
    spec = fixture(); spec['private_content_archive']['selected_outer_sha256'] = '0'*64
    tree = ast.parse(Path(module.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'reference']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant)
                      and a.value == 'CONTENT_REFERENCE_EXACT_PRIVATE_ARCHIVE_AND_SELECTED_PARENT'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-parent-content-binding-guard-removal>', 'exec'), namespace)
    with pytest.raises(ValueError): module.reference(spec)
    assert namespace['reference'](spec)['archive']['selected_outer_sha256'] == '0'*64


def test_export_reference_function_never_deletes_or_rewrites_parent():
    tree = ast.parse(Path(module.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'preserve']
    calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert calls.count('save') == 1 and 'check_context' in calls
    assert not any(v.endswith(('.unlink', '.write_bytes', '.write_text', '.rename')) for v in calls)
    assert not any('copy' in v or 'rmtree' in v for v in calls)
