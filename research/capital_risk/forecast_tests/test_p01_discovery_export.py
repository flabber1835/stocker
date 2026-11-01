"""Actual synthetic export roundtrip and stop-receipt failure behavior only."""
import ast,json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_p01_discovery_export as export
from system_campaign_pxd_financial_body import function
import system_campaign_pxd_financial_body as body

@pytest.fixture
def scoped(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='a'*64)))
    return request

def receipt():
    return dict(arm='P01',stage=export.STAGE,financial_authority=False,account_performance_computed=False,
        production_contacted=False,status='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW',
        worker=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None))

def test_actual_p01_ciphertext_authentication_manifest_marker_roundtrip(tmp_path,scoped):
    proof=export.qualify_export(tmp_path/'probe',scoped)
    assert proof['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']
    assert (tmp_path/'probe/probe.tar.crseal').exists()

def test_prior_actual_stage_only_adapter_reproduces_p01_export_refusal(tmp_path,scoped):
    source=tmp_path/'source';source.mkdir();(source/'marker.txt').write_bytes(export.MARKER)
    old=function('system_campaign_evidence_export.py','seal',
        {'campaign-factual-suffix':export.STAGE},vars(export.original))
    with pytest.raises(ValueError,match='RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE'):
        old(source,tmp_path/'old.crseal',b'x'*32,scoped,'P01',stage=export.STAGE,protocol_sha256='a'*64)
    assert not (tmp_path/'old.crseal').exists()

def test_real_probe_refuses_prior_broken_adapter_before_long_work(tmp_path,scoped,monkeypatch):
    old=function('system_campaign_evidence_export.py','seal',
        {'campaign-factual-suffix':export.STAGE},vars(export.original))
    monkeypatch.setattr(export,'adapter',lambda:old)
    with pytest.raises(ValueError,match='RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE'):
        export.qualify_export(tmp_path/'probe',scoped)

@pytest.mark.parametrize('arm,stage',[('P02',export.STAGE),('P01','campaign-factual-suffix')])
def test_current_actual_adapter_rejects_other_arm_or_stage(tmp_path,scoped,arm,stage):
    with pytest.raises(ValueError,match='P01_DISCOVERY_EXACT_EXPORT_SCOPE'):
        export.adapter()(tmp_path,tmp_path/'bad.crseal',b'x'*32,scoped,arm,stage=stage,protocol_sha256='a'*64)

def test_changed_original_exporter_refuses(tmp_path,scoped,monkeypatch):
    root=Path(export.__file__).parent
    for name in ('system-campaign-pxd-qualification-request.json','system_campaign_evidence_export.py'):
        (tmp_path/name).write_bytes((root/name).read_bytes()+(b'\n' if name.endswith('.py') else b''))
    monkeypatch.setattr(body,'HERE',tmp_path)
    with pytest.raises(ValueError,match='PXD_BODY_EXACT_UNCHANGED_ADOPTED_ORCHESTRATOR'):export.adapter()

def test_stop_metadata_is_durable_before_and_after_export_error(tmp_path,scoped,monkeypatch):
    value=receipt();path=tmp_path/'public.json'
    def fail(*args):
        assert json.loads(path.read_bytes())['worker']==value['worker']
        raise ValueError('REFUSED_SYNTHETIC_EXPORT')
    monkeypatch.setattr(export,'sealed',fail)
    result=export.finish_export(value,tmp_path/'private',path,b'x'*32,scoped,known=True)
    saved=json.loads(path.read_bytes());assert saved==result
    assert saved['status']=='KNOWN_STOP_EXPORT_REFUSED_NO_PLAINTEXT_FALLBACK'
    assert saved['pre_export_status']=='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW'
    assert saved['worker']['stopped'] and not saved['encrypted_output_exported']
    assert saved['export_error']==dict(type='ValueError',code='REFUSED_SYNTHETIC_EXPORT')
    assert 'encrypted_output' not in saved and not list(tmp_path.glob('*.tar*'))

def test_unknown_stop_never_reads_or_seals_private_root(tmp_path,scoped,monkeypatch):
    value=receipt();value.pop('worker');value['status']='DISCOVERY_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    monkeypatch.setattr(export,'sealed',lambda *a:(_ for _ in ()).throw(AssertionError('Forbidden snapshot')))
    result=export.finish_export(value,tmp_path/'DOES_NOT_EXIST',tmp_path/'public.json',b'x'*32,scoped,known=False)
    assert not result['encrypted_output_exported'] and 'encrypted_output' not in result

@pytest.mark.parametrize('change',[{'nav':'SYNTHETIC_NOT_FINANCE'},{'status':{'state':'SYNTHETIC_NOT_FINANCE'}}])
def test_public_receipt_rejects_extra_or_nested_payload(tmp_path,change):
    value=receipt();value.update(change)
    with pytest.raises(ValueError,match='P01_PUBLIC_'):export.write_public_receipt(tmp_path/'public.json',value)
    assert not (tmp_path/'public.json').exists()

def test_actual_public_field_guard_removal_admits_extra_scalar(tmp_path):
    value=receipt();value['nav']='SYNTHETIC_NOT_FINANCE'
    fn,=[n for n in ast.parse(Path(export.__file__).read_bytes()).body
          if isinstance(n,ast.FunctionDef) and n.name=='write_public_receipt']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and any(isinstance(x,ast.Constant)
        and x.value=='P01_PUBLIC_RECEIPT_ONLY_DECLARED_NONFINANCIAL_FIELDS' for x in ast.walk(n)))]
    namespace=dict(vars(export));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-public-field-guard-removed>','exec'),namespace)
    namespace['write_public_receipt'](tmp_path/'public.json',value)
    assert json.loads((tmp_path/'public.json').read_bytes())['nav']=='SYNTHETIC_NOT_FINANCE'
