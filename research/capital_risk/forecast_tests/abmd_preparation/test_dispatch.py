"""Readonly declaration and unchanged legacy entry, metadata only."""
from copy import deepcopy
import pytest
import system_campaign_abmd_preflight_dispatch as data
from system_campaign_financial_partial import root_spec

@pytest.mark.parametrize('arm',['P06','P07'])
def test_two_exact_own1238_declarations_have_no_adoption_or_financial_transition(arm):
    d=data.declaration(root_spec(arm))
    assert d['catalog_file'].startswith(arm) and d['financial_sessions_advanced']==0 and d['checkpoint_adopted'] is False
    assert len(data.source_names())==len(set(data.source_names()))

@pytest.mark.parametrize('change',['outer','count','cursor','inputs','authority'])
def test_stale_or_financial_root_refuses(change):
    s=deepcopy(root_spec('P07'))
    if change=='outer':s['outer_sha256']='0'*64
    elif change=='count':s['measured_closes']=1237
    elif change=='cursor':s['selected_session']='2022-10-31'
    elif change=='inputs':s['repairs']=s['repairs'][:-1]
    else:s['financial_authority']=True
    with pytest.raises(ValueError):data.declaration(s)

def test_other_roots_have_no_implicit_preparation():
    assert data.declaration(root_spec('P05')) is None
    s=dict(root_spec('P07'),root_admission_sha256='0'*64);assert data.declaration(s) is None

def test_unselected_entry_calls_complete_legacy_wrapper_and_does_no_new_work(monkeypatch):
    import system_campaign_bounded_sensor_preparation as previous
    calls=[];legacy=lambda *a:None
    monkeypatch.setattr(previous,'preflight_entry',lambda *a,**k:calls.append((a,k)))
    assert data.preflight_entry('SYNTHETIC_OLD','SYNTHETIC_OUT',{},legacy,old_bounded_enabled=False) is None
    assert calls==[(('SYNTHETIC_OLD','SYNTHETIC_OUT',{},legacy),dict(enabled=False))]

def test_selected_entry_refuses_before_any_local_financial_import(monkeypatch):
    import system_campaign_bounded_sensor_preparation as previous
    import full_system_core
    monkeypatch.setattr(previous,'preflight_entry',lambda *a,**k:None)
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        data.preflight_entry('unused','unused',{},lambda *a:None,abmd_declaration={'synthetic':True})
