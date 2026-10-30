"""Exact unchanged failed-prefix admission, synthetic metadata only."""
import ast
import hashlib
import json
from pathlib import Path
import pytest
import system_campaign_factual_admit as module
from forecast_tests.test_p02_unadvanced_alder import fixture as original_fixture


def fixture(tmp_path):
    spec,inventory=original_fixture(tmp_path)
    outer='04dbed001c745fa04aaa5a28320911a6a7ac3eb1cbfc2b418a42dadfaa5fcb0a'
    spec.update(receipt_schema='research.system-p02-uncertainty-suffix-receipt/1',unadvanced_receipt_status='STOPPED_P02_UNCERTAINTY_PREFIX_PRESERVED',
        arm='P02',run_id=41086155048,selected_session='2020-02-28',outer_sha256=outer,unadvanced_failure_kind='SPRINT_PACKET_DAY_FIELD')
    for name in spec['unadvanced_prefix_reviews']:
        p=tmp_path/name;v=json.loads(p.read_bytes());v.update(checkpoint_sha256=outer,counts={'formation':126,'daily':543});p.write_text(json.dumps(v))
        spec['unadvanced_prefix_reviews'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
    p=tmp_path/'old-uncertainty-certificate-review.json';p.write_text(json.dumps(dict(status='COMMITTED_PREFIX_INTERVAL_INVARIANT',checkpoint_sha256=outer,
        through='2020-02-28',rows=89,comparisons=165,financial_path_invariant_over_declared_sensor_interval=True)))
    spec['unadvanced_certificate_review_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    return spec,inventory


def test_exact_no_advance_and_actual_guard_removal(tmp_path):
    spec,inventory=fixture(tmp_path);module.prove_unadvanced(spec,inventory,tmp_path)
    bad={**inventory,'book/daily.jsonl':{'bytes':12,'sha256':'b'*64}}
    with pytest.raises(ValueError,match='NO_FINANCIAL_ADVANCEMENT'):module.prove_unadvanced(spec,bad,tmp_path)
    tree=ast.parse(Path(module.__file__).read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prove_unadvanced_sprint_packet')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='SPRINT_PACKET_FAILURE_NO_FINANCIAL_ADVANCEMENT' for x in ast.walk(n))]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-journal-guard-removed>','exec'),scope)
    scope[node.name](spec,bad,tmp_path)


@pytest.mark.parametrize('name',('book/status.json','book/result.json','sprint-input-qualification.json','recovered-tail-proof.json','acceleration-proof.json'))
def test_any_financial_entry_cannot_be_treated_unadvanced(tmp_path,name):
    spec,inventory=fixture(tmp_path);inventory[name]={'bytes':0,'sha256':'f'*64}
    with pytest.raises(ValueError,match='BEFORE_FINANCIAL_ENTRY'):module.prove_unadvanced(spec,inventory,tmp_path)


def test_exact_failure_cannot_be_substituted_or_old_interval_unproved(tmp_path):
    spec,inventory=fixture(tmp_path);p=tmp_path/'old-uncertainty-certificate-review.json';v=json.loads(p.read_bytes());v['financial_path_invariant_over_declared_sensor_interval']=False;p.write_text(json.dumps(v))
    spec['unadvanced_certificate_review_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='RETAINED_INTERVAL_PROOF'):module.prove_unadvanced(spec,inventory,tmp_path)


def basis_fixture(tmp_path):
    spec,inventory=fixture(tmp_path)
    spec.update(run_id=41089567127,unadvanced_failure_kind='SPRINT_RETAINED_BASIS_FILE')
    raw=b"FileNotFoundError: [Errno 2] No such file or directory: '/old/common-factual-and-uncertainty-basis.json'\n"
    (tmp_path/'economic-worker.log').write_bytes(raw)
    spec['unadvanced_worker_log_sha256']=hashlib.sha256(raw).hexdigest()
    return spec,inventory


def test_exact_missing_support_failure_admitted_only_without_advancement(tmp_path):
    spec,inventory=basis_fixture(tmp_path);module.prove_unadvanced(spec,inventory,tmp_path)
    bad={**inventory,'book/daily.jsonl':{'bytes':12,'sha256':'b'*64}}
    with pytest.raises(ValueError,match='NO_FINANCIAL_ADVANCEMENT'):module.prove_unadvanced(spec,bad,tmp_path)


@pytest.mark.parametrize('name',('common-factual-and-uncertainty-basis.json',
    'uncertainty-certificate.jsonl','correlation-inputs.jsonl.gz','sprint-input-overlay.json'))
def test_missing_support_failure_cannot_hide_new_inputs_or_recovered_evidence(tmp_path,name):
    spec,inventory=basis_fixture(tmp_path);inventory[name]={'bytes':0,'sha256':'f'*64}
    with pytest.raises(ValueError,match='EXACT_MISSING_SUPPORT'):module.prove_unadvanced(spec,inventory,tmp_path)
