"""Complete immutable resource metadata and collision/dependency falsifiers."""
import sys
from pathlib import Path
from copy import deepcopy
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('KDNY_RESOURCES_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_KDNY_resources as p


def test_entire_authentic_full26_fact_preserves_trace_and_all165_old_assets():
 v=p.fact();declared=p.declarations(v)
 archives=v['historical_archive_resolutions']
 assert len(declared)+len(archives)==216
 assert sum(x['bytes'] for x in v['resources'].values())==366268272
 assert (v['raw_proof']['rows'],v['committed_proof']['rows'],len(v['excluded_tail_sessions']))==(956,949,7)
 original=__import__('json').loads((C/'P07-BWA-saved-resources.json').read_bytes())
 assert all(v['actual_financial_manifest'][name]==pin for name,pin in original['resources'].items())
 assert len(v['actual_resource_trace']['reads'])==94
 assert not v['financial_profile_ready'] and not v['actual_neutral27_known']


def dto():
 raw=b'EXPLICIT_NONCANONICAL_IMMUTABLE_RESOURCE_DTO';pin=p.pin(raw)
 v=dict(resources={'origin/input.json':dict(source_path='input.json',archive_role='original_financial',authenticated_member='input.json',**pin)},
  actual_financial_manifest={'input.json':pin},actual_readonly_manifest={},actual_resource_trace={'reads':{'input.json':pin}})
 return v


@pytest.mark.parametrize('name',['book/checkpoint.json.gz','book/watch.jsonl','uncertainty-certificate.jsonl','stopped-review/core-review.json','source-bindings.json','parent-preflight/worker.log'])
def test_old_resources_cannot_occupy_new_current_output_names(name):
 v=dto();v['resources'][name]=v['resources'].pop('origin/input.json')
 with pytest.raises(ValueError,match='COLLISION'):p.declarations(v)


def test_current_control_collision_guard_removal_falsifier(monkeypatch):
 v=dto();v['resources']['source-bindings.json']=v['resources'].pop('origin/input.json')
 with pytest.raises(ValueError):p.declarations(v)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='KDNY_RESOURCE_NO_CURRENT_CONTROL_REVIEW_JOURNAL_OR_CHECKPOINT_COLLISION' else old(ok,label))
 assert 'source-bindings.json' in p.declarations(v)


def test_complete_reader_dependency_guard_removal_falsifier(monkeypatch):
 v=dto();v['actual_resource_trace']['reads']['missing-input.json']=p.pin(b'EXPLICIT_NONCANONICAL_MISSING_DTO')
 with pytest.raises(ValueError,match='ALL94'):p.declarations(v)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='KDNY_RESOURCE_ALL94_ACTUAL_FULL26_READER_DEPENDENCIES' else old(ok,label))
 assert p.declarations(v)=={'origin/input.json':p.pin(b'EXPLICIT_NONCANONICAL_IMMUTABLE_RESOURCE_DTO')}


def test_original_failed_reviews_and_new_successful_proofs_have_distinct_names():
 v=p.fact();fresh=[(n,x) for n,x in v['resources'].items() if x['archive_role']=='successful_readonly_review']
 assert len(fresh)==4
 assert any(x['source_path'].startswith('lineage/request231-review-requalification/original-stopped-review') for x in v['resources'].values())
 assert all(not n.startswith('stopped-review/') for n,x in fresh)
 assert v['original_failed_stops']==[0,1,1] and v['fresh_readonly_stops']==[0,0]


def test_local_copy_and_canary_are_closed():
 with pytest.raises(ValueError):p.preserve(Path('EXPLICIT_NONCANONICAL_SOURCE_DTO'),Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO'),{},[],b'')
 with pytest.raises(ValueError):p.canary(Path('EXPLICIT_NONCANONICAL_SOURCE_DTO'),Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO'))


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
