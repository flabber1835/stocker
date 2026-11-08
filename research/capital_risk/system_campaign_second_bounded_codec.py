"""Two exact bounded input owners, preserving the complete original codec."""
import json
from pathlib import Path
from system_campaign_bounded_sensor_input import InputCodec,BoundedSensorInput,SCHEMA,need

class SuccessorCodec(InputCodec):
 def __init__(self,event,evidence,native,*,previous_event,previous_evidence):
  super().__init__(event,evidence,native)
  need(event['security_id']!=previous_event['security_id']
   and previous_event['effective_session']<event['native_session'],'SECOND_CODEC_DISTINCT_ORDERED_EVENTS')
  self.previous_event=previous_event.copy()
  self.previous_evidence=[v.copy() for v in previous_evidence]

 def previous_owner(self):
  owner=getattr(self.original_load,'__self__',None)
  need(type(owner)in (InputCodec,SuccessorCodec) and self.original_load==owner.load
   and self.original_apply==owner.apply and owner.event==self.previous_event
   and owner.evidence==self.previous_evidence,'SECOND_CODEC_ACTUAL_ORIGINAL_DOVA_OWNER_AND_APPLY')
  return owner

 def owner_for(self,event,evidence):
  owner=self.previous_owner()
  while owner.event!=event:
   need(type(owner)is SuccessorCodec,'SECOND_CODEC_NO_UNDECLARED_BOUNDED_EVENT')
   owner=owner.previous_owner()
  need(owner.evidence==evidence,'SECOND_CODEC_EXACT_PREVIOUS_OWNER_EVIDENCE')
  return owner

 def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
  value=json.loads(Path(path).read_bytes())
  if value.get('schema')==SCHEMA:self.previous_owner()
  if value.get('schema')==SCHEMA and value.get('event')!=self.event:
   owner=self.owner_for(value.get('event'),value.get('source_evidence'))
   obj=self.original_load(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
   need(any(obj is v for v in owner.objects),'SECOND_CODEC_PREVIOUS_OBJECT_OWNED_BY_ORIGINAL_OWNER')
   return obj
  return super().load(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)

 def apply(self,packet,obj):
  if isinstance(obj,BoundedSensorInput):self.previous_owner()
  if isinstance(obj,BoundedSensorInput) and obj.event.model_dump()!=self.event:
   owner=self.owner_for(obj.event.model_dump(),[v.model_dump() for v in obj.source_evidence])
   need(any(obj is v for v in owner.objects)
    and not any(obj is v for v in self.objects),'SECOND_CODEC_DELEGATE_ONLY_ORIGINAL_PREVIOUS_OBJECT')
   return self.original_apply(packet,obj)
  return super().apply(packet,obj)
