"""Only inert metadata/source/refusal checks; canonical cases run hosted."""
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

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0,Fence())
import system_campaign_morf_cash_parent as parent
import system_campaign_p02_morf_cash_job as job
import system_campaign_pxd_financial_body as body
from full_system_benchmark import need

sha=lambda raw:hashlib.sha256(raw).hexdigest()
digest=lambda obj:sha(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode())


def literal(filename,name):
    node,=[n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.Assign)
           and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
    return ast.literal_eval(node.value)


def spec():return json.loads((HERE/parent.SPEC).read_bytes())


def test_actual_admitted_own38_financial_parent_and_complete_source_index():
    value=spec();assert parent.scope(value)==value
    ref=parent.reference(value)
    assert (ref['run_id'],ref['artifact_id'])==(41239118150,13057615894)
    assert ref['selected_outer_sha256']==value['outer_sha256'] and len(value['repairs'])==38
    request=job.expected_request();old=json.loads((HERE/'system-campaign-p02-unconsumed2024-cash-request.json').read_bytes())
    assert len(request['sources'])==len(job.SOURCES)==309
    assert all(request['sources'][name]==value for name,value in old['sources'].items())
    assert request==json.loads((HERE/job.REQUEST).read_bytes())


@pytest.mark.parametrize('key,value',[('outer_sha256','0'*64),('selected_session','2024-08-15'),
    ('measured_closes',1666),('parent_certificate_rows',1200),('review_only',True),('financial_resume_authorized',False)])
def test_changed_parent_or_diagnostic_cursor_refuses(key,value):
    changed=spec();changed[key]=value
    with pytest.raises(ValueError):parent.scope(changed)


def test_actual_component_copy_guard_removal_falsifier(monkeypatch):
    changed=spec();changed['full_client_admission']['qualification_copy_used_as_predecessor']=True
    monkeypatch.setattr(parent,'SPEC_SHA',sha((json.dumps(changed,sort_keys=True,indent=2)+'\n').encode()))
    with pytest.raises(ValueError,match='MORF_FULL_ACTUAL_ADVANCED_FINANCIAL_PROOF'):parent.scope(changed)
    fn,=[n for n in ast.parse(Path(parent.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='scope']
    hits=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Expr)
          and any(isinstance(v,ast.Constant) and v.value=='MORF_FULL_ACTUAL_ADVANCED_FINANCIAL_PROOF' for v in ast.walk(n))]
    assert len(hits)==1;fn.body[hits[0]]=ast.Pass();ns=dict(vars(parent))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-parent-guard-removed>','exec'),ns)
    assert ns['scope'](changed)==changed


def validator():
    file='system_campaign_morf_cash_facts.py';catalog=json.loads((HERE/literal(file,'CATALOG')).read_bytes())
    pure,=[n for n in ast.parse((HERE/'system_campaign_cash_calendar.py').read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='validate_term']
    ns=dict(need=need,math=math,PREOPEN='CONFIRMED_PREOPEN_COMPLETION',NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
    exec(compile(ast.Module(body=[pure],type_ignores=[]),'<original-pure-cash-term-validation>','exec'),ns)
    fn,=[n for n in ast.parse((HERE/file).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
    ns=dict(need=need,sha=sha,Path=Path,__file__=str(HERE/file),SID='977112340201324412',
        STEM=catalog['commitment_group']['reference_stem'],CATALOG=literal(file,'CATALOG'),
        original=SimpleNamespace(original=SimpleNamespace(__file__=str(HERE/'system_campaign_cash_calendar.py'),
            validate_term=ns['validate_term'],PREOPEN='CONFIRMED_PREOPEN_COMPLETION')))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<pure-morf-catalog-guard>','exec'),ns)
    return catalog,ns['validate']


def test_mandatory_cash_actual_preopen_date_and_hash_only_quote_commitment():
    catalog,validate=validator();assert validate(catalog)==catalog
    quote,=catalog['same_day_quote_claims']
    assert not {'raw_open','raw_close','reported_volume','raw_compatible_volume'}&set(quote)
    assert quote['session']=='2024-08-16' and catalog['terms'][0]['last_trading_session']=='2024-08-15'


@pytest.mark.parametrize('kind',['cash','suspension','native','no_quote','provider','context'])
def test_changed_fact_or_false_quote_absence_refuses(kind):
    value,validate=validator();term=value['terms'][0]
    if kind=='cash':term['added']['cash_per_share']=56.
    elif kind=='suspension':term['added']['session']='2024-08-19'
    elif kind=='native':term['native_session']='2024-08-15'
    elif kind=='no_quote':value['same_day_quote_claims']=[]
    elif kind=='provider':term['provider_rows_proof']['selected_row_sha256'].pop()
    else:value['quote_context_sha256']='0'*64
    with pytest.raises(ValueError):validate(value)


def quote_context():
    fn,=[n for n in ast.parse((HERE/'system_campaign_morf_cash_facts.py').read_bytes()).body
           if isinstance(n,ast.ClassDef) and n.name=='RecognitionTap']
    class Original:
        def __init__(self,catalog):
            self.expected={'member':1};self.completed=dict(self.expected)
            self.original=lambda *args:None;self.inputs=SimpleNamespace(_archive_rows=self.original)
    ns=dict(original=SimpleNamespace(RecognitionTap=Original),need=need,digest=digest)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<pure-retained-quote-preimage-check>','exec'),ns)
    row=dict(session='2024-08-16',security_id='977112340201324412',ticker='MORF',issuer_id='SEC_CIK:1679363',raw_close='1',reported_volume='1',tradeable='1')
    witness={k:row[k] for k in ('session','security_id','ticker','issuer_id')};witness['source_observation_sha256']=digest(row)
    obj=ns['RecognitionTap'](dict(same_day_quote_claims=[witness]));obj.found={(row['session'],row['security_id']):row}
    return obj,fn,ns


def test_quote_retention_and_actual_removed_preimage_guard_falsifier():
    obj,node,namespace=quote_context();proof=obj.proof()
    assert len(proof['actual_recognition_quotes'])==1 and proof['quote_absence_claimed'] is False
    obj.found[next(iter(obj.found))]['raw_close']='2'
    with pytest.raises(ValueError,match='MORF_EXACT_FULL_RECOGNITION_QUOTE_PREIMAGE_UNCHANGED'):obj.proof()
    removed=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if any(isinstance(v,ast.Constant) and v.value=='MORF_EXACT_FULL_RECOGNITION_QUOTE_PREIMAGE_UNCHANGED'
                   for v in ast.walk(n)):removed.append(n);return None
            return self.generic_visit(n)
    node=Remove().visit(node);assert len(removed)==1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-quote-guard-removed>','exec'),namespace)
    altered=namespace['RecognitionTap'].__new__(namespace['RecognitionTap']);altered.__dict__.update(obj.__dict__)
    assert altered.proof()['actual_recognition_quotes'][0]['raw_close']=='2'


def test_original_economic_call_and_all_lineage_bodies_compile_unchanged():
    file='system_campaign_p02_morf_cash_run.py'
    economic=body.tree('system_campaign_p02_q4_cash_run.py','economic',literal(file,'ECONOMIC'),insert_after='actual_packets_and_own_cash_gate')
    review=body.tree('system_campaign_p02_q4_cash_run.py','review',literal(file,'REVIEW'),keywords=literal(file,'REVIEW_KEYS'))
    actualjob=body.tree('system_campaign_p02_close_job.py','main',job.JOB_SITES,
                        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2})
    for node in (economic,review,actualjob):compile(node,'<inert-qualified-orchestration>','exec')
    original,=[n for n in ast.parse((HERE/'system_campaign_p02_q4_cash_run.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='economic']
    calls=lambda t:[ast.dump(n) for n in ast.walk(t) if isinstance(n,ast.Call)
                    and any(isinstance(v,ast.Attribute) and ast.unparse(v)=='backtest.main' for v in n.args)]
    assert calls(original)==calls(economic)
    assert ast.unparse(economic).count('preserve_all_checkpoints(old, out)')==1
    assert 'all38_old_descriptors_preserved=True' in ast.unparse(review)
    text=(HERE/file).read_text();assert 'admitted.retained_scopes(old,parent,out)' in text
    assert 'retained_five_cash_boundary(root,old,cp)' in text
    gate=(HERE/'system_campaign_morf_cash_gate.py').read_text()
    assert 'finally:adapter.decide=original_decide' in gate
    assert 'runtime.checkpoint(restored)==cp[\'run\']' in gate


def test_registry_preserves_prior_groups_restores_and_refuses_override():
    filename='system_campaign_morf_cash_context.py'
    node,=[n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='CashRegistry']
    group=json.loads((HERE/literal(filename,'FILE')).read_bytes())['groups'][0]
    registry=SimpleNamespace(registrations=lambda driver=None:[])
    class Prior:
        duplicate=False
        def __init__(self,driver):self.driver=driver
        def registrations(self,driver):
            return [dict(reference_stem='already-admitted/1/')]+([deepcopy(group)] if self.duplicate else [])
        def __enter__(self):self.saved=registry.registrations;registry.registrations=self.registrations;return self
        def __exit__(self,*args):registry.registrations=self.saved
    ns=dict(PriorRegistry=Prior,registry=registry,need=need,Path=Path,json=json,re=re,deepcopy=deepcopy,sha=sha,
        FILE=literal(filename,'FILE'),STEM=group['reference_stem'])
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<pure-exact-morf-registry>','exec'),ns)
    saved=registry.registrations
    with ns['CashRegistry'](HERE):
        actual=registry.registrations(HERE)
        assert actual[0]['reference_stem']=='already-admitted/1/' and actual[1]==group
    assert registry.registrations is saved
    Prior.duplicate=True
    with pytest.raises(ValueError,match='MORF_NO_PRIOR_REGISTRATION_OVERRIDE'):ns['CashRegistry'](HERE)
    removed=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if any(isinstance(v,ast.Constant) and v.value=='MORF_NO_PRIOR_REGISTRATION_OVERRIDE' for v in ast.walk(n)):
                removed.append(n);return None
            return self.generic_visit(n)
    node=Remove().visit(node);assert len(removed)==1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-registry-override-guard-removed>','exec'),ns)
    assert len(ns['CashRegistry'](HERE).registrations(HERE))==3


def test_fresh_minimal_metadata_process_has_no_financial_imports():
    code="import sys,json;sys.path.insert(0,sys.argv[1]);import system_campaign_morf_cash_import_probe as p;r=p.qualify(json.load(open(sys.argv[2])));assert r['source_files']==309;print(r['status'])"
    value=subprocess.run([sys.executable,'-B','-c',code,str(HERE),str(HERE/job.REQUEST)],
                         capture_output=True,text=True,timeout=60)
    assert value.returncode==0,value.stderr
    assert value.stdout.strip()=='MORF_METADATA_AND_EXACT_REQUEST_QUALIFIED'


def test_actual_veto_falsifier_handler_accepts_real_prefixed_error_only():
    source=ast.parse((HERE/'system_campaign_morf_cash_gate.py').read_bytes())
    veto,=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='require_veto']
    ns=dict(need=need);exec(compile(ast.Module(body=[veto],type_ignores=[]),'<pure-actual-veto-requirement>','exec'),ns)
    bad=SimpleNamespace(decision=SimpleNamespace(operations=[],admission_rejections=[]))
    with pytest.raises(ValueError) as actual:ns['require_veto'](bad,'SYNTHETIC')
    assert str(actual.value)=='REFUSED_FULL_SYSTEM_MORF_CANONICAL_ACTUAL_TERMINAL_DAY_ADMISSION_VETO'
    qualifier,=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_quote']
    handler,=[n for n in ast.walk(qualifier) if isinstance(n,ast.ExceptHandler)
        and any(isinstance(v,ast.Constant) and v.value=='MORF_GATE_REMOVED_VETO_ACTUAL_FALSIFIER_REASON' for v in ast.walk(n))]
    body_code=compile(ast.Module(body=handler.body,type_ignores=[]),'<actual-hosted-falsifier-error-handler>','exec')
    exec(body_code,dict(ns,error=actual.value))
    with pytest.raises(ValueError,match='MORF_GATE_REMOVED_VETO_ACTUAL_FALSIFIER_REASON'):
        exec(body_code,dict(ns,error=ValueError('UNEXPECTED_ERROR')))


def test_harness_recovery_bound_to_same_unchanged_prefix_and_actual_guard_removal(monkeypatch):
    changed=deepcopy(job.GATE_RECOVERY);changed['selected_outer_sha256']='0'*64
    monkeypatch.setattr(job,'GATE_RECOVERY',changed)
    with pytest.raises(ValueError,match='MORF_HARNESS_RECOVERY_EXACT_UNADVANCED_OWN38'):job.expected_request()
    fn,=[n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='expected_request']
    hits=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Expr)
          and any(isinstance(v,ast.Constant) and v.value=='MORF_HARNESS_RECOVERY_EXACT_UNADVANCED_OWN38' for v in ast.walk(n))]
    assert len(hits)==1;fn.body[hits[0]]=ast.Pass();ns=dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-harness-parent-guard-removed>','exec'),ns)
    assert ns['expected_request']()['morf_gate_harness_recovery']['selected_outer_sha256']=='0'*64
