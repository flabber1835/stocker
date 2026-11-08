"""Whole history delegation and required real-packet evidence, DATA only."""
from pathlib import Path
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_HISTORY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PTLA_history as h


def qualification_dto():
 return dict(passed=True,packet_checks=2,financial_sessions_advanced=0,
  EXPLICIT_NONCANONICAL_PACKET_QUALIFICATION_DTO=True,**{k:True for k in h.QUALIFICATION_FLAGS})


def test_delegates_whole_current_to_original_successor_verifier(monkeypatch):
 root=Path('EXPLICIT_NONCANONICAL_ROOT_DTO');current={'EXPLICIT_NONCANONICAL_CURRENT_DTO':True};seen=[]
 def original(*args,**kwargs):seen.append((args,kwargs));return {'EXPLICIT_NONCANONICAL_RESULT_DTO':True}
 monkeypatch.setattr(h.original,'verify',original)
 assert h.history(root,current,member=lambda n:b'EXPLICIT_NONCANONICAL_BYTES')=={'EXPLICIT_NONCANONICAL_RESULT_DTO':True}
 args,kw=seen[0];assert args[0]is root and args[1]is current and args[2]==h.spec()
 assert kw['previous_history']is h.full_parent and kw['document']is h.document and kw['zero_adoption']is h.adoption
 assert (kw['parent_path'],kw['neutral_path'],kw['proof_path'],kw['earliest'])==(h.PARENT,h.NEUTRAL,h.PROOF,'2020-07-01')


@pytest.mark.parametrize('flag',h.QUALIFICATION_FLAGS)
def test_each_required_original_packet_guard_cannot_be_omitted(flag):
 value=qualification_dto();assert h.packet_qualification(value);value[flag]=False
 with pytest.raises(ValueError,match='ENTIRE_ACTUAL_TWO_PACKET'):h.packet_qualification(value)


@pytest.mark.parametrize('key,value',[('packet_checks',1),('packet_checks',True),('financial_sessions_advanced',False),('financial_sessions_advanced',1)])
def test_exact_packet_counts_and_zero_financial_work(key,value):
 q=qualification_dto();q[key]=value
 with pytest.raises(ValueError,match='ENTIRE_ACTUAL_TWO_PACKET'):h.packet_qualification(q)


def test_packet_guard_removal_falsifier(monkeypatch):
 q=qualification_dto();q['original_incomplete_guard_retained']=False
 with pytest.raises(ValueError):h.packet_qualification(q)
 old=h.need;monkeypatch.setattr(h,'need',lambda ok,label:None if label=='PTLA_HISTORY_ENTIRE_ACTUAL_TWO_PACKET_AND_NEGATIVE_GUARDS' else old(ok,label))
 assert h.packet_qualification(q)


def test_historical_qualification_reads_archived_bytes_without_touching_new_writer(monkeypatch,tmp_path):
 raw=b'EXPLICIT_NONCANONICAL_HISTORICAL_QUALIFICATION_DTO';fresh=b'EXPLICIT_NONCANONICAL_NEW_WRITER_DTO'
 monkeypatch.setattr(h.resources,'fact',lambda:dict(resources={h.resources.QUALIFIED:h.resources.pin(raw)}))
 archived=tmp_path/h.resources.QUALIFIED;archived.parent.mkdir(parents=True);archived.write_bytes(raw)
 current=tmp_path/'branch-controller-qualification.json';current.write_bytes(fresh)
 other=tmp_path/'EXPLICIT_NONCANONICAL_OTHER_DTO';other.write_bytes(b'OTHER_DTO')
 read=h.historical_members(lambda name:(tmp_path/name).read_bytes())
 assert read(current.name)==raw and read(other.name)==b'OTHER_DTO'
 assert current.read_bytes()==fresh and archived.read_bytes()==raw
 archived.unlink();current.write_bytes(raw);assert read(current.name)==raw
 current.write_bytes(fresh)
 with pytest.raises(ValueError,match='EXACT_ARCHIVED_ORIGINAL_CONTROLLER_QUALIFICATION'):read(current.name)


def test_whole_original_origin_loader_and_bundle_verifier_preserved():
 original=h.previous.previous.origins.load;bound=h.origin_reader()
 assert bound.__code__ is original.__code__ and bound.__defaults__==original.__defaults__ and bound.__closure__ is original.__closure__ is None
 assert bound.__globals__['validate_bundle'].__closure__[0].cell_contents is original.__globals__['validate_bundle']


def test_qualification_guard_removal_falsifier(monkeypatch):
 expected=b'EXPLICIT_NONCANONICAL_OLD_QUALIFICATION_DTO';wrong=b'EXPLICIT_NONCANONICAL_WRONG_DTO'
 monkeypatch.setattr(h.resources,'fact',lambda:dict(resources={h.resources.QUALIFIED:h.resources.pin(expected)}))
 read=h.historical_members(lambda name:wrong)
 with pytest.raises(ValueError,match='EXACT_ARCHIVED_ORIGINAL'):read('branch-controller-qualification.json')
 old=h.need;monkeypatch.setattr(h,'need',lambda ok,label:None if label=='PTLA_HISTORY_EXACT_ARCHIVED_ORIGINAL_CONTROLLER_QUALIFICATION' else old(ok,label))
 assert read('branch-controller-qualification.json')==wrong


def test_complete_bundle_arguments_and_current_object_are_never_narrowed(monkeypatch):
 original=h.previous.previous.origins.load;seen=[]
 def whole(*args,**kwargs):seen.append((args,kwargs));return 'EXPLICIT_NONCANONICAL_RESULT_DTO'
 monkeypatch.setitem(original.__globals__,'validate_bundle',whole)
 args=tuple({'EXPLICIT_NONCANONICAL_ARGUMENT_DTO':i} for i in range(5))
 callback=h.origin_reader().__globals__['validate_bundle']
 assert callback(*args,lambda n:b'EXPLICIT_NONCANONICAL_BYTES_DTO',input_hash='EXPLICIT_NONCANONICAL_HASH_DTO',zero_adoption='EXPLICIT_NONCANONICAL_ADOPTION_DTO')=='EXPLICIT_NONCANONICAL_RESULT_DTO'
 actual,kwargs=seen[0];assert all(a is b for a,b in zip(actual[:5],args))
 assert kwargs==dict(input_hash='EXPLICIT_NONCANONICAL_HASH_DTO',zero_adoption='EXPLICIT_NONCANONICAL_ADOPTION_DTO')


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
