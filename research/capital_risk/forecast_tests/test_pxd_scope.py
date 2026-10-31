"""Pure PXD input boundary and original-scope isolation; no financial runtime."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace, MethodType

import pytest
import system_campaign_close_scope as old
import system_campaign_pxd_scope as scope

SID = '276044719892003870'
PRED = 'a'*64
EVIDENCE = [dict(reference=f'research:inert-pxd/{i}',description='inert',sha256=str(i)*64) for i in range(3)]


def body():
    return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=PRED,
        source_evidence=[],suppress=[dict(session='2024-05-02',security_id=SID,term_sha256='b'*64)],add=[])


def document():
    return dict(schema=scope.SCHEMA,scope=scope.SCOPE,predecessor_checkpoint_sha256=PRED,
        require_unowned_and_unordered=True,require_no_entry_intents=True,
        morning_settlement_claimed=False,canonical_repair=body(),source_evidence=deepcopy(EVIDENCE))


def load(tmp_path,value=None,**changes):
    path=tmp_path/'inert-input.json';path.write_text(json.dumps(value or document()),encoding='utf8')
    return scope.parse(path,**dict(dict(resume_session='2024-04-30',
        predecessor_checkpoint_sha256=PRED,expected_repair=body(),expected_evidence=EVIDENCE),**changes))


def state(label):
    return SimpleNamespace(state_hash=label,wealth_core={'episodes':{}},pending=[],
        last_evidence={'wealth_core':{'intents':[]}})


def guard(tmp_path):
    obj=load(tmp_path)
    value=scope.TransitionGuard(SimpleNamespace(objects=[obj]))
    run=SimpleNamespace(state=state('before'),input_sha256='c'*64)
    result=SimpleNamespace(state=state('after'))
    value.original_advance=lambda actual,published: result
    return value,run,result


def test_separate_actual_schema_and_original_function_bodies(tmp_path):
    before=Path(old.__file__).read_bytes()
    obj=load(tmp_path)
    assert obj.model_dump(by_alias=True)['schema']==scope.SCHEMA
    assert old.NATIVES=={'533554648046407798':'2023-11-06'}
    assert old.COMPLETIONS=={'533554648046407798':'2023-11-07'}
    assert scope.active('2024-05-01')==[] and scope.active('2024-05-02')==[SID]
    assert scope.active('2026-07-31')==[SID]
    assert scope.parse.__code__ is old.parse.__code__
    assert scope.TransitionGuard.advance.__code__ is old.TransitionGuard.advance.__code__
    assert scope.InputCodec.load.__code__ is old.InputCodec.load.__code__
    assert scope.review_guards.__code__ is old.review_guards.__code__
    assert Path(old.__file__).read_bytes()==before


@pytest.mark.parametrize('change',[dict(predecessor_checkpoint_sha256='0'*64),dict(resume_session='2024-05-02')])
def test_wrong_predecessor_and_consumed_input_refuse(tmp_path,change):
    with pytest.raises(ValueError):load(tmp_path,**change)


@pytest.mark.parametrize('field,value',[('schema',old.SCHEMA),('scope',old.SCOPE),
    ('require_no_entry_intents',False),('require_unowned_and_unordered',1),
    ('morning_settlement_claimed',True),('unexpected','ignored')])
def test_foreign_or_relaxed_scope_refuses(tmp_path,field,value):
    doc=document();doc[field]=value
    with pytest.raises(ValueError):load(tmp_path,doc)


@pytest.mark.parametrize('when',['before','after'])
@pytest.mark.parametrize('kind',['owned','pending','intent','claim'])
def test_actual_transition_refuses_positions_orders_intents_claims(tmp_path,when,kind):
    value,run,result=guard(tmp_path)
    altered=run.state if when=='before' else result.state
    if kind=='owned':altered.wealth_core['episodes']['inert']={'security_id':SID}
    elif kind=='pending':altered.pending=[{'security_id':SID}]
    elif kind=='intent':altered.last_evidence['wealth_core']['intents']=[{'security_id':SID}]
    else:altered.wealth_core['unresolved_terminals']={SID:{}}
    with pytest.raises(ValueError):value.advance(run,SimpleNamespace(session='2024-05-02'))
    assert value.pending is None and value.failure['financial_row_committed'] is False


def test_actual_scope_proof_binds_committed_row_and_new_watch(tmp_path):
    value,run,result=guard(tmp_path)
    assert value.advance(run,SimpleNamespace(session='2024-05-02')) is result
    proof=deepcopy(value.pending)
    assert proof['schema']==scope.WATCH and proof['scope']==scope.SCOPE
    assert proof['affected_security_ids']==[SID] and proof['prior_state_sha256']=='before'
    writes=[];value.original_append=lambda journal,name,record:writes.append((name,record))
    row=dict(session='2024-05-02',state_sha256='after',input_sha256='c'*64)
    value.append(object(),'daily',row)
    assert writes[0][0]=='watch' and writes[0][1]['schema']==scope.WATCH
    assert writes[1]==('daily',row) and value.pending is None
    assert writes[0][1]['financial_row_sha256']==old.digest(row)


def test_actual_position_guard_removal_falsifier(tmp_path):
    value,run,result=guard(tmp_path)
    run.state.wealth_core['episodes']['inert']={'security_id':SID}
    with pytest.raises(ValueError):value.advance(run,SimpleNamespace(session='2024-05-02'))
    node,=[n for n in ast.parse(Path(old.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='projection']
    node.body=[n for n in node.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Name) and n.value.func.id=='require_absent')]
    namespace=dict(vars(old))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<actual-position-guard-removed>','exec'),namespace)
    broken=scope.isolated(scope.TransitionGuard.advance,projection=namespace['projection'])
    value.advance=MethodType(broken,value)
    assert value.advance(run,SimpleNamespace(session='2024-05-02')) is result


def test_source_guard_removal_falsifier(monkeypatch):
    monkeypatch.setattr(scope,'SOURCE_SHA256','0'*64)
    with pytest.raises(ValueError,match='EXACT_UNCHANGED_SEVENTH_INPUT_IMPLEMENTATION'):
        scope.require_source()
    monkeypatch.setattr(scope,'require_source',lambda:None)
    assert scope.isolated(old.active,NATIVES=scope.NATIVES)('2024-05-02')==[SID]
