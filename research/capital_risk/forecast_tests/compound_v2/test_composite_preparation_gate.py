"""Pure orchestration falsifiers; no financial imports or financial state."""
import ast
from copy import deepcopy
import hashlib
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PACKAGE=Path(__file__).resolve().parents[2]
CODE=PACKAGE.parent/'research-ci-compatibility-20261103/research/capital_risk'
NAMES={'composite_preparation_receipt','prepare_composite_before_finance','require_composite_preparation'}

class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise AssertionError('NO_CANONICAL_FINANCIAL_IMPORT:'+fullname)

@pytest.fixture(autouse=True)
def imported():
    guard=Fence();sys.meta_path.insert(0,guard);yield;sys.meta_path.remove(guard)

def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def need(value,message):
    if not value:raise ValueError(message)

def source():
    private=PACKAGE/'system_campaign_financial_resume.py'
    return private.read_text() if private.is_file() else (CODE/'system_campaign_financial_resume.py').read_text()

def functions(*,mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',break_guard=None):
    nodes=[deepcopy(n) for n in ast.parse(source()).body if isinstance(n,ast.FunctionDef) and n.name in NAMES]
    assert {n.name for n in nodes}==NAMES
    # Only import bindings are replaced. Full orchestration and guards stay exact.
    for node in nodes:
        body=[]
        for n in node.body:
            if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_compound_dispatch':
                body.append(ast.Assign(targets=[ast.Name(id='selected',ctx=ast.Store())],value=ast.Name(id='selected_stub',ctx=ast.Load())))
            elif isinstance(n,ast.ImportFrom) and n.module=='research.pooled_vacancy_funding':
                body.extend(ast.Assign(targets=[ast.Name(id=a.name,ctx=ast.Store())],value=ast.Name(id=a.name+'_stub',ctx=ast.Load())) for a in n.names)
            else:body.append(n)
        node.body=body
    if break_guard:
        removed=0
        for node in nodes:
            for call in ast.walk(node):
                if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='need' and len(call.args)==2 and isinstance(call.args[1],ast.Constant) and call.args[1].value==break_guard:
                    call.args[0]=ast.Constant(True);removed+=1
        assert removed==1
    scope=dict(Path=Path,json=json,need=need,sha256_file=sha_file,EXECUTION_MODE=mode)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<exact-composite-preparation-orchestration>','exec'),scope)
    return scope

def fixture(tmp_path,scope,*,behavior=None,selected=True):
    # Input identity only: no portfolio, ledger, canonical run or checkpoint bytes.
    cp=dict(sha256='a'*64,source_cursor='2021-04-30',run=dict(checkpoint_sha256='b'*64,input_sha256='c'*64))
    spec=dict(arm='P07',root_admission_sha256='d'*64)
    out=tmp_path/'preflight';out.mkdir(parents=True)
    runtime=SimpleNamespace(advance=lambda *a,**k:'advance')
    backtest=SimpleNamespace(main=lambda *a,**k:'main')
    originals=(backtest.main,runtime.advance)
    module_file=tmp_path/'synthetic-codec.py';module_file.write_text('synthetic input codec\n')
    calls=[]
    module=SimpleNamespace(__file__=str(module_file),OVERLAY='future-financial-overlay.json',QUALIFICATION='compound-input-v2-qualification.json',ORDINARY_QUALIFICATION='compound-v2-ordinary-qualification.json')
    def prepare(parent,folder,arm):
        assert arm==spec['arm'] and folder==out and parent is cp
        calls.append('prepare')
        if behavior=='advance':runtime.advance(None,None)
        if behavior=='main':backtest.main([])
        if behavior=='failure':raise OSError(30,'Read-only filesystem')
        if behavior=='mutate':parent['run']['input_sha256']='0'*64
        if behavior in ('checkpoint','adoption'):
            path=folder/('book' if behavior=='checkpoint' else 'input-adoption')/'checkpoint.json.gz'
            path.parent.mkdir();path.write_bytes(b'synthetic marker; no financial state')
        path=folder/module.OVERLAY;path.write_text('{"synthetic_input":true}\n')
        (folder/module.QUALIFICATION).write_text(json.dumps(dict(passed=True,financial_sessions_advanced=1 if behavior=='qualifier' else 0,loaded_minimum_boundary=cp['source_cursor'] if behavior=='consumed' else '2021-05-25')))
        (folder/module.ORDINARY_QUALIFICATION).write_text(json.dumps(dict(financial_sessions_advanced=0)))
        loaded=SimpleNamespace(sha256='0'*64 if behavior=='hash' else sha_file(path),earliest_affected_session=cp['source_cursor'] if behavior=='consumed' else '2021-05-25')
        if behavior=='foreignpath':path=folder/'other-overlay.json';path.write_text('{}')
        return path,loaded
    module.prepare=prepare
    scope.update(selected_stub=lambda parent,arm:module if selected else None,backtest_stub=backtest,runtime_stub=runtime)
    return SimpleNamespace(cp=cp,spec=spec,out=out,module=module,calls=calls,backtest=backtest,runtime=runtime,originals=originals)

def assert_restored(f):
    assert (f.backtest.main,f.runtime.advance)==f.originals

def test_selected_composite_prepares_without_financial_advance_or_checkpoint(tmp_path):
    s=functions();f=fixture(tmp_path,s);before=deepcopy(f.cp)
    receipt=s['prepare_composite_before_finance'](f.cp,f.out,f.spec)
    assert f.calls==['prepare'] and f.cp==before
    assert receipt['financial_sessions_advanced']==0 and receipt['checkpoint_adopted'] is False and receipt['parent_unchanged'] is True
    assert receipt['runtime_source_sha256']==sha_file(f.module.__file__)
    assert set(receipt['artifacts'])=={f.module.OVERLAY,f.module.QUALIFICATION,f.module.ORDINARY_QUALIFICATION}
    s['require_composite_preparation'](f.cp,f.spec,dict(composite_preparation=receipt),f.out)
    assert not list(f.out.rglob('*.gz'));assert_restored(f)

@pytest.mark.parametrize('mode',['READONLY_FROZEN_SOURCE_WITNESSES','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'])
def test_source_and_report_modes_do_not_select_or_prepare_composite(mode,tmp_path):
    s=functions(mode=mode);f=fixture(tmp_path,s)
    def forbidden(*args):raise AssertionError('readonly cannot select financial composite')
    s['selected_stub']=forbidden
    assert s['prepare_composite_before_finance'](f.cp,f.out,f.spec) is None and f.calls==[]

def test_successful_other_phase_is_unchanged_and_foreign_receipt_refused(tmp_path):
    s=functions();f=fixture(tmp_path,s,selected=False)
    assert s['prepare_composite_before_finance'](f.cp,f.out,f.spec) is None and f.calls==[]
    s['require_composite_preparation'](f.cp,f.spec,{},f.out)
    with pytest.raises(ValueError,match='NO_FOREIGN_COMPOSITE'):s['require_composite_preparation'](f.cp,f.spec,dict(composite_preparation={}),f.out)

@pytest.mark.parametrize('behavior',['advance','main','failure','mutate','checkpoint','adoption','hash','consumed','foreignpath','qualifier'])
def test_actual_preparation_failures_stop_before_financial_launch_and_restore_callables(behavior,tmp_path):
    s=functions();f=fixture(tmp_path,s,behavior=behavior)
    with pytest.raises((ValueError,OSError)):s['prepare_composite_before_finance'](f.cp,f.out,f.spec)
    assert_restored(f)

def test_preexisting_financial_checkpoint_cannot_enter_preparation(tmp_path):
    s=functions();f=fixture(tmp_path,s);(f.out/'book').mkdir();(f.out/'book/checkpoint.json.gz').write_bytes(b'synthetic')
    with pytest.raises(ValueError,match='STARTS_WITHOUT_FINANCIAL_CHECKPOINT'):s['prepare_composite_before_finance'](f.cp,f.out,f.spec)
    assert f.calls==[];assert_restored(f)

@pytest.mark.parametrize('field,bad',[
    ('parent_outer_sha256','0'*64),('parent_inner_sha256','0'*64),('parent_input_sha256','0'*64),
    ('parent_cursor','2021-04-29'),('root_admission_sha256','0'*64),('runtime_source_sha256','0'*64),
    ('overlay_sha256','0'*64),('earliest_affected_session','2021-04-30'),('earliest_affected_session','2021-05-26'),('passed',False),
    ('financial_sessions_advanced',1),('checkpoint_adopted',True),('parent_unchanged',False),('arm','P06')])
def test_exact_parent_generation_timing_source_and_zero_authority_receipt_required(field,bad,tmp_path):
    s=functions();f=fixture(tmp_path,s);receipt=s['prepare_composite_before_finance'](f.cp,f.out,f.spec);receipt[field]=bad
    with pytest.raises(ValueError):s['require_composite_preparation'](f.cp,f.spec,dict(composite_preparation=receipt),f.out)

@pytest.mark.parametrize('which',['overlay','qualification','runtime'])
def test_replaced_preparation_artifact_or_runtime_cannot_launch(which,tmp_path):
    s=functions();f=fixture(tmp_path,s);receipt=s['prepare_composite_before_finance'](f.cp,f.out,f.spec)
    path={'overlay':f.out/f.module.OVERLAY,'qualification':f.out/f.module.QUALIFICATION,'runtime':Path(f.module.__file__)}[which]
    if which=='qualification':path.write_text('{"financial_sessions_advanced":0,"passed":true,"changed":true}')
    else:path.write_text('changed source-only bytes')
    with pytest.raises(ValueError):s['require_composite_preparation'](f.cp,f.spec,dict(composite_preparation=receipt),f.out)

@pytest.mark.parametrize('message,behavior',[
    ('RESUME_COMPOSITE_PREPARATION_NO_PARENT_MUTATION_OR_CHECKPOINT_ADOPTION','mutate'),
    ('RESUME_COMPOSITE_PREPARATION_ZERO_SESSION_QUALIFIERS','qualifier'),
    ('RESUME_COMPOSITE_PREPARED_EXACT_OVERLAY_AND_UNCONSUMED_BOUNDARY','consumed')])
def test_new_preparation_critical_guards_are_required(message,behavior,tmp_path):
    normal=functions();a=fixture(tmp_path/'normal',normal,behavior=behavior)
    with pytest.raises(ValueError,match=message):normal['prepare_composite_before_finance'](a.cp,a.out,a.spec)
    mutant=functions(break_guard=message);b=fixture(tmp_path/'mutant',mutant,behavior=behavior)
    assert mutant['prepare_composite_before_finance'](b.cp,b.out,b.spec)['passed'] is True

def test_exact_receipt_guard_removal_admits_wrong_parent_and_is_caught(tmp_path):
    s=functions();f=fixture(tmp_path,s);receipt=s['prepare_composite_before_finance'](f.cp,f.out,f.spec);receipt['parent_outer_sha256']='0'*64
    with pytest.raises(ValueError):s['require_composite_preparation'](f.cp,f.spec,dict(composite_preparation=receipt),f.out)
    mutant=functions(break_guard='RESUME_EXACT_STOPPED_ZERO_FINANCIAL_COMPOSITE_PREPARATION_REQUIRED')
    mutant.update({k:s[k] for k in ('selected_stub','backtest_stub','runtime_stub')})
    mutant['require_composite_preparation'](f.cp,f.spec,dict(composite_preparation=receipt),f.out)

def test_actual_resume_calls_gate_inside_retained_loader_before_any_economic_work():
    tree=ast.parse(source());pre=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='preflight')
    context=next(n for n in pre.body if isinstance(n,ast.With) and 'financial_inputs' in ast.unparse(n.items[0].context_expr))
    statements=[ast.unparse(n) for n in context.body]
    assert next(i for i,v in enumerate(statements) if 'actual_parent(old, spec)' in v)<next(i for i,v in enumerate(statements) if 'prepare_composite_before_finance(cp, out, spec)' in v)
    assert 'composite_preparation=preparation' in ast.unparse(pre)
    eco=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='economic')
    lines=[ast.unparse(n) for n in eco.body]
    assert next(i for i,v in enumerate(lines) if v.startswith('require_composite_preparation('))<next(i for i,v in enumerate(lines) if v.startswith('with financial_inputs('))
    full=ast.unparse(tree)
    assert "need(successful_stop(receipt['preflight']), 'RESUME_PARENT_PREFLIGHT_REFUSED_NO_FINANCIAL_LAUNCH')" in full
    assert not any(name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')) for name in sys.modules)
