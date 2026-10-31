"""Inert checkpoint metadata and callback tests; never invoke a financial runtime."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import system_campaign_pxd_pause as pause


OVERLAY='d'*64


def outer(value):
    run=value['run']
    run['checkpoint_sha256']=pause.digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
    value['sha256']=pause.digest({k:v for k,v in value.items() if k!='sha256'})
    return value


def pair():
    before=dict(base={'inert':True},source_cursor='2024-04-30',completed=1592,
        economics={'nav':'123'},stats={'rows':3},spy_base='1',retries={'count':0},repairs=[],
        chain='a'*64,journals={n:dict(bytes=0,prefix_sha256=pause.sha(b''))
            for n in ('daily','formation','watch','monthly')},
        run=dict(state={'inert_state':'unchanged'},state_sha256=pause.digest({'inert_state':'unchanged'}),
            input_sha256=pause.digest(dict(base={'inert':True},repairs=[]))))
    outer(before);after=deepcopy(before)
    descriptor=dict(filename=OVERLAY+'.json',sha256=OVERLAY,resume_session='2024-04-30',
        predecessor_checkpoint_sha256=before['run']['checkpoint_sha256'])
    after['repairs'].append(descriptor)
    after['run']['input_sha256']=pause.digest(dict(base=after['base'],repairs=after['repairs']))
    event=dict(schema='research.pooled-action-successor/1',
        predecessor_checkpoint_sha256=before['run']['checkpoint_sha256'],unchanged_through='2024-04-30',
        earliest_affected_session='2024-05-02',state_sha256=before['run']['state_sha256'],overlay=descriptor,
        predecessor_input_sha256=before['run']['input_sha256'],successor_input_sha256=after['run']['input_sha256'])
    after['chain']=pause.digest(dict(previous=before['chain'],event=event))
    after['journals']['watch']=dict(bytes=1,prefix_sha256=pause.sha(b'x'))
    outer(after)
    return before,after,event


def test_exact_canonical_metadata_boundary():
    before,after,event=pair();saved=deepcopy(after)
    assert pause.adoption(after,before,OVERLAY,'2024-05-02')==event
    assert after==saved


@pytest.mark.parametrize('change',['economics','controller','count','retries','descriptor','chain','journal'])
def test_no_financial_controller_or_lineage_change_can_hide_inside_valid_hashes(change):
    before,after,_=pair()
    if change=='economics':after['economics']['nav']='124'
    elif change=='controller':
        after['run']['state']['inert_state']='changed'
        after['run']['state_sha256']=pause.digest(after['run']['state'])
    elif change=='count':after['completed']+=1
    elif change=='retries':after['retries']['count']+=1
    elif change=='descriptor':
        after['repairs'][-1]['predecessor_checkpoint_sha256']='0'*64
        after['run']['input_sha256']=pause.digest(dict(base=after['base'],repairs=after['repairs']))
    elif change=='chain':after['chain']='0'*64
    else:after['journals']['daily']['bytes']=1
    outer(after)
    with pytest.raises(ValueError):pause.adoption(after,before,OVERLAY,'2024-05-02')


def private_functions():
    # Functions are inert test callbacks with a shared, recognizable source file.
    namespace={}
    exec(compile('def run_backtest(): pass\ndef create():\n stop=[]\n def handler(number,frame): stop.append(number)\n return handler,stop\n',
        '<inert-canonical-source>','exec'),namespace)
    return namespace['run_backtest'],namespace['create']()


def test_pause_calls_only_registered_function_and_blocks_runtime_advance(tmp_path,monkeypatch):
    before,after,_=pair();path=tmp_path/'checkpoint.json.gz'
    value=pause.PauseAfterAdoption(before,path,OVERLAY,'2024-05-02')
    function,(handler,stop)=private_functions();writes=[]
    value.backtest=SimpleNamespace(run_backtest=function)
    value.original_write=lambda p,v:writes.append((p,deepcopy(v)))
    monkeypatch.setattr(pause.signal,'getsignal',lambda sig:handler)
    value.write(path,before);assert stop==[]
    value.write(path,after);assert stop==[pause.signal.SIGTERM]
    assert len(writes)==2 and value.proof()['financial_sessions_advanced']==0
    with pytest.raises(ValueError,match='EXACTLY_ONE_INPUT_ADOPTION'):value.write(path,after)
    with pytest.raises(ValueError,match='UNCHANGED_PRE_ADOPTION_CHECKPOINT'):value.write(path,before)
    with pytest.raises(ValueError,match='CANNOT_ADVANCE'):value.advance(object(),object())
    with pytest.raises(ValueError,match='EXACT_ADOPTION_WITH_NO_ADVANCE'):value.proof()


def test_foreign_handler_or_output_refuses_before_write(tmp_path,monkeypatch):
    before,after,_=pair();path=tmp_path/'checkpoint.json.gz'
    value=pause.PauseAfterAdoption(before,path,OVERLAY,'2024-05-02');writes=[]
    value.original_write=lambda p,v:writes.append(v)
    value.backtest=SimpleNamespace(run_backtest=lambda:None)
    monkeypatch.setattr(pause.signal,'getsignal',lambda sig:None)
    with pytest.raises(ValueError,match='ONLY_ACTUAL_PRIVATE_CANONICAL_STOP_HANDLER'):value.write(path,after)
    with pytest.raises(ValueError,match='ONLY_DISPOSABLE_CURRENT_CHECKPOINT'):value.write(tmp_path/'other.gz',after)
    assert writes==[]


def test_actual_financial_equality_guard_removal_falsifier():
    before,after,_=pair();after['economics']['nav']='124';outer(after)
    with pytest.raises(ValueError):pause.adoption(after,before,OVERLAY,'2024-05-02')
    node,=[n for n in ast.parse(Path(pause.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='adoption']
    removed=[n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='PXD_ZERO_STARTUP_ALL_FINANCIAL_AND_REPORTING_VALUES_UNCHANGED'
            for a in n.value.args)]
    assert len(removed)==1;node.body=[n for n in node.body if n not in removed]
    namespace=dict(vars(pause))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<actual-financial-equality-guard-removed>','exec'),namespace)
    assert namespace['adoption'](after,before,OVERLAY,'2024-05-02')['unchanged_through']=='2024-04-30'


def test_exit_restores_every_hook_and_both_handlers(monkeypatch):
    before,_,_=pair();value=pause.PauseAfterAdoption(before,Path('inert'),OVERLAY,'2024-05-02')
    original_write,original_advance=object(),object()
    value.backtest=SimpleNamespace(write_checkpoint='wrapped');value.runtime=SimpleNamespace(advance='blocked')
    value.original_write,value.original_advance=original_write,original_advance
    value.original_handlers={pause.signal.SIGINT:object(),pause.signal.SIGTERM:object()}
    restored=[];monkeypatch.setattr(pause.signal,'signal',lambda sig,handler:restored.append((sig,handler)))
    value.__exit__(ValueError,ValueError('inert failure'),None)
    assert value.backtest.write_checkpoint is original_write and value.runtime.advance is original_advance
    assert restored==list(value.original_handlers.items())
