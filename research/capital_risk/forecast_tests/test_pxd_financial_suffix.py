"""Inert admission/source/stop tests; never execute a financial runtime locally."""
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import json
from pathlib import Path
import subprocess
import sys

import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):
            raise ImportError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
        return None


sys.meta_path.insert(0,Fence())
import system_campaign_pxd_financial_parent as parent
import system_campaign_pxd_financial_body as body
from system_campaign_p02_pxd_job import expected_request,JOB_SITES
import system_campaign_pxd_financial_diagnostics as diagnostics


def spec():
    return json.loads((HERE/'system-campaign-p02-pxd-predecessor.json').read_bytes())


def test_exact_separate_authorities_and_original_failed_outcomes():
    value=spec();original,corrected,qualified=parent.scope(value)
    assert original['review_only'] is True and original['financial_resume_authorized'] is False
    assert corrected['financial_resume_authorized'] is False
    assert qualified['financial_predecessor_authorized'] is False
    assert value['financial_resume_authorized'] is True
    result=parent.reference(value)
    assert result['original_failed_reviewer_relabelled'] is False
    assert result['qualification_copy_is_predecessor'] is False
    assert value['outer_sha256']==qualified['original_checkpoint_sha256']
    assert value['outer_sha256']!=qualified['qualification_checkpoint_sha256']


@pytest.mark.parametrize('key,value',[
    ('outer_sha256','0'*64),('inner_sha256','0'*64),('financial_resume_authorized',False),
    ('original_reviewer_exit_code',0),('parent_certificate_rows',1137),('measured_closes',1593),
])
def test_changed_own_boundary_or_relabelled_outcome_refuses(key,value):
    changed=spec();changed[key]=value
    with pytest.raises(ValueError):parent.scope(changed)


def test_financial_alias_guard_and_actual_removal_falsifier(monkeypatch):
    changed=spec();changed['review_aliases']['book/daily.jsonl']=deepcopy(changed['review_aliases']['core-review.json'])
    normalized=(json.dumps(changed,indent=2,sort_keys=True)+'\n').encode()
    monkeypatch.setattr(parent,'SPEC_SHA',hashlib.sha256(normalized).hexdigest())
    with pytest.raises(ValueError,match='ONLY_FIVE_NONFINANCIAL'):parent.scope(changed)
    node,=[n for n in ast.parse(Path(parent.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='scope']
    def keep(n):
        return not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
                    and any(isinstance(v,ast.Constant) and v.value=='PXD_PARENT_ONLY_FIVE_NONFINANCIAL_REVIEW_ALIASES'
                            for v in n.value.args))
    node.body=[n for n in node.body if keep(n)]
    namespace=dict(vars(parent))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<actual-review-alias-guard-removed>','exec'),namespace)
    assert namespace['scope'](changed)[0]['run_id']==41214327942


def test_exact_body_sites_compile_without_financial_execution():
    economic=body.tree('system_campaign_p02_close_run.py','economic',body.ECONOMIC,
                       insert_after='actual_packets_and_own_unheld_close_gate')
    review=body.tree('system_campaign_p02_close_run.py','review',body.REVIEW,keywords=body.REVIEW_KEYWORDS)
    job=body.tree('system_campaign_p02_close_job.py','main',JOB_SITES,
                  expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2})
    for value in (economic,review,job):compile(value,'<not-executed>','exec')
    before,=[n for n in ast.parse((HERE/'system_campaign_p02_close_run.py').read_bytes()).body
             if isinstance(n,ast.FunctionDef) and n.name=='economic']
    calls=lambda tree:[ast.dump(n) for n in ast.walk(tree) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Attribute) and ast.unparse(v)=='backtest.main' for v in n.args)]
    assert calls(before)==calls(economic)
    assert ast.unparse(economic).count('preserve_all_checkpoints(old, out)')==1
    assert 'all36_old_descriptors_preserved=True' in ast.unparse(review)


def test_extra_or_missing_source_site_refuses():
    with pytest.raises(ValueError,match='EVERY_DECLARED_LITERAL'):
        body.tree('system_campaign_p02_close_run.py','economic',{**body.ECONOMIC,'NOT_A_SOURCE_LITERAL':'WRONG'})


def test_actual_job_receipt_additions_compile_without_running_job(monkeypatch):
    import system_campaign_p02_pxd_job as job
    captured=[]
    def compile_only(filename,name,replacements,namespace,**kwargs):
        value=body.tree(filename,name,replacements,**kwargs)
        compile(value,'<actual-job-fields-no-execution>','exec')
        captured.append(value)
        return lambda args:'COMPILED_WITHOUT_JOB_EXECUTION'
    monkeypatch.setattr(job,'function',compile_only)
    assert job.main(None)=='COMPILED_WITHOUT_JOB_EXECUTION'
    text=ast.unparse(captured[0])
    assert 'qualification_copy_used_as_predecessor=False' in text
    assert 'composite_financial_predecessor=True' in text


def test_source_hash_guard_and_removal_falsifier(tmp_path,monkeypatch):
    filename='system_campaign_p02_close_run.py'
    raw=(HERE/filename).read_bytes()+b'\n# inert source mutation\n'
    (tmp_path/filename).write_bytes(raw)
    (tmp_path/'system-campaign-pxd-qualification-request.json').write_bytes(
        (HERE/'system-campaign-pxd-qualification-request.json').read_bytes())
    monkeypatch.setattr(body,'HERE',tmp_path)
    with pytest.raises(ValueError,match='UNCHANGED_ADOPTED_ORCHESTRATOR'):
        body.tree(filename,'economic',body.ECONOMIC)
    node,=[n for n in ast.parse(Path(body.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='tree']
    node.body=[n for n in node.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='PXD_BODY_EXACT_UNCHANGED_ADOPTED_ORCHESTRATOR'
                for a in n.value.args))]
    namespace=dict(vars(body))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<actual-source-hash-guard-removed>','exec'),namespace)
    assert isinstance(namespace['tree'](filename,'economic',body.ECONOMIC),ast.Module)


def inspection():
    run='123';role='worker'
    mounts=[dict(Type='bind',Destination=name,RW=name=='/out')
            for name in ('/variant','/frozen','/driver','/out','/old')]
    return dict(Name='/capital-system-factual-p02-'+role+'-'+run+'-1',Id='a'*64,
        Image='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        State=dict(Running=False,OOMKilled=False,ExitCode=1),
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,
            NanoCpus=2000000000,ReadonlyRootfs=True,PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Mounts=mounts,Config=dict(WorkingDir='/variant',Env=[],Cmd=['-B','-u',
            '/driver/system_campaign_p02_pxd_run.py','--mode','economic','--spec','/out/spec.json',
            '--request','/driver/system-campaign-p02-pxd-request.json']))


def test_same_actual_stop_fences_new_entrypoint():
    diagnostics.stopped(inspection(),dict(stopped=True,oom_killed=False,exit_code=1),
                        'worker','123','system-campaign-p02-pxd-request.json')


@pytest.mark.parametrize('kind',['network','oom','old_entry','writable_source','running'])
def test_changed_or_unknown_stop_refuses(kind):
    value=inspection()
    if kind=='network':value['HostConfig']['NetworkMode']='bridge'
    elif kind=='oom':value['State']['OOMKilled']=True
    elif kind=='old_entry':value['Config']['Cmd'][2]='/driver/system_campaign_p02_close_run.py'
    elif kind=='writable_source':value['Mounts'][0]['RW']=True
    else:value['State']['Running']=True
    with pytest.raises(ValueError):
        diagnostics.stopped(value,dict(stopped=True,oom_killed=False,exit_code=1),
                            'worker','123','system-campaign-p02-pxd-request.json')


def test_uncommitted_checkpoint_is_preserved_outside_active_book():
    raw=(HERE/'system_campaign_p02_pxd_run.py').read_bytes()
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='preserve_all_checkpoints']
    assignment,=[n for n in ast.walk(fn) if isinstance(n,ast.Assign)
                 and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='committed']
    code=compile(ast.Expression(assignment.value),'<inert-prefix-classification>','eval')
    selected=dict(completed=1592,source_cursor='2024-04-30',journals={'daily':{'bytes':100},'watch':{'bytes':20}})
    committed=deepcopy(selected);unsent=deepcopy(selected);unsent['journals']['watch']['bytes']=21
    assert eval(code,dict(cp=committed,selected=selected)) is True
    assert eval(code,dict(cp=unsent,selected=selected)) is False
    unsent=deepcopy(selected);unsent.update(completed=1593,source_cursor='2024-05-01')
    assert eval(code,dict(cp=unsent,selected=selected)) is False


def test_original_cash_boundary_and_all286_source_commitments():
    request=expected_request()
    assert request['retained_cash_original_spec_sha256']==hashlib.sha256(
        (HERE/'system-campaign-p02-q4-cash-predecessor.json').read_bytes()).hexdigest()
    assert len(request['sources'])==286
    old=json.loads((HERE/'system-campaign-pxd-qualification-request.json').read_bytes())
    assert all(request['sources'][name]==value for name,value in old['sources'].items())


def test_actual_locked_dependency_metadata_imports_in_fresh_process():
    code="""import json,sys
sys.path.insert(0,sys.argv[1])
from system_campaign_pxd_financial_import_probe import qualify
from system_campaign_p02_pxd_job import expected_request
r=qualify(expected_request())
assert r['actual_financial_runtime_imports'] is False
assert not any(n=='numpy' or n.startswith('numpy.') or n=='pandas' or n.startswith('pandas.') for n in sys.modules)
print(r['status'])
"""
    result=subprocess.run([sys.executable,'-B','-c',code,str(HERE)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='METADATA_AND_EXACT_PXD_FINANCIAL_REQUEST_QUALIFIED'
