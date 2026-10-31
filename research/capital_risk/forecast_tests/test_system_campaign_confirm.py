"""Finalist chronology and local historical-entry fences; synthetic locks only."""
import ast,copy
from pathlib import Path
import pytest
from system_campaign_confirm import selected_for_core,confirm
from system_campaign_joint_space import joint_profiles
from system_campaign_facts import digest


def locks():
    ids=[v['id'] for v in joint_profiles()['joint_profiles']]
    result=[]
    for day,index in (('2020-12-31',1),('2022-12-30',2)):
        v={'schema':'research.system-campaign-global-training-lock/1','cutoff':day,
           'status':'TRAINING_LOCKED','selected':['FAKE_CORE::'+ids[index]],'evaluation_used':False,
           'global_optimum_claim':False}
        result.append({**v,'sha256':digest(v)})
    return result,ids


def test_only_frozen_training_selected_ids_admitted():
    values,ids=locks()
    assert selected_for_core(values,'FAKE_CORE')==ids[1:3]
    values[0]['selected'].append('FAKE_CORE::'+ids[3])
    with pytest.raises(ValueError,match='AUTHENTIC_TRAINING_LOCK'):selected_for_core(values,'FAKE_CORE')
    values[0]['sha256']=digest({k:v for k,v in values[0].items() if k!='sha256'})
    assert selected_for_core(values,'FAKE_CORE')==ids[1:4]
    with pytest.raises(ValueError,match='ONLY_FROZEN_SELECTED_IDS'):selected_for_core(values,'OTHER_CORE')


def test_later_cutoff_refused_and_actual_guard_removal_falsifier():
    values,ids=locks();values[1]['cutoff']='2024-12-31'
    values[1]['sha256']=digest({k:v for k,v in values[1].items() if k!='sha256'})
    with pytest.raises(ValueError,match='ORDERED_TRAINING_LOCKS'):selected_for_core(values,'FAKE_CORE')
    tree=ast.parse(Path(selected_for_core.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='selected_for_core')
    node.body.pop(0);scope=dict(selected_for_core.__globals__)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<removed-finalist-chronology>','exec'),scope)
    assert scope['selected_for_core'](values,'FAKE_CORE')==ids[1:3]


def test_no_local_historical_confirmation_or_output(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);target=tmp_path/'not-created'
    with pytest.raises(ValueError,match='HOSTED_JOINT_NUMERICAL_ONLY'):
        confirm(Path('/missing-core'),Path('/missing-numeric'),Path('/missing-audit'),Path('/missing-selection'),target)
    assert not target.exists()
