"""Closed source-manifest checks and explicit noncanonical filename DTO only."""
import json,sys
from pathlib import Path
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('WWE12_FINAL_SOURCE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_WWE12_runtime as p
from system_campaign_financial_partial import root_spec

def test_actual_closed_source_profile_and_finite_final_declaration():
 value=p.declaration(root_spec('P06',p.data.ROOT))
 assert value['committed_seed_rows']==173 and value['actual_parent_inputs']==11 and value['required_genuine_neutral_inputs']==12
 assert value['genuine_neutral12_known'] is value['financial_source_changed'] is False
 assert len(p.source_names())==len(set(p.source_names()))

def test_plain_filename_guard_and_meaningful_removal(monkeypatch):
 class NoncanonicalManifestDTO:
  def __truediv__(self,n):return self
  def is_file(self):return True
  def read_bytes(self):return json.dumps(dict(EXPLICIT_NONCANONICAL_SOURCE_MANIFEST_DTO=True,files={'../EXPLICIT_NONCANONICAL_ESCAPE.json':{}})).encode()
 monkeypatch.setattr(p,'HERE',NoncanonicalManifestDTO())
 for module in (p.api,p.seeds,p.observations,p.loader):monkeypatch.setattr(module,'source_names',lambda:())
 with pytest.raises(ValueError,match='PLAIN_WHOLE'):p.source_names()
 original=p.data.need;monkeypatch.setattr(p.data,'need',lambda value,label:None if label=='P06_WWE12_ONLY_PLAIN_WHOLE_PROFILE_SOURCE_FILENAMES' else original(value,label))
 assert '../EXPLICIT_NONCANONICAL_ESCAPE.json' in p.source_names()

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
