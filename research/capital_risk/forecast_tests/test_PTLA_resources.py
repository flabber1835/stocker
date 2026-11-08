"""Current authenticated DATA and falsifiers for restart asset ownership."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_RESOURCE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PTLA_resources as r


def test_complete_current_full20_asset_inventory():
 v=r.fact();declared=r.declarations(v)
 assert len(declared)==123 and len(v['historical_archive_resolutions'])==4
 assert len(v['original105_destinations'])==105 and v['raw_proof']['rows']==v['committed_proof']['rows']==174
 assert v['parent_transport']['measured_closes']==628 and v['parent_transport']['selected_session']=='2020-06-30'


def test_complete_original_resource_functions_are_reused():
 api=r.original_api()
 for name in ('closure','verify','preserve','canary'):
  old,new=getattr(r.original,name),getattr(api,name)
  assert new.__code__ is old.__code__ and new.__closure__ is old.__closure__
 assert api.closure.__globals__['source'].ROOT==r.ROOT


def test_old_asset_omission_refused():
 v=deepcopy(r.fact());victim=next(n for n,e in v['resources'].items() if e['source_path'] in v['original105_destinations'] and not n.startswith('book/pre-event/'))
 del v['resources'][victim]
 with pytest.raises(ValueError,match='ALL27_NEW_READS_AND_ALL105'):r.declarations(v)


def test_actual_read_omission_refused():
 v=deepcopy(r.fact());victim=next(n for n,e in v['resources'].items() if e['source_path'] in v['actual_resource_trace']['reads'])
 del v['resources'][victim]
 with pytest.raises(ValueError,match='ALL27_NEW_READS_AND_ALL105'):r.declarations(v)


def test_archive_resolution_omission_refused():
 v=deepcopy(r.fact());v['historical_archive_resolutions'].pop()
 with pytest.raises(ValueError,match='ALL_ORIGINAL_PRE_EVENT'):r.declarations(v)


def test_original_diagnostic_cannot_occupy_new_active_output():
 v=deepcopy(r.fact());name=next(n for n in v['resources'] if n.startswith(r.PREFIX+'/origin/diagnostics/'))
 v['resources']['bounded-contingent-observer/actual-future-event-refusal.json']=v['resources'].pop(name)
 with pytest.raises(ValueError,match='NO_ACTIVE_BOOK_CONTROL_REVIEW_OR_DIAGNOSTIC'):r.declarations(v)


def test_diagnostic_collision_guard_removal_falsifier(monkeypatch):
 v=deepcopy(r.fact());name=next(n for n in v['resources'] if n.startswith(r.PREFIX+'/origin/diagnostics/'))
 active='bounded-contingent-observer/actual-future-event-refusal.json';v['resources'][active]=v['resources'].pop(name)
 with pytest.raises(ValueError):r.declarations(v)
 original=r.need
 monkeypatch.setattr(r,'need',lambda ok,label:None if label=='PTLA_RESOURCES_NO_ACTIVE_BOOK_CONTROL_REVIEW_OR_DIAGNOSTIC_COLLISION' else original(ok,label))
 assert active in r.declarations(v)


def test_source_pin_changes_refused():
 v=deepcopy(r.fact());name=next(iter(v['resources']));v['resources'][name]['sha256']='0'*64
 with pytest.raises(ValueError,match='EXACT_AUTHENTICATED_SOURCE_MEMBER'):r.declarations(v)


def test_original_qualification_does_not_occupy_next_writer_output():
 v=deepcopy(r.fact());v['resources']['branch-controller-qualification.json']=v['resources'].pop(r.QUALIFIED)
 with pytest.raises(ValueError,match='NO_ACTIVE_BOOK_CONTROL_REVIEW_OR_DIAGNOSTIC'):r.declarations(v)


def test_local_copy_paths_stay_closed():
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.preserve(None,None,None,None,None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.canary(None,None)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
