"""Targeted inert metadata/falsifier checks; actual canonical cases run hosted."""
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
import system_campaign_lbph_cash_parent as parent
import system_campaign_p02_lbph_cash_job as job
import system_campaign_pxd_financial_body as body
from full_system_benchmark import need

sha=lambda raw:hashlib.sha256(raw).hexdigest()


def literal(filename,name):
    node,=[n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.Assign)
           and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
    return ast.literal_eval(node.value)


def spec():return json.loads((HERE/parent.SPEC).read_bytes())


def test_actual_own39_october_financial_authority_and_unchanged309_sources():
    value=spec();assert parent.scope(value)==value
    ref=parent.reference(value)
    assert (ref['run_id'],ref['artifact_id'])==(41246680594,13060192478)
    assert ref['selected_outer_sha256']==value['outer_sha256'] and len(value['repairs'])==39
    request=job.expected_request();old=json.loads((HERE/'system-campaign-p02-morf-cash-request.json').read_bytes())
    assert len(request['sources'])==len(set(job.SOURCES))==321
    assert all(request['sources'][n]==v for n,v in old['sources'].items())
    assert request==json.loads((HERE/job.REQUEST).read_bytes())
    assert request['parent_certificate_rows']==1266


@pytest.mark.parametrize('key,value',[('outer_sha256','0'*64),('selected_session','2024-11-27'),
    ('measured_closes',1739),('parent_certificate_rows',1285),('review_only',True),('financial_resume_authorized',False)])
def test_diagnostic_or_changed_parent_refuses(key,value):
    changed=spec();changed[key]=value
    with pytest.raises(ValueError):parent.scope(changed)


def test_actual_component_predecessor_guard_is_load_bearing(monkeypatch):
    changed=spec();changed['full_client_admission']['qualification_copy_used_as_predecessor']=True
    monkeypatch.setattr(parent,'SPEC_SHA',sha((json.dumps(changed,sort_keys=True,indent=2)+'\n').encode()))
    with pytest.raises(ValueError,match='LBPH_FULL_ACTUAL_ADVANCED_FINANCIAL_PROOF'):parent.scope(changed)
    node,=[n for n in ast.parse(Path(parent.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='scope']
    hits=[i for i,n in enumerate(node.body) if isinstance(n,ast.Expr)
          and any(isinstance(v,ast.Constant) and v.value=='LBPH_FULL_ACTUAL_ADVANCED_FINANCIAL_PROOF' for v in ast.walk(n))]
    assert len(hits)==1;node.body[hits[0]]=ast.Pass();scope=dict(vars(parent))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-parent-guard-removal>','exec'),scope)
    assert scope['scope'](changed)==changed


def validator():
    filename='system_campaign_lbph_cash_facts.py';catalog=json.loads((HERE/literal(filename,'CATALOG')).read_bytes())
    source=ast.parse((HERE/'system_campaign_cash_calendar.py').read_bytes())
    node,=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='validate_term']
    scope=dict(need=need,math=math,PREOPEN='CONFIRMED_PREOPEN_COMPLETION',NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<original-pure-cash-term-validator>','exec'),scope)
    node,=[n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
    scope=dict(need=need,sha=sha,Path=Path,CATALOG=literal(filename,'CATALOG'),
        STEM=catalog['commitment_group']['reference_stem'],original=SimpleNamespace(original=SimpleNamespace(
            __file__=str(HERE/'system_campaign_cash_calendar.py'),validate_term=scope['validate_term'],PREOPEN='CONFIRMED_PREOPEN_COMPLETION')))
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-lbph-fact-guard>','exec'),scope)
    return catalog,scope['validate']


def test_mandatory_common_date_is_neither_tender_expiry_nor_suspension():
    catalog,validate=validator();assert validate(catalog)==catalog
    term,=catalog['terms'];assert (term['native_session'],term['added']['session'])==('2024-11-29','2024-12-02')
    assert term['added']['cash_per_share']==60. and catalog['same_day_quote_claims']==[]
    assert not {'raw_open','raw_close','signal_close','reported_volume'}&set(term['identity_witness'])


@pytest.mark.parametrize('kind',['cash','tender','suspension','native','provider','quote','mandatory'])
def test_wrong_terms_or_fabricated_recognition_quote_refuse(kind):
    value,validate=validator();term=value['terms'][0]
    if kind=='cash':term['added']['cash_per_share']=59.
    elif kind=='tender':term['added']['session']='2024-11-27'
    elif kind=='suspension':term['added']['session']='2024-12-03'
    elif kind=='native':term['native_session']='2024-11-27'
    elif kind=='provider':term['provider_rows_proof']['selected_row_sha256'].pop()
    elif kind=='quote':value['same_day_quote_claims']=[dict(session='2024-12-02')]
    else:term['mandatory_common_share_completion_confirmed']=False
    with pytest.raises(ValueError):validate(value)


def test_actual_positive_cash_requirement_and_removed_guard_falsifier():
    node,=[n for n in ast.parse((HERE/'system_campaign_lbph_cash_gate.py').read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='require_positive']
    scope=dict(need=need);exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-positive-result-requirement>','exec'),scope)
    core=SimpleNamespace(cash=9600.,episodes={})
    ledger=SimpleNamespace(events=[SimpleNamespace(security_id='S',event_type=SimpleNamespace(value='CASH_MERGER'),
        price=60.,cash_delta=600.,shares_delta=-10.)])
    scope['require_positive'](core,ledger,'S');core.cash=9599.
    with pytest.raises(ValueError,match='LBPH_CANONICAL_POSITIVE_60_CASH_REMOVAL'):scope['require_positive'](core,ledger,'S')
    removed=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,item):
            if any(isinstance(v,ast.Constant) and v.value=='LBPH_CANONICAL_POSITIVE_60_CASH_REMOVAL' for v in ast.walk(item)):
                removed.append(item);return None
            return self.generic_visit(item)
    node=Remove().visit(node);assert len(removed)==1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-positive-guard-removal>','exec'),scope)
    scope['require_positive'](core,ledger,'S')


def test_original_financial_call_lifecycle_and_explicit_three_retained_boundaries():
    filename='system_campaign_p02_lbph_cash_run.py'
    economic=body.tree('system_campaign_p02_q4_cash_run.py','economic',literal(filename,'ECONOMIC'),insert_after='actual_packets_and_own_cash_gate')
    review=body.tree('system_campaign_p02_q4_cash_run.py','review',literal(filename,'REVIEW'),keywords=literal(filename,'REVIEW_KEYS'))
    actualjob=body.tree('system_campaign_p02_close_job.py','main',job.JOB_SITES,
        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2})
    for node in (economic,review,actualjob):compile(node,'<inert-exact-source-bound-body>','exec')
    original,=[n for n in ast.parse((HERE/'system_campaign_p02_q4_cash_run.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='economic']
    calls=lambda node:[ast.dump(n) for n in ast.walk(node) if isinstance(n,ast.Call)
                       and any(isinstance(v,ast.Attribute) and ast.unparse(v)=='backtest.main' for v in n.args)]
    assert calls(original)==calls(economic)
    assert ast.unparse(economic).count('preserve_all_checkpoints(old, out)')==1
    assert 'all39_old_descriptors_preserved=True' in ast.unparse(review)
    text=(HERE/filename).read_text()
    assert 'retained.cash_boundary(root,old,request)' in text
    assert 'five_cash_boundary(root,cp,request)' in text and 'morf_boundary(root,old,cp)' in text
    assert "'2024-04-30'" in text and "'2024-07-31'" in text
    assert 'admitted.retained_five_cash_boundary(root,old,cp)' not in text
    assert 'for name in MORF_GATES:retained.exact_copy(old/name,out/name)' in text


def test_registry_restores_and_actual_override_guard_removal():
    filename='system_campaign_lbph_cash_context.py'
    node,=[n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='CashRegistry']
    group=json.loads((HERE/literal(filename,'FILE')).read_bytes())['groups'][0]
    registry=SimpleNamespace(registrations=lambda driver=None:[])
    class Prior:
        duplicate=False
        def __init__(self,driver):self.driver=driver
        def registrations(self,driver):return [dict(reference_stem='prior-morf/1/')]+([deepcopy(group)] if self.duplicate else [])
        def __enter__(self):self.saved=registry.registrations;registry.registrations=self.registrations;return self
        def __exit__(self,*args):registry.registrations=self.saved
    scope=dict(PriorRegistry=Prior,registry=registry,need=need,Path=Path,json=json,re=re,deepcopy=deepcopy,sha=sha,
        FILE=literal(filename,'FILE'),STEM=group['reference_stem'])
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-ordinary-registry>','exec'),scope)
    saved=registry.registrations
    with scope['CashRegistry'](HERE):assert registry.registrations(HERE)==[dict(reference_stem='prior-morf/1/'),group]
    assert registry.registrations is saved
    Prior.duplicate=True
    with pytest.raises(ValueError,match='LBPH_NO_PRIOR_REGISTRATION_OVERRIDE'):scope['CashRegistry'](HERE)
    removed=[]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,item):
            if any(isinstance(v,ast.Constant) and v.value=='LBPH_NO_PRIOR_REGISTRATION_OVERRIDE' for v in ast.walk(item)):
                removed.append(item);return None
            return self.generic_visit(item)
    node=Remove().visit(node);assert len(removed)==1
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-registration-guard-removal>','exec'),scope)
    assert len(scope['CashRegistry'](HERE).registrations(HERE))==3


def test_fresh_locked_metadata_closure_without_financial_imports():
    code="import sys,json;sys.path.insert(0,sys.argv[1]);import system_campaign_lbph_cash_import_probe as p;r=p.qualify(json.load(open(sys.argv[2])));assert r['source_files']==321;print(r['status'])"
    result=subprocess.run([sys.executable,'-B','-c',code,str(HERE),str(HERE/job.REQUEST)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='LBPH_METADATA_AND_EXACT_REQUEST_QUALIFIED'
