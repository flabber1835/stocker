"""Concrete event-clock permissions over noncanonical metadata, no induction run."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_bounded_runtime_v2 import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_bounded_sensor_suffix_v2 as data

def test_new_event_still_uses_entire_original_permission_resolver(monkeypatch):
    calls=[]
    def original(*a,**k):calls.append((a,k));return {'SYNTHETIC_PERMISSION':True},['SYNTHETIC_RESOLUTION']
    monkeypatch.setattr(data.original,'permissions',original)
    c={'event':{'effective_session':'2099-11-12'}};rows=[{'session':'2099-11-12'}]
    result=data.event_permissions('synthetic-root',{'source_cursor':'2099-10-31'},[],rows,c,through='2099-11-29',input_descriptors=['CURRENT'])
    assert result==({'SYNTHETIC_PERMISSION':True},['SYNTHETIC_RESOLUTION'])
    assert calls==[(('synthetic-root',rows,c),dict(through='2099-11-29',input_descriptors=['CURRENT']))]

def test_retained_event_revalidates_genuine_historical_descriptor_identity_not_current_view(monkeypatch):
    c={'event':{'effective_session':'2099-11-12'}};old={'session':'2099-11-12'};calls=[]
    monkeypatch.setattr(data,'actual_archive',lambda *a:(Path('synthetic-producer-name'),b'SYNTHETIC',{'repairs':['HISTORICAL_ARCHIVE_IDENTITY']}))
    def locate(*a,**k):calls.append(k);return ('OLD_PERMISSION_NEVER_GRANTED_AGAIN',{'actual':'synthetic-producer-name'})
    monkeypatch.setattr(data.original,'locate',locate)
    result=data.event_permissions('synthetic-root',{'source_cursor':'2099-12-31'},[old],[{'session':'2100-01-02'}],c,
        through='2100-01-31',input_descriptors=['CURRENT_WITH_LATER_ORDINARY_INPUTS'])
    assert result[0]=={} and result[1][0]['prior_event_basis_revalidated'] is True
    assert result[1][0]['prior_transition_reexecuted'] is False
    assert calls==[dict(input_descriptors=['HISTORICAL_ARCHIVE_IDENTITY'])]

@pytest.mark.parametrize('change',['missing_old','duplicate_old','replayed_new'])
def test_missing_duplicate_or_replayed_prior_event_is_refused(change):
    c={'event':{'effective_session':'2099-11-12'}};old=[{'session':'2099-11-12'}];new=[{'session':'2100-01-02'}]
    if change=='missing_old':old=[]
    elif change=='duplicate_old':old*=2
    else:new.append({'session':'2099-11-12'})
    with pytest.raises(ValueError):data.event_permissions('unused',{'source_cursor':'2099-12-31'},old,new,c,through='2100-01-31',input_descriptors=[])

def test_entire_original_suffix_code_object_is_preserved_without_invoking_it():
    before=data.original.suffix
    fn=data.bind_suffix({'source_cursor':'2099-10-31'},[])
    assert fn.__code__ is before.__code__ and data.original.suffix is before
    assert fn.__globals__['permissions'] is not before.__globals__['permissions']
    for name,value in before.__globals__.items():
        if name!='permissions':assert fn.__globals__[name] is value

def test_hosted_guard_precedes_canonical_induction_imports(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('LOCAL_NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='LOCAL_NOT_HOSTED'):data.suffix(None,None,None,None,None,None,None,growth=None)
