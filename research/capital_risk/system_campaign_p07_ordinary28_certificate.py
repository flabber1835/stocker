"""Original four-model chain with genuine972 consumed-event seed validation."""
import json
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_KDNY_certificate as original
import system_campaign_bounded_sensor_event_review as events
import system_campaign_p03_thor_qualification_reuse as reuse
import system_campaign_p07_ordinary28_history as history
resources=history.resources
bind_arguments=original.bind_arguments

def require_resolution(resolution,declared):
 keys=('actual','gzip_sha256','outer_sha256','state_sha256','input_sha256')
 need(set(resolution)==set(keys) and resolution in declared,'ORDINARY28_CERTIFICATE_EXACT_DECLARED_ARCHIVE_RESOLUTION')
 return resolution

def archived_bases(root,parent,rows,qualified):
 resources.seed_contract(parent,rows,qualified);root=Path(root)
 need(history.previous.full(root,parent)['full_inputs']==27,'ORDINARY28_CERTIFICATE_WHOLE_GENUINE27_BEFORE_ARCHIVED26_AXIS')
 member=lambda n:(root/n).read_bytes()
 archived26=history.previous.archived_parent(member)
 old_axis=history.previous.previous.actual_event_descriptors(root,archived26['repairs'])
 values=(original.original_lifecycle.catalog(),original.source.catalog())
 result=[]
 for index,catalog in enumerate(values):
  allowed,resolutions=events.permissions(root,rows,catalog,through=parent['source_cursor'],input_descriptors=old_axis if index==0 else parent['repairs'])
  need(len(resolutions)==1,'ORDINARY28_CERTIFICATE_ONE_ACTUAL_ARCHIVE_PER_CONSUMED_EVENT')
  resolution=require_resolution(resolutions[0],resources.fact()['historical_archive_resolutions'])
  raw=member(resolution['actual']);need(sha(raw)==resolution['gzip_sha256'],'ORDINARY28_CERTIFICATE_ORIGINAL_EVENT_GZIP_AT_USE')
  result.append((catalog,allowed,resolution,raw))
 need(len({item[2]['actual'] for item in result})==2,'ORDINARY28_CERTIFICATE_DISTINCT_ORIGINAL_ABMD_AND_KDNY_ARCHIVES')
 origin=member(original.original_origin.ORIGIN)
 need(sha(origin)==resources.spec()['retained_abmd']['origin_sha256'],'ORDINARY28_CERTIFICATE_ORIGINAL_ABMD_NEUTRAL_ORIGIN')
 return result,origin

def bind_consumed(factory,event,current,spec,validate_seed):
 fn=reuse.bind_constructor
 bound=FunctionType(fn.__code__,dict(fn.__globals__,constructor_seed=validate_seed),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'ORDINARY28_CERTIFICATE_WHOLE_ORIGINAL_CONSUMED_CONSTRUCTOR_BINDER')
 return bound(factory,event,current,spec)

def certificate_class(codec,parent,current,spec,baseline,root,*,mixed):
 from full_system_core import hosted
 hosted()
 import system_campaign_uncertainty_context as base
 import system_campaign_financial_branches as branches
 from system_campaign_uncertainty_math import Interval
 from system_campaign_abmd_bounded_catalog import evidence
 from system_campaign_second_bounded_factory import mark,second_factory
 from system_campaign_second_bounded_codec import SuccessorCodec
 root=Path(root);history.data.parent_contract(parent,spec);resources.seed_contract(parent,baseline[1],baseline[2])
 need(base.growth is branches.growth is mixed,'ORDINARY28_CERTIFICATE_ORIGINAL_MIXED_POINT_INTERVAL_GROWTH')
 need(history.full(root,current)['full_inputs']==28 and current['run']['state']==parent['run']['state'],
  'ORDINARY28_CERTIFICATE_ACTUAL_NEUTRAL28_UNCHANGED_ENTIRE27_STATE')
 saved,origin=archived_bases(root,parent,baseline[1],baseline[2]);abmd,kdny=(v[0] for v in saved)
 need(type(codec)is SuccessorCodec and codec.event==kdny['event'] and codec.evidence==original.source.evidence(kdny) and codec.objects,
  'ORDINARY28_CERTIFICATE_ACTUAL_RETAINED_KDNY_CODEC_AND_TYPED_OBJECTS')
 old=codec.previous_owner()
 need(old.event==abmd['event'] and old.evidence==evidence(abmd) and old.objects,'ORDINARY28_CERTIFICATE_ACTUAL_ORIGINAL_ABMD_CODEC_CHAIN')
 initial=original.frozen.certificate_class(abmd['event'],abmd['market_source'],old,old.native,mixed=mixed,inherited_root=Path(original.frozen.__file__).parent)
 def validate_seed(rows,event,actual,target):
  need(actual==current and target==spec and rows==baseline[1] and event in (abmd['event'],kdny['event'])
   and event['effective_session']<=rows[-1]['session'],'ORDINARY28_CERTIFICATE_ONLY_BOTH_CONSUMED_EVENTS_AND_LITERAL972')
  resources.seed_contract(parent,rows,baseline[2])
  need(history.full(root,current)['full_inputs']==28 and current['run']['state']==parent['run']['state'],
   'ORDINARY28_CERTIFICATE_GENUINE_NEUTRAL28_STILL_UNCHANGED')
  fresh,fresh_origin=archived_bases(root,parent,rows,baseline[2])
  need(fresh==saved and fresh_origin==origin,'ORDINARY28_CERTIFICATE_BOTH_ARCHIVES_AND_OLD_PERMISSIONS_UNCHANGED')
  return resources.fact()['committed_proof']
 def retained(rows,event,source,actual_codec):
  need(event==abmd['event'] and source==abmd['market_source'] and actual_codec is old,'ORDINARY28_CERTIFICATE_EXACT_CONSUMED_ABMD_SOURCE_AND_CODEC')
  validate_seed(rows,event,current,spec);return True
 continued=original.compile_continued(retained)(initial.__mro__[1],abmd['event'],abmd['market_source'],old,old.native,witness=initial.witness,interval_class=Interval)
 need(continued.append is initial.append is branches.Certificate.append and continued.__mro__[1:]==initial.__mro__[1:]
  and continued.witness is initial.witness,'ORDINARY28_CERTIFICATE_ALL_ORIGINAL_ABMD_JOINT_METHODS_AND_BINDINGS')
 mark(continued,abmd['event'],old)
 joint=second_factory(kdny['event'],kdny['market_source'],codec,codec.native,inherited_root=Path(original.frozen.__file__).parent,previous_class=continued)
 joint=bind_consumed(joint,kdny['event'],current,spec,validate_seed)
 need(joint.append is branches.Certificate.append and issubclass(joint,continued),'ORDINARY28_CERTIFICATE_ORIGINAL_B19_APPEND_AND_FOUR_MODEL_CHAIN')
 return joint

def source_names():return (Path(__file__).name,Path(original.__file__).name,Path(reuse.__file__).name,*history.source_names())
