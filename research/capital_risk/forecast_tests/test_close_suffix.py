"""Exact own-prefix orchestration and receipt scope; no runtime execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from forecast_tests.test_content_reference import fixture
from forecast_tests.test_close_admission import without_guard
import system_campaign_close_reference as reference
import system_campaign_normal_reference as normal
import system_campaign_close_facts as facts
import system_campaign_p02_close_job as job


HERE = Path(job.__file__).parent


def test_request_binds_own35_all247_old_sources_and_original_cash_boundary():
    value = job.expected_request();old = job.inherited_request()
    assert value == json.loads((HERE / 'system-campaign-p02-close-request.json').read_bytes())
    assert len(value['sources']) == 258 and {n:value['sources'][n] for n in old['sources']} == old['sources']
    assert facts.contract()['inherited_sources'] == old['sources']
    assert value['retained_cash_original_spec_sha256'] == old['predecessor_sha256']
    spec = json.loads((HERE / value['predecessor_file']).read_bytes())
    assert spec['run_id'] == 41208142260 and spec['selected_session'] == '2023-10-31'
    assert len(spec['repairs']) == 35 and value['parent_certificate_rows'] == 1014
    assert value['parent_content_reference_sha256'] == job.digest(reference.reference(spec))
    for name in ('canonical_controller_sources','ordinary_registry_sha256','q4_cash_catalog_sha256',
                 'q4_cash_registry_extension_sha256','metadata_dependencies_sha256','financial_wait_seconds',
                 'review_wait_seconds','qualified_packet_source_sha256'):
        assert value[name] == old[name]


def test_actual_worker_entrypoint_is_exact_and_rejects_old_driver(monkeypatch):
    expected = dict(Config=dict(Cmd=['-B','-u','/driver/system_campaign_p02_close_run.py',
        '--mode','economic','--spec','/out/spec.json','--request','/driver/system-campaign-p02-close-request.json']))
    monkeypatch.setattr(job,'prior_inspect',lambda *args:expected)
    assert job.inspect('capital-system-factual-p02-worker-1-1') == expected
    expected['Config']['Cmd'][2]='/driver/system_campaign_p02_q4_cash_run.py'
    with pytest.raises(ValueError): job.inspect('capital-system-factual-p02-worker-1-1')


def test_canonical_gate_and_guard_enclose_finance_and_retained_proof_is_not_rebound():
    tree=ast.parse((HERE/'system_campaign_p02_close_run.py').read_bytes())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='economic']
    timing={n.args[0].value:n for n in ast.walk(fn) if isinstance(n,ast.Call)
        and ast.unparse(n.func)=='timing.call' and n.args and isinstance(n.args[0],ast.Constant)}
    gate=timing['actual_packets_and_own_unheld_close_gate'];finance=timing['financial_driver_total']
    assert gate.lineno < finance.lineno
    close,=[n for n in ast.walk(fn) if isinstance(n,ast.With)
        and any(ast.unparse(v.context_expr)=='close_codec' for v in n.items)]
    assert gate in list(ast.walk(close)) and finance in list(ast.walk(close))
    writes=[n for n in ast.walk(fn) if isinstance(n,ast.Assign)
        and any('certificate.proof_model' in ast.unparse(v) for v in n.targets)]
    assert len(writes)==1 and 'model.sha256' in ast.unparse(writes[0])
    assert "bound['session'] == '2023-07-31'" in ast.unparse(fn)
    assert any(isinstance(n,ast.Try) and n.finalbody for n in ast.walk(close))


def test_exact_proven_current_prefix_and_original_q4_cash_scope_both_reviewed():
    tree=ast.parse((HERE/'system_campaign_p02_close_run.py').read_bytes())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review']
    calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call)]
    cash,=[n for n in calls if ast.unparse(n.func)=='timing.call' and n.args
           and isinstance(n.args[0],ast.Constant) and n.args[0].value=='retained_and_new_cash_entitlements']
    assert ast.unparse(cash.args[4])=='cash_parent'
    assert 'review_close' in ast.unparse(fn) and 'require_exact_delta' in ast.unparse(fn)
    assert 'canonical_all_history_financial_review' in ast.unparse(fn)


@pytest.mark.parametrize('schema',sorted(normal.RECEIPTS | {reference.RECEIPT}))
def test_receipt_scope_preserves_full_actual_spec(schema):
    spec=fixture();spec['receipt_schema']=schema;before=deepcopy(spec)
    value=reference.reference(spec)
    assert spec==before and value['parent_spec_sha256']==job.digest(spec)
    if schema in normal.RECEIPTS: assert value==normal.reference(spec)
    else:
        with pytest.raises(ValueError): normal.reference(spec)


@pytest.mark.parametrize('change',['schema','unknown','review','boolean','foreign'])
def test_new_receipt_adapter_preserves_existing_rejections(change):
    spec=fixture();spec['receipt_schema']=reference.RECEIPT
    if change=='schema': spec['receipt_schema']='UNDECLARED'
    elif change=='unknown': spec['inspections']['economic-worker-inspect.json']['exit_code']=None
    elif change=='review': spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']=1
    elif change=='boolean': spec['inspections']['economic-worker-inspect.json']['exit_code']=True
    else: spec['arm']='P01'
    with pytest.raises(ValueError): reference.reference(spec)


def test_actual_source_guard_removal_is_detected(monkeypatch):
    spec=fixture();spec['receipt_schema']=reference.RECEIPT
    monkeypatch.setattr(reference,'SOURCE_SHA','0'*64)
    with pytest.raises(ValueError): reference.reference(spec)
    broken=without_guard(reference,'function','CLOSE_REFERENCE_EXACT_ADOPTED_NORMAL_REFERENCE_SOURCE')
    assert broken('reference',RECEIPTS=normal.RECEIPTS | {reference.RECEIPT})(spec)
