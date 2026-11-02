"""Inert source, metadata and refusal tests; no local financial execution."""
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import json
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0, Fence())
import system_campaign_unconsumed_cash_parent as parent
import system_campaign_p02_unconsumed_cash_job as job
import system_campaign_unconsumed_cash_diagnostics as diagnostics
import system_campaign_pxd_financial_body as body
from full_system_benchmark import need


def spec():
    return json.loads((HERE/parent.SPEC).read_bytes())


def literals(filename, name):
    node, = [n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.Assign)
             and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
    return ast.literal_eval(node.value)


def test_actual_financial_artifact_and_complete_unchanged_prefix_proof():
    value=spec(); assert parent.scope(value)==value
    result=parent.reference(value)
    assert result['run_id']==41233199484 and result['artifact_id']==13055072366
    assert result['selected_outer_sha256']==value['outer_sha256']
    assert value['full_client_admission']['qualification_copy_used_as_predecessor'] is False
    assert value['inspections']['economic-worker-inspect.json']['exit_code']==1
    assert value['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==0
    assert len(value['repairs'])==37


@pytest.mark.parametrize('key,value', [('outer_sha256','0'*64), ('input_sha256','0'*64),
    ('financial_resume_authorized',False), ('review_only',True), ('measured_closes',1593), ('parent_certificate_rows',1137)])
def test_changed_financial_authority_refuses(key,value):
    changed=spec();changed[key]=value
    with pytest.raises(ValueError): parent.scope(changed)


def test_component_copy_guard_and_actual_removal_falsifier(monkeypatch):
    changed=spec();changed['full_client_admission']['qualification_copy_used_as_predecessor']=True
    monkeypatch.setattr(parent,'SPEC_SHA',hashlib.sha256((json.dumps(changed,sort_keys=True,indent=2)+'\n').encode()).hexdigest())
    with pytest.raises(ValueError,match='FULL_FINANCIAL_PROOF'): parent.scope(changed)
    node, = [n for n in ast.parse(Path(parent.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='scope']
    sites=[i for i,n in enumerate(node.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
           and any(isinstance(a,ast.Constant) and a.value=='UNCONSUMED_CASH_FULL_FINANCIAL_PROOF_AND_EXACT_ADOPTION_EQUIVALENCE'
                   for a in n.value.args)]
    assert len(sites)==1;node.body[sites[0]]=ast.Pass();namespace=dict(vars(parent))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<actual-component-copy-guard-removed>','exec'),namespace)
    assert namespace['scope'](changed)==changed


def test_actual_bodies_compile_and_canonical_call_is_unchanged():
    file='system_campaign_p02_unconsumed_cash_run.py'
    economic=body.tree('system_campaign_p02_q4_cash_run.py','economic',literals(file,'ECONOMIC'),
                       insert_after='actual_packets_and_own_cash_gate')
    review=body.tree('system_campaign_p02_q4_cash_run.py','review',literals(file,'REVIEW'),
                     keywords=literals(file,'REVIEW_KEYS'))
    actualjob=body.tree('system_campaign_p02_close_job.py','main',job.JOB_SITES,
                        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2})
    for node in (economic,review,actualjob): compile(node,'<not-executed>','exec')
    old, = [n for n in ast.parse((HERE/'system_campaign_p02_q4_cash_run.py').read_bytes()).body
            if isinstance(n,ast.FunctionDef) and n.name=='economic']
    calls=lambda t:[ast.dump(n) for n in ast.walk(t) if isinstance(n,ast.Call)
                    and any(isinstance(v,ast.Attribute) and ast.unparse(v)=='backtest.main' for v in n.args)]
    assert calls(old)==calls(economic)
    assert ast.unparse(economic).count('preserve_all_checkpoints(old, out)')==1
    assert 'all37_old_descriptors_preserved=True' in ast.unparse(review)
    assert 'all_eight_original_model_semantics_unchanged=True' in ast.unparse(review)
    text=(HERE/file).read_text()
    assert 'with retained_closing(root, cp) as closing, materialized(codec, root, descriptor, schema=PXD)' in text
    assert 'with retained_scopes(old, parent, out)' in text
    assert 'with retained_scopes(root, cp, out)' in text
    assert 'cash_boundary(root, old, request)' in text


def catalog_validator():
    filename='system_campaign_unconsumed_cash_facts.py'
    catalog=json.loads((HERE/literals(filename,'CATALOG')).read_bytes())
    vanilla, = [n for n in ast.parse((HERE/'system_campaign_cash_calendar.py').read_bytes()).body
                if isinstance(n,ast.FunctionDef) and n.name=='validate_term']
    scope=dict(need=need,math=math,PREOPEN='CONFIRMED_PREOPEN_COMPLETION',NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[vanilla],type_ignores=[])),'<pure-cash-term>','exec'),scope)
    node, = [n for n in ast.parse((HERE/filename).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
    namespace=dict(need=need,Path=Path,sha=lambda b:hashlib.sha256(b).hexdigest(),
        STEM=catalog['commitment_group']['reference_stem'],CATALOG=literals(filename,'CATALOG'),EXPECTED=literals(filename,'EXPECTED'),
        original=SimpleNamespace(original=SimpleNamespace(__file__=str(HERE/'system_campaign_cash_calendar.py'),
            validate_term=scope['validate_term'],PREOPEN=scope['PREOPEN'])))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<pure-cash-catalog>','exec'),namespace)
    return catalog,namespace['validate']


def test_exact_five_unconsumed_facts_and_complete_provider_preimages():
    catalog,validate=catalog_validator(); assert validate(catalog)==catalog
    assert {t['ticker'] for t in catalog['terms']}=={'ALPN','SWAV','DCPH','EVBG','PRFT'}
    assert all(len(t['provider_rows_proof']['selected_row_sha256'])==3 for t in catalog['terms'])
    assert all(t['native_session']>'2024-04-30' for t in catalog['terms'])


@pytest.mark.parametrize('kind',['cash','consumed','suspension_date','incomplete_provider','wire'])
def test_changed_fact_or_old_summary_refuses(kind):
    value,validate=catalog_validator();term=value['terms'][0]
    if kind=='cash': term['added']['cash_per_share']=64.
    elif kind=='consumed': term['native_session']='2024-04-30'
    elif kind=='suspension_date': term['added']['session']='2024-05-21'
    elif kind=='incomplete_provider': term['provider_rows_proof']['selected_row_sha256'].pop()
    else: value['excluded_pending_events']=[]
    with pytest.raises(ValueError): validate(value)


def registry_class():
    source=ast.parse((HERE/'system_campaign_unconsumed_cash_context.py').read_bytes())
    node, = [n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='CashRegistry']
    new=json.loads((HERE/'system-campaign-unconsumed2024-cash-registry-extension.json').read_bytes())['groups'][0]
    registry=SimpleNamespace(registrations=lambda driver=None:[])
    class Prior:
        duplicate=False
        def __init__(self,driver): self.driver=driver
        def registrations(self,driver):
            return [dict(reference_stem='already-admitted/1/')]+([deepcopy(new)] if self.duplicate else [])
        def __enter__(self):
            self.saved=registry.registrations;registry.registrations=self.registrations;return self
        def __exit__(self,*args): registry.registrations=self.saved
    namespace=dict(PriorRegistry=Prior,registry=registry,need=need,Path=Path,json=json,re=__import__('re'),
        deepcopy=deepcopy,sha=lambda b:hashlib.sha256(b).hexdigest(),FILE='system-campaign-unconsumed2024-cash-registry-extension.json',
        STEM=new['reference_stem'])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<actual-registry-metadata-no-financial-code>','exec'),namespace)
    return namespace,Prior,registry,node


def test_registry_appends_and_restores_after_exception():
    namespace,_,registry,_=registry_class();saved=registry.registrations
    value=namespace['CashRegistry'](HERE)
    assert value.registrations(HERE)[0]==dict(reference_stem='already-admitted/1/')
    with pytest.raises(RuntimeError):
        with value:
            assert registry.registrations==value.registrations
            raise RuntimeError('synthetic caller failure')
    assert registry.registrations is saved


def test_registry_override_guard_and_actual_removal_falsifier():
    namespace,prior,_,node=registry_class();prior.duplicate=True
    with pytest.raises(ValueError,match='NO_EXISTING_REGISTRY_OVERRIDE'): namespace['CashRegistry'](HERE)
    method, = [n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='registrations']
    sites=[i for i,n in enumerate(method.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
           and any(isinstance(a,ast.Constant) and a.value=='UNCONSUMED_CASH_NO_EXISTING_REGISTRY_OVERRIDE' for a in n.value.args)]
    assert len(sites)==1;method.body[sites[0]]=ast.Pass()
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<actual-registry-override-guard-removed>','exec'),namespace)
    assert len(namespace['CashRegistry'](HERE).registrations(HERE))==3


def inspection():
    mounts=[dict(Type='bind',Destination=name,RW=name=='/out') for name in ('/variant','/frozen','/driver','/out','/old')]
    return dict(Name='/capital-system-factual-p02-worker-123-1',Id='a'*64,
        Image='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        State=dict(Running=False,OOMKilled=False,ExitCode=1),
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            ReadonlyRootfs=True,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),Mounts=mounts,
        Config=dict(WorkingDir='/variant',Env=[],Cmd=['-B','-u','/driver/system_campaign_p02_unconsumed_cash_run.py',
            '--mode','economic','--spec','/out/spec.json','--request','/driver/'+job.REQUEST]))


def test_actual_new_stop_entrypoint_and_unknown_refusal():
    value=inspection()
    diagnostics.stopped(value,dict(stopped=True,oom_killed=False,exit_code=1),'worker','123',job.REQUEST)
    for key in ('running','old_entry','network'):
        bad=deepcopy(value)
        if key=='running': bad['State']['Running']=True
        elif key=='network': bad['HostConfig']['NetworkMode']='bridge'
        else: bad['Config']['Cmd'][2]='/driver/system_campaign_p02_pxd_run.py'
        with pytest.raises(ValueError):
            diagnostics.stopped(bad,dict(stopped=True,oom_killed=False,exit_code=1),'worker','123',job.REQUEST)


def test_actual_job_receipt_fields_compile_without_running_job(monkeypatch):
    captured=[]
    def compile_only(filename,name,replacements,namespace,**kwargs):
        node=body.tree(filename,name,replacements,**kwargs);compile(node,'<not-executed>','exec');captured.append(node)
        return lambda args:'COMPILED_ONLY'
    monkeypatch.setattr(job,'function',compile_only)
    assert job.main(None)=='COMPILED_ONLY'
    text=ast.unparse(captured[0]);assert 'retained_typed_models=8' in text
    assert 'qualification_copy_used_as_predecessor=False' in text


def test_all_actual_admitted_source_bytes_are_unchanged():
    value=job.expected_request();old=json.loads((HERE/'system-campaign-p02-pxd-request.json').read_bytes())
    assert len(job.SOURCES)==len(set(job.SOURCES))==297
    assert all(value['sources'][name]==expected for name,expected in old['sources'].items())
    assert value['parent_certificate_rows']==1138 and value['concurrent_candidate_limit']==1
    assert value['financial_wait_seconds']==12600 and value['review_wait_seconds']==2700


def test_actual_metadata_closure_in_fresh_locked_process():
    code="""import sys
sys.path.insert(0,sys.argv[1])
from system_campaign_unconsumed_cash_import_probe import qualify
from system_campaign_p02_unconsumed_cash_job import expected_request
r=qualify(expected_request())
assert r['actual_financial_runtime_imports'] is False
assert not any(n=='numpy' or n.startswith('numpy.') or n=='pandas' or n.startswith('pandas.') for n in sys.modules)
print(r['status'])
"""
    result=subprocess.run([sys.executable,'-B','-c',code,str(HERE)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='UNCONSUMED_CASH_METADATA_AND_EXACT_REQUEST_QUALIFIED'
