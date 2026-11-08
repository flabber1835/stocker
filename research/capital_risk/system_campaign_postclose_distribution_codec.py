"""Typed distribution input; all packet economics delegate the original codec."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,PrivateAttr
import system_campaign_postclose_distribution_input as source
from system_campaign_bounded_sensor_input import Digest,Evidence
from system_campaign_facts import sha,digest
from full_system_benchmark import need
SCHEMA='research.postclose-distribution-input/1'
HERE=Path(__file__).parent

class DistributionInput(BaseModel):
 model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
 schema_id:Literal['research.postclose-distribution-input/1']=Field(alias='schema')
 predecessor_checkpoint_sha256:Digest
 parent_outer_sha256:Digest
 parent_input_sha256:Digest
 parent_state_sha256:Digest
 parent_root_admission_sha256:Digest
 parent_cursor:str
 event_session:str
 binding_sha256:Digest
 source_evidence:Annotated[list[Evidence],Field(min_length=6,max_length=32)]
 canonical_financial_source_changed:Literal[False]
 financial_state_changed:Literal[False]
 _file_sha256:str|None=PrivateAttr(default=None)
 _resume_session:str|None=PrivateAttr(default=None)

 @property
 def earliest_affected_session(self):return self.event_session
 @property
 def sha256(self):return self._file_sha256

def document(value=None):
 value=source.catalog() if value is None else value;spec=source.validate(value);binding=source.build_terms(value)
 refs={
  'research.postclose-distribution/source-catalog/1':sha(source.encoded(value)),
  'research.postclose-distribution/source-review/1':sha((HERE/source.REVIEW).read_bytes()),
  'research.postclose-distribution/source-qualification/1':sha((HERE/source.QUALIFICATION).read_bytes()),
  'research.postclose-distribution/source-compiler/1':sha(Path(source.__file__).read_bytes()),
  'research.postclose-distribution/original-packet-projection/1':sha(Path(source.original.__file__).read_bytes()),
  'research.postclose-distribution/original-packet-compiler/1':sha((HERE/'system_campaign_distribution_facts.py').read_bytes()),
  'research.postclose-distribution/typed-descriptor-codec/1':sha(Path(__file__).read_bytes())}
 return dict(schema=SCHEMA,predecessor_checkpoint_sha256=spec['inner_sha256'],parent_outer_sha256=spec['outer_sha256'],
  parent_input_sha256=spec['input_sha256'],parent_state_sha256=spec['state_sha256'],parent_root_admission_sha256=spec['root_admission_sha256'],
  parent_cursor=spec['selected_session'],event_session=binding['spin']['session'],binding_sha256=digest(binding),
  source_evidence=[dict(reference=ref,sha256=pin,description='Exact source-bound distribution input; original financial engine and saved book unchanged.')
   for ref,pin in sorted(refs.items())],canonical_financial_source_changed=False,financial_state_changed=False)

def parse(path,*,resume_session,predecessor_checkpoint_sha256,expected_document):
 raw=Path(path).read_bytes();need(len(raw)<=65536,'POSTCLOSE_TYPED_BOUNDED_INPUT_SIZE')
 obj=DistributionInput.model_validate_json(raw);doc=obj.model_dump(mode='json',by_alias=True)
 need(doc==expected_document and raw==source.encoded(expected_document),'POSTCLOSE_TYPED_EXACT_COMPLETE_SOURCE_BOUND_DOCUMENT')
 need(type(resume_session)is str and date.fromisoformat(resume_session).isoformat()==resume_session
  and resume_session==obj.parent_cursor<obj.event_session and date.fromisoformat(obj.event_session).isoformat()==obj.event_session,
  'POSTCLOSE_TYPED_ONLY_EXACT_UNCONSUMED_PARENT_CURSOR')
 need(obj.predecessor_checkpoint_sha256==predecessor_checkpoint_sha256,'POSTCLOSE_TYPED_ONLY_EXACT_GENUINE_PREDECESSOR')
 refs=[v.reference for v in obj.source_evidence]
 need(len(refs)==len(set(refs)),'POSTCLOSE_TYPED_UNIQUE_COMPLETE_SOURCE_REFERENCES')
 obj._file_sha256,obj._resume_session=sha(raw),resume_session
 return obj

class InputCodec:
 def __init__(self,projection,*,value=None):
  value=source.catalog() if value is None else value
  self.document=document(value);binding=source.build_terms(value)
  need(projection.binding==binding and type(projection).__init__.__code__ is source.original.EventSessionProjection.__init__.__code__
   and projection.apply.__func__ is source.original.EventSessionProjection.apply
   and projection._bound.__func__ is source.original.EventSessionProjection._bound,
   'POSTCLOSE_TYPED_ONLY_WHOLE_ORIGINAL_QUALIFIED_PACKET_PROJECTION')
  self.projection=projection;self.objects=[];self.changed_packets=0;self.active=False
  self.original_load=self.original_apply=None

 def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
  raw=Path(path).read_bytes()
  if json.loads(raw).get('schema')!=SCHEMA:
   need(callable(self.original_load),'POSTCLOSE_TYPED_COMPLETE_PREVIOUS_LOADER_REQUIRED')
   return self.original_load(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
  obj=parse(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,expected_document=self.document)
  self.objects.append(obj);return obj

 def apply(self,packet,obj):
  if not isinstance(obj,DistributionInput):
   need(callable(self.original_apply),'POSTCLOSE_TYPED_COMPLETE_PREVIOUS_PACKET_APPLIER_REQUIRED')
   return self.original_apply(packet,obj)
  need(any(obj is item for item in self.objects) and obj.model_dump(mode='json',by_alias=True)==self.document
   and obj.sha256==sha(source.encoded(self.document)) and obj._resume_session==self.document['parent_cursor'],
   'POSTCLOSE_TYPED_ACTUAL_LOADED_OBJECT_AND_UNCHANGED_DECLARATION')
  changed=self.projection.apply(packet,self.projection.descriptor)
  if changed!=packet:self.changed_packets+=1
  return changed

 def __enter__(self):
  from full_system_core import hosted
  hosted()
  from research.pooled_vacancy_funding import backtest
  need(self.active is False and callable(backtest.load_repair) and callable(backtest.apply_repair),
   'POSTCLOSE_TYPED_INSTALL_ONLY_AFTER_COMPLETE_RETAINED_CHAIN')
  self.backtest=backtest;self.original_load,self.original_apply=backtest.load_repair,backtest.apply_repair
  backtest.load_repair=self.load
  try:backtest.apply_repair=self.apply
  except Exception:
   backtest.load_repair=self.original_load;raise
  self.active=True;return self

 def __exit__(self,*args):
  need(self.active is True and self.backtest.load_repair==self.load and self.backtest.apply_repair==self.apply,
   'POSTCLOSE_TYPED_ONLY_OWN_ACTIVE_LAYER_CAN_RESTORE_PREVIOUS_CHAIN')
  self.backtest.load_repair,self.backtest.apply_repair=self.original_load,self.original_apply
  self.active=False
