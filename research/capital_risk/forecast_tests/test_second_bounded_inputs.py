"""Explicit noncanonical packet/class DTOs; never instantiate financial classes."""
import ast,importlib.util,json,sys
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
from types import FunctionType,SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('SECOND_BOUNDED_NONCANONICAL_DTO_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_second_bounded_codec as codec
import system_campaign_second_bounded_factory as factory
import system_campaign_bounded_sensor_input as original

@pytest.fixture
def pair():
 path=C/'forecast_tests/bounded_sensor/test_bounded_sensor.py'
 spec=importlib.util.spec_from_file_location('second_bounded_original_noncanonical_helpers',path)
 m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 native=m.Native();old_event=m.event();old_evidence=m.evidence()
 new_native=replace(native,session='2020-06-10',security_id='235472954303009097')
 event=dict(old_event,ticker='STML',security_id=new_native.security_id,native_session='2020-06-10',
  effective_session='2020-06-10',prior_session='2020-06-09',native_term_sha256=original.digest(asdict(new_native)),
  upfront_cash_per_share='11.50',right_upper_per_share='1.00')
 evidence=[dict(v,reference='EXPLICIT_NONCANONICAL_STML_DTO:'+str(i)) for i,v in enumerate(old_evidence)]
 lower=original.InputCodec(old_event,old_evidence,native);calls=[]
 lower.original_load=lambda *args,**kwargs:calls.append(('load',args,kwargs)) or 'EXPLICIT_NONCANONICAL_UNRELATED_INPUT_DTO'
 lower.original_apply=lambda packet,obj:calls.append(('apply',packet,obj)) or packet
 outer=codec.SuccessorCodec(event,evidence,new_native,previous_event=old_event,previous_evidence=old_evidence)
 outer.original_load,outer.original_apply=lower.load,lower.apply
 return m,lower,outer,calls,new_native

def document(owner):
 return dict(schema=original.SCHEMA,predecessor_checkpoint_sha256='a'*64,event=owner.event,source_evidence=owner.evidence)

def load(owner,path):
 return owner.load(path,resume_session='2019-10-01',predecessor_checkpoint_sha256='a'*64)

def write(tmp_path,value,name='EXPLICIT_NONCANONICAL_INPUT_DTO.json'):
 path=tmp_path/name;path.write_bytes((json.dumps(value,sort_keys=True)+'\n').encode());return path

def test_both_same_schema_inputs_keep_their_actual_original_owners(pair,tmp_path):
 m,lower,outer,calls,new_native=pair
 old=load(outer,write(tmp_path,document(lower),'EXPLICIT_NONCANONICAL_OLD_DTO.json'))
 new=load(outer,write(tmp_path,document(outer),'EXPLICIT_NONCANONICAL_NEW_DTO.json'))
 assert lower.objects==[old] and outer.objects==[new]
 assert outer.apply(m.Packet('2019-11-12',(lower.native,)),old).terminal==(lower.native,)
 assert outer.apply(m.Packet('2020-06-10',(new_native,)),new).terminal==(new_native,)
 assert calls==[] and old.event.ticker=='DOVA' and new.event.ticker=='STML'

def test_unrelated_inputs_keep_the_entire_original_delegate_chain(pair,tmp_path):
 m,lower,outer,calls,_=pair;path=write(tmp_path,{'schema':'EXPLICIT_NONCANONICAL_OTHER_SCHEMA'})
 assert load(outer,path)=='EXPLICIT_NONCANONICAL_UNRELATED_INPUT_DTO'
 packet=m.Packet('2020-06-10',());obj=object()
 assert outer.apply(packet,obj) is packet and [v[0] for v in calls]==['load','apply']

@pytest.mark.parametrize('mutation',['unknown','evidence','wrong_lower','wrong_apply'])
def test_unknown_event_or_changed_original_owner_refuses_before_loading(pair,tmp_path,mutation):
 _,lower,outer,calls,_=pair;value=deepcopy(document(lower))
 if mutation=='unknown':value['event']['security_id']='123456789'
 elif mutation=='evidence':value['source_evidence'][0]['sha256']='f'*64
 elif mutation=='wrong_lower':outer.original_load=lambda *args,**kwargs:None
 else:outer.original_apply=lambda *args:None
 with pytest.raises(ValueError):load(outer,write(tmp_path,value))
 assert not lower.objects and not outer.objects and calls==[]

@pytest.mark.parametrize('which',['old','new'])
def test_copy_of_a_loaded_object_is_not_owned(pair,tmp_path,which):
 m,lower,outer,_,new_native=pair;owner=lower if which=='old' else outer
 obj=load(outer,write(tmp_path,document(owner)));packet=m.Packet('2020-06-10',(new_native,))
 with pytest.raises(ValueError):outer.apply(packet,obj.model_copy(deep=True))

def test_another_declared_layer_keeps_all_earlier_objects_and_original_bodies(pair,tmp_path):
 m,lower,outer,_,new_native=pair
 native=replace(new_native,session='2021-06-10',security_id='1357913579')
 event=dict(outer.event,security_id=native.security_id,ticker='EXPLICIT_NONCANONICAL_THIRD_DTO',
  native_session=native.session,effective_session=native.session,prior_session='2021-06-09',
  native_term_sha256=original.digest(asdict(native)))
 third=codec.SuccessorCodec(event,outer.evidence,native,previous_event=outer.event,previous_evidence=outer.evidence)
 third.original_load,third.original_apply=outer.load,outer.apply
 for i,owner in enumerate((lower,outer,third)):
  obj=load(third,write(tmp_path,document(owner),f'EXPLICIT_NONCANONICAL_OWNER_{i}_DTO.json'))
  assert owner.objects==[obj]
  packet=m.Packet(owner.native.session,(owner.native,))
  assert third.apply(packet,obj) is packet
 assert len(lower.objects)==len(outer.objects)==len(third.objects)==1

def test_entire_original_factory_AST_undo_changes_only_the_base_class():
 raw=Path(factory.original.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='certificate_class')
 after=factory.factory_tree(raw)
 cls=next(n for n in ast.walk(after) if isinstance(n,ast.ClassDef) and n.name=='BoundedCertificate')
 assert ast.unparse(cls.bases[0])=='PreviousCertificate'
 cls.bases=[ast.parse('b.Certificate',mode='eval').body]
 assert ast.dump(after)==ast.dump(before)
 with pytest.raises(ValueError):factory.factory_tree(raw+b'\n')

def state_DTO():
 return SimpleNamespace(EXPLICIT_NONCANONICAL_STATE_DTO=True,
  wealth_core=dict(episodes={},slots={},terminal_pending_terms={},terminal_pending_sessions={},unresolved_terminals={},terminal_carry_audit={}),
  pending=[],ledger=dict(receivables=[],events=[]))

@pytest.mark.parametrize('mutation',['episode','pending','receivable','terms','unresolved','carry'])
def test_owned_ordered_or_claimed_rights_still_refuse(pair,mutation):
 _,lower,_,_,_=pair;sid=lower.event['security_id'];state=state_DTO()
 factory.absence(state,sid)
 if mutation=='episode':state.wealth_core['episodes']['DTO']=dict(security_id=sid)
 elif mutation=='pending':state.pending.append(dict(security_id=sid))
 elif mutation=='receivable':state.ledger['receivables'].append(dict(security_id=sid))
 else:state.wealth_core[dict(terms='terminal_pending_terms',unresolved='unresolved_terminals',carry='terminal_carry_audit')[mutation]][sid]={}
 with pytest.raises(ValueError):factory.absence(state,sid)

def test_original_and_successor_factories_stay_hosted_only(pair,tmp_path,monkeypatch):
 _,lower,outer,_,native=pair;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  factory.first_factory(lower.event,{},lower,lower.native,inherited_root=C)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  factory.second_factory(outer.event,{},outer,native,inherited_root=C,previous_class=object)
 assert not any(n.startswith(('research.pooled_','stock_strategy_shared','sentinel')) for n in sys.modules)

def metadata_parent_DTO(pair):
 _,lower,outer,_,_=pair
 class ParentDTO:
  EXPLICIT_NONCANONICAL_CLASS_DTO=True
  def __init__(self):pass
  def values(self):pass
  def recover(self):pass
  def advance(self):pass
  def witness(self):pass
 return factory.mark(ParentDTO,lower.event,lower),outer

def test_class_method_code_and_closure_guard_and_meaningful_removal(pair,monkeypatch):
 cls,outer=metadata_parent_DTO(pair)
 assert factory.parent_metadata(cls,outer.event,outer)==outer.previous_event
 cls.values=lambda self:'EXPLICIT_NONCANONICAL_CHANGED_METHOD_DTO'
 with pytest.raises(ValueError,match='METHOD_CODE_AND_CLOSURES'):factory.parent_metadata(cls,outer.event,outer)
 need=factory.need
 monkeypatch.setattr(factory,'need',lambda ok,label:None if label=='SECOND_FACTORY_COMPLETE_ORIGINAL_PARENT_METHOD_CODE_AND_CLOSURES' else need(ok,label))
 assert factory.parent_metadata(cls,outer.event,outer)==outer.previous_event

def test_unmarked_subclass_does_not_inherit_factory_authority(pair):
 cls,outer=metadata_parent_DTO(pair)
 class Unmarked(cls):pass
 with pytest.raises(ValueError,match='FRESH_QUALIFIED_ORIGINAL_PARENT_CLASS'):factory.parent_metadata(Unmarked,outer.event,outer)

@pytest.mark.parametrize('n',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(n):
 assert not any(k==n or k.startswith(n+'.') for k in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(n)
