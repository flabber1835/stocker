"""Standalone typed input and explicit noncanonical pure packet tests."""
import importlib.util,json,sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('POSTCLOSE_CODEC_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_codec as p

@pytest.fixture
def packet_codec(monkeypatch):
 path=C/'forecast_tests/compound_v2/test_distribution_v2.py';saved=list(sys.path)
 spec=importlib.util.spec_from_file_location('postclose_typed_noncanonical_packet_helpers',path)
 helpers=importlib.util.module_from_spec(spec);sys.modules[spec.name]=helpers
 try:spec.loader.exec_module(helpers)
 finally:sys.path[:]=saved
 import system_campaign_distribution_facts as compiler
 monkeypatch.setattr(compiler,'REPAIR_SHA',p.sha(helpers.pure_repair_container()))
 value=p.source.catalog();binding=p.source.build_terms(value);cls=p.source.projection_type(value)
 parent=helpers.vendor(binding['original_rows'][value['parent_security_id']]);child=helpers.vendor(binding['original_rows'][value['child_security_id']])
 projection=cls(binding,parent_bar=parent,child_bar=child,source_raw=helpers.pure_repair_container(),
  source_namespace=helpers.source_namespace(),spin_factory=helpers.Spin)
 packet=helpers.Packet('2023-07-05',(parent,child),('EXPLICIT_NONCANONICAL_UNRELATED_TERMINAL_DTO',),projection.originals)
 return p.InputCodec(projection,value=value),packet

def input_file(tmp_path,document):
 path=tmp_path/'EXPLICIT_NONCANONICAL_TYPED_INPUT_TEST_PATH.json'
 path.write_bytes(p.source.encoded(document));return path

def load(codec,path):
 return codec.load(path,resume_session=codec.document['parent_cursor'],
  predecessor_checkpoint_sha256=codec.document['predecessor_checkpoint_sha256'])

def test_actual_document_is_standalone_and_binds_real_parent_and_all_sources():
 doc=p.document();obj=p.DistributionInput.model_validate(doc)
 assert doc['schema']==p.SCHEMA and doc['parent_cursor']=='2023-06-30' and doc['event_session']=='2023-07-05'
 assert obj.model_dump(mode='json',by_alias=True)==doc and 'add' not in doc and 'suppress' not in doc
 assert obj.canonical_financial_source_changed is obj.financial_state_changed is False
 assert len(obj.source_evidence)==7 and obj.sha256 is None

def test_typed_load_and_original_pure_packet_projection(packet_codec,tmp_path):
 codec,packet=packet_codec;before=p.digest(asdict(packet));path=input_file(tmp_path,codec.document)
 obj=load(codec,path);changed=codec.apply(packet,obj)
 assert obj.sha256==p.sha(path.read_bytes()) and obj.earliest_affected_session=='2023-07-05'
 assert codec.objects==[obj] and codec.changed_packets==1
 assert p.digest(asdict(packet))==before and changed.terminal==packet.terminal and changed.bars[1]==packet.bars[1]
 assert changed.bars[0].dividend_per_share==0 and changed.spins==(codec.projection.added,)
 assert changed.bars[0].raw_open==packet.bars[0].raw_open and changed.bars[0].raw_close==packet.bars[0].raw_close

@pytest.mark.parametrize('field,value',[('parent_cursor','2023-07-03'),('event_session','2023-07-03'),
 ('predecessor_checkpoint_sha256','f'*64),('binding_sha256','f'*64),
 ('canonical_financial_source_changed',True),('financial_state_changed',True)])
def test_changed_declaration_is_refused(packet_codec,tmp_path,field,value):
 codec,_=packet_codec;doc=deepcopy(codec.document);doc[field]=value
 with pytest.raises(ValueError):load(codec,input_file(tmp_path,doc))
 assert codec.objects==[]

@pytest.mark.parametrize('change',['resume','predecessor'])
def test_only_exact_unconsumed_parent_can_load(packet_codec,tmp_path,change):
 codec,_=packet_codec;path=input_file(tmp_path,codec.document)
 args=dict(resume_session=codec.document['parent_cursor'],predecessor_checkpoint_sha256=codec.document['predecessor_checkpoint_sha256'])
 args['resume_session' if change=='resume' else 'predecessor_checkpoint_sha256']='2023-07-03' if change=='resume' else 'f'*64
 with pytest.raises(ValueError):codec.load(path,**args)

def test_actual_loaded_object_guard_and_removal_falsifier(packet_codec,monkeypatch):
 codec,packet=packet_codec;unloaded=p.DistributionInput.model_validate(codec.document)
 with pytest.raises(ValueError,match='ACTUAL_LOADED_OBJECT'):codec.apply(packet,unloaded)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_TYPED_ACTUAL_LOADED_OBJECT_AND_UNCHANGED_DECLARATION' else original(ok,label))
 assert codec.apply(packet,unloaded).spins==(codec.projection.added,)

def test_previous_loader_and_packet_layers_are_delegated_exactly(packet_codec,tmp_path):
 codec,packet=packet_codec;path=tmp_path/'EXPLICIT_NONCANONICAL_OTHER_INPUT_DTO.json'
 path.write_text(json.dumps(dict(schema='EXPLICIT_NONCANONICAL_OTHER_SCHEMA_DTO')))
 calls=[];previous=SimpleNamespace(EXPLICIT_NONCANONICAL_PREVIOUS_INPUT_DTO=True)
 def previous_load(actual,**kwargs):calls.append((actual,kwargs));return previous
 def previous_apply(actual,obj):calls.append((actual,obj));return packet
 codec.original_load,codec.original_apply=previous_load,previous_apply
 assert load(codec,path) is previous and codec.apply(packet,previous) is packet
 assert calls==[(path,dict(resume_session=codec.document['parent_cursor'],predecessor_checkpoint_sha256=codec.document['predecessor_checkpoint_sha256'])),
  (packet,previous)]

def test_owned_layer_restores_exact_previous_functions_on_noncanonical_api_DTO(packet_codec):
 codec,_=packet_codec
 previous_load=lambda *a,**k:None;previous_apply=lambda *a,**k:None
 codec.original_load,codec.original_apply=previous_load,previous_apply
 codec.backtest=SimpleNamespace(EXPLICIT_NONCANONICAL_API_DTO=True,load_repair=codec.load,apply_repair=codec.apply)
 codec.active=True;codec.__exit__(None,None,None)
 assert codec.backtest.load_repair is previous_load and codec.backtest.apply_repair is previous_apply and codec.active is False

def test_unknown_loader_layer_cannot_be_overwritten(packet_codec):
 codec,_=packet_codec;other=lambda *a,**k:None
 codec.backtest=SimpleNamespace(EXPLICIT_NONCANONICAL_API_DTO=True,load_repair=other,apply_repair=codec.apply)
 codec.active=True
 with pytest.raises(ValueError,match='ONLY_OWN_ACTIVE_LAYER'):codec.__exit__(None,None,None)
 assert codec.backtest.load_repair is other

def test_real_entry_refuses_locally_before_financial_import(packet_codec,monkeypatch):
 codec,_=packet_codec;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):codec.__enter__()
 assert codec.active is False

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
