"""Complete original observer composition and source ownership, opaque DATA."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_OBSERVER_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PTLA_observers as o


def dtos(monkeypatch):
 def term(i):return dict(security_id='EXPLICIT_NONCANONICAL_SECURITY_DTO_'+str(i),added=dict(session='EXPLICIT_NONCANONICAL_DAY_DTO',kind='CASH_MERGER',security_id='EXPLICIT_NONCANONICAL_SECURITY_DTO_'+str(i)))
 old=[term(i) for i in range(34)];new=term(34)
 monkeypatch.setattr(o.data,'terms',lambda:[deepcopy(new)])
 doc=dict(EXPLICIT_NONCANONICAL_INPUT_DOCUMENT_DTO=True,add=[new['added']]);raw=o.data.encoded(doc)
 material=dict(EXPLICIT_NONCANONICAL_MATERIAL_DTO=True,terms=[new]);material_raw=o.data.encoded(material)
 descriptor=dict(sha256=o.original.sha(raw),filename=o.original.sha(raw)+'.json')
 return old,new,doc,material,material_raw,descriptor


def test_all_prior_terms_are_preserved_and_one_added(monkeypatch):
 old,new,doc,material,raw,descriptor=dtos(monkeypatch);tail=old[-10:];resources={'EXPLICIT_NONCANONICAL_OLD_RESOURCE_DTO':b'OLD_DTO'}
 result,files=o.extend(tail,resources,old,doc,material,raw,descriptor,'EXPLICIT_NONCANONICAL_MATERIAL_DTO.json')
 assert result==o.original.merge(tail,[new]) and len(o.original.merge(old,result))==35
 assert files['EXPLICIT_NONCANONICAL_OLD_RESOURCE_DTO']==b'OLD_DTO' and len(files)==2
 assert resources=={'EXPLICIT_NONCANONICAL_OLD_RESOURCE_DTO':b'OLD_DTO'}


@pytest.mark.parametrize('changed',['descriptor','material','prior_term','source_only_scope'])
def test_altered_input_material_or_inherited_terms_refused(monkeypatch,changed):
 old,new,doc,material,raw,descriptor=dtos(monkeypatch)
 if changed=='descriptor':descriptor['sha256']='0'*64;descriptor['filename']='0'*64+'.json'
 elif changed=='material':raw=b'{}'
 elif changed=='prior_term':old.pop()
 else:
  new['require_unowned_and_unordered']=True;monkeypatch.setattr(o.data,'terms',lambda:[new])
 with pytest.raises(ValueError):o.extend(old[-10:],{},old,doc,material,raw,descriptor,'EXPLICIT_NONCANONICAL_MATERIAL_DTO.json')


def test_original_resource_cannot_be_replaced(monkeypatch):
 old,new,doc,material,raw,descriptor=dtos(monkeypatch)
 key=o.original.DIRECTORY+'/materials/'+descriptor['sha256']+'/EXPLICIT_NONCANONICAL_MATERIAL_DTO.json'
 resources={key:b'EXPLICIT_NONCANONICAL_ORIGINAL_RESOURCE_DTO'}
 with pytest.raises(ValueError,match='NO_REPLACED_ORIGINAL_SOURCE_RESOURCE'):
  o.extend(old[-10:],resources,old,doc,material,raw,descriptor,'EXPLICIT_NONCANONICAL_MATERIAL_DTO.json')
 prior=o.need;monkeypatch.setattr(o,'need',lambda ok,label:None if label=='PTLA_OBSERVER_NO_REPLACED_ORIGINAL_SOURCE_RESOURCE' else prior(ok,label))
 _,files=o.extend(old[-10:],resources,old,doc,material,raw,descriptor,'EXPLICIT_NONCANONICAL_MATERIAL_DTO.json')
 assert files[key]==raw and files[key]!=resources[key]


def test_no_new_term_before_actual_descriptor21(monkeypatch):
 expected=(['EXPLICIT_NONCANONICAL_OLD_TAIL_DTO'],{'EXPLICIT_NONCANONICAL_OLD_RESOURCE_DTO':b'DTO'})
 monkeypatch.setattr(o,'inherited',lambda *a,**k:({},*expected,[]))
 monkeypatch.setattr(o.history,'document',lambda *a:pytest.fail('No actual21 descriptor is present'))
 assert o.tail_materials(Path('EXPLICIT_NONCANONICAL_ROOT_DTO'),dict(repairs=['EXPLICIT_NONCANONICAL_DESCRIPTOR_DTO']*20))==expected


def test_all_three_original_entry_bodies_and_closures_reused():
 for name in ('observer','review','stage_retained'):
  fn=getattr(o.original,name);bound=o.bind(name)
  assert bound.__code__ is fn.__code__ and bound.__closure__ is fn.__closure__
  assert bound.__globals__['tail_materials']is o.tail_materials
 with pytest.raises(ValueError,match='ONLY_COMPLETE_ORIGINAL_ENTRY'):o.bind('EXPLICIT_NONCANONICAL_BAD_ENTRY_DTO')


def test_local_observer_and_review_paths_closed():
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):o.observer(None,None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):o.review(None,None,None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):o.stage_retained(None,None,None)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
