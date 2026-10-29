"""Synthetic differential proof guards, not a historical replay/economic result."""
import array,ast,copy
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import pytest
from system_campaign_equivalence import exact,compare_buffers,compare_cutoff,compare_future_inputs


def buffer():
    return SimpleNamespace(axis=deque(['2000-01-03'],maxlen=300),spy=deque([100.],maxlen=300),
        rings={'FAKE':SimpleNamespace(indices=array.array('i',[0]),tickers=['FAKE'],tradeable=array.array('b',[1]),
                                      values={'raw_close':array.array('d',[float('nan'),0.])})},
        metadata={'FAKE':{'kind':'SYNTHETIC'}},sectors={},index=0,current=None)


def test_buffer_bits_capacity_and_complete_fields_are_material():
    old=buffer();new=copy.deepcopy(old);assert compare_buffers(old,new)
    new.rings['FAKE'].values['raw_close'][1]=-0.
    with pytest.raises(ValueError,match='BUFFER_EXACT'):compare_buffers(old,new)
    new=copy.deepcopy(old);new.axis=deque(new.axis,maxlen=299)
    with pytest.raises(ValueError,match='BUFFER_EXACT'):compare_buffers(old,new)
    new=copy.deepcopy(old);new.extra=0
    with pytest.raises(ValueError,match='COMPLETE_BUFFER_FIELDS'):compare_buffers(old,new)
    with pytest.raises(ValueError,match='UNSUPPORTED_BUFFER_TYPE'):exact(object())


def test_actual_buffer_equality_guard_removal_falsifier():
    old=buffer();new=copy.deepcopy(old);new.spy[0]=101.
    with pytest.raises(ValueError,match='BUFFER_EXACT'):compare_buffers(old,new)
    tree=ast.parse(Path(compare_buffers.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='compare_buffers')
    node.body=[n for n in node.body if not any(isinstance(v,ast.Constant)
               and v.value=='EQUIVALENCE_COMPLETE_BUFFER_EXACT' for v in ast.walk(n))]
    scope=dict(compare_buffers.__globals__)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<removed-buffer-equality>','exec'),scope)
    assert scope['compare_buffers'](old,new)


def case():
    old=dict(source_cursor='2019-04-30',completed=1,base={'source':'same'},repairs=[{'sha':'old'}],
        run={'state':{'cash':100.},'state_sha256':'s','schema':'v1','base_main_sha':'m','policy':'p'},
        economics={'nav':'100'},stats={'n':1},spy_base=1.,retries={'n':0},sha256='old-cutoff')
    full=copy.deepcopy(old);full['sha256']='complete';selected=copy.deepcopy(old);selected['source_cursor']='2017-07-31'
    selected['run']['checkpoint_sha256']='own';new=copy.deepcopy(old);new['repairs'].append({'sha':'new'});new['sha256']='new-cutoff'
    doc={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':'own','source_evidence':[],'suppress':[],
         'add':[{'session':'2018-03-06','security_id':'FAKE'}]}
    return old,new,full,selected,doc


def test_any_state_or_future_input_change_refuses_equivalence():
    args=case();assert compare_cutoff(*args,'2019-04-30')['complete_recurrence_state_exact']
    args[1]['run']['state']['cash']=101.
    with pytest.raises(ValueError,match='CANONICAL_STATE_EXACT'):compare_cutoff(*args,'2019-04-30')
    args=case();args[-1]['add'][0]['session']='2020-01-02'
    with pytest.raises(ValueError,match='ALL_FUTURE_ACTION_INPUTS_EXACT'):compare_cutoff(*args,'2019-04-30')
    args=case();args[2]['repairs'].append({'sha':'later'})
    with pytest.raises(ValueError,match='EXACT_OLD_INPUT_SUCCESSOR_AXIS'):compare_cutoff(*args,'2019-04-30')


def future_case():
    args=case();d={'sha256':'future','resume_session':'2025-06-30','predecessor_checkpoint_sha256':'later-own'}
    args[2]['repairs'].append(d)
    future={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':'later-own','source_evidence':[],
        'suppress':[{'session':'2025-07-24','security_id':'TGI','term_sha256':'a'*64}],
        'add':[{'session':'2025-07-25','security_id':'TGI','cash_per_share':26.}]}
    for name in ('suppress','add'):args[-1][name].extend(copy.deepcopy(future[name]))
    return args,future


def test_identical_future_input_successor_and_economic_mutations():
    args,future=future_case()
    assert compare_cutoff(*args,'2019-04-30',future_documents=[future])['identical_future_ordinary_input_successors']==1
    for field,value in (('cash_per_share',27.),('session','2025-07-28'),('security_id','OTHER')):
        bad=copy.deepcopy(future);bad['add'][0][field]=value
        with pytest.raises(ValueError,match='ALL_FUTURE_ACTION_INPUTS_EXACT'):
            compare_cutoff(*args,'2019-04-30',future_documents=[bad])
    bad=copy.deepcopy(future);bad['suppress'][0]['term_sha256']='b'*64
    with pytest.raises(ValueError,match='ALL_FUTURE_ACTION_INPUTS_EXACT'):
        compare_cutoff(*args,'2019-04-30',future_documents=[bad])
    bad=copy.deepcopy(future);bad['bar_override']=[]
    with pytest.raises(ValueError,match='ORDINARY_FUTURE_INPUT_ONLY'):
        compare_cutoff(*args,'2019-04-30',future_documents=[bad])
    args[2]['repairs'][-1]['resume_session']='2019-04-30'
    with pytest.raises(ValueError,match='OLD_SUCCESSOR_STRICTLY_FUTURE'):
        compare_cutoff(*args,'2019-04-30',future_documents=[future])


def test_actual_future_equality_guard_removal_falsifier():
    args,future=future_case();args[-1]['add'][-1]['cash_per_share']=27.
    with pytest.raises(ValueError,match='ALL_FUTURE_ACTION_INPUTS_EXACT'):
        compare_future_inputs(args[2],args[3],args[0],args[-1],'2019-04-30',[future])
    node=next(n for n in ast.parse(Path(compare_future_inputs.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='compare_future_inputs')
    node.body=[n for n in node.body if not any(isinstance(v,ast.Constant)
        and v.value=='EQUIVALENCE_ALL_FUTURE_ACTION_INPUTS_EXACT' for v in ast.walk(n))]
    scope=dict(compare_future_inputs.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-future-equality>','exec'),scope)
    assert scope['compare_future_inputs'](args[2],args[3],args[0],args[-1],'2019-04-30',[future])==1


def test_historical_differential_entry_refuses_locally_before_output(monkeypatch,tmp_path):
    from system_campaign_equivalence_run import run
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);target=tmp_path/'not-created'
    with pytest.raises(ValueError,match='HOSTED'):
        run(target,Path('/missing-old'),{})
    assert not target.exists()
