"""Zero-transition preparation selection and host boundary; DATA only."""
import json,sys
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_PREPARATION_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_bounded_sensor_preparation as data

def test_exact_source_generation_catalog_and_complete_registered_interpreters():
    v=data.catalog();assert len(v['input_semantics_sources'])==9 and len(data.source_names())==10
    for name in data.source_names():assert (Path(data.__file__).parent/name).is_file()
    assert data.selected(dict(arm='P03',root_admission_sha256=v['parent_root_admission_sha256']))

@pytest.mark.parametrize('spec',[None,dict(arm='P03'),dict(arm='P05',root_admission_sha256='2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0'),dict(arm='P03',root_admission_sha256='0'*64)])
def test_foreign_or_unqualified_roots_are_never_selected(spec):assert not data.selected(spec)

def test_disabled_entry_keeps_original_preflight_and_does_no_preparation(tmp_path,monkeypatch):
    seen=[]
    monkeypatch.setattr(data,'prepare',lambda *args:seen.append('prepare'))
    data.preflight_entry(tmp_path,tmp_path,{},lambda *args:seen.append('legacy'),enabled=False)
    assert seen==['legacy']

def test_enabled_entry_cannot_enter_preparation_outside_the_hosted_boundary(tmp_path,monkeypatch):
    import full_system_core
    seen=[]
    def refuse():raise ValueError('SYNTHETIC_HOST_BOUNDARY')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    monkeypatch.setattr(data,'prepare',lambda *args:seen.append('prepare'))
    with pytest.raises(ValueError,match='SYNTHETIC_HOST_BOUNDARY'):
        data.preflight_entry(tmp_path,tmp_path,{},lambda *args:seen.append('legacy'),enabled=True)
    assert seen==['legacy']

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
