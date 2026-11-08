"""Both original bounded models, with their entire admitted174-record seed."""
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
import system_campaign_p03_PTLA_history as history
import system_campaign_p03_STML_source as stml
import system_campaign_bounded_sensor_runtime_v2 as dova
import system_campaign_bounded_sensor_suffix_v2 as event_review
import system_campaign_p03_thor_qualification_reuse as reuse
resources=history.resources


def require_resolution(resolution,declared):
 keys=('actual','gzip_sha256','outer_sha256','state_sha256','input_sha256')
 value={k:resolution[k] for k in keys}
 need(value in declared and resolution['prior_event_basis_revalidated'] is True
  and resolution['prior_transition_reexecuted'] is False,'PTLA_CERTIFICATE_ONLY_DECLARED_PRIOR_ARCHIVE_NO_REPLAY')
 return value


def archived_bases(root,parent,rows,qualified):
 resources.seed_contract(parent,rows,qualified);root=Path(root);declared=resources.fact()['historical_archive_resolutions'];found=[]
 for catalog in (dova.catalog(),stml.catalog()):
  allowed,resolutions=event_review.event_permissions(root,parent,rows,[],catalog,through=parent['source_cursor'],input_descriptors=parent['repairs'])
  need(allowed=={} and len(resolutions)==1,'PTLA_CERTIFICATE_BOTH_EVENTS_ALREADY_CONSUMED_AND_NO_NEW_PERMISSION')
  resolution=require_resolution(resolutions[0],declared);raw=(root/resolution['actual']).read_bytes()
  need(history.sha(raw)==resolution['gzip_sha256'],'PTLA_CERTIFICATE_EXACT_ORIGINAL_EVENT_GZIP_BYTES')
  found.append((catalog,resolution,raw))
 need(len({v[1]['actual'] for v in found})==2,'PTLA_CERTIFICATE_TWO_DISTINCT_ORIGINAL_EVENT_ARCHIVES')
 return found


def bind_consumed(factory,event,current,spec,validate_seed):
 fn=FunctionType(reuse.bind_constructor.__code__,dict(reuse.bind_constructor.__globals__,constructor_seed=validate_seed),
  reuse.bind_constructor.__name__,reuse.bind_constructor.__defaults__)
 return fn(factory,event,current,spec)


def certificate_class(codec,parent,current,spec,baseline,root):
 from full_system_core import hosted
 hosted()
 from system_campaign_second_bounded_codec import SuccessorCodec
 from system_campaign_second_bounded_factory import first_factory,second_factory
 from system_campaign_bounded_sensor_lifecycle_data import evidence
 from system_campaign_financial_branches import Certificate
 import system_campaign_uncertainty_context as base
 import system_campaign_financial_branches as branches
 from system_campaign_uncertainty_math import growth
 root=Path(root);resources.parent_contract(parent,spec)
 need(base.growth is branches.growth is growth,'PTLA_CERTIFICATE_ORIGINAL_P03_FULL_INTERVAL_GROWTH')
 need(history.full(root,current)['full_inputs']==21 and current['run']['state']==parent['run']['state'],
  'PTLA_CERTIFICATE_ACTUAL_CANONICAL_NEUTRAL21_WITH_UNCHANGED_STATE')
 originals=archived_bases(root,parent,baseline[1],baseline[2]);first,second=(v[0] for v in originals)
 need(type(codec)is SuccessorCodec and codec.event==second['event'] and codec.evidence==stml.evidence(second) and codec.objects,
  'PTLA_CERTIFICATE_ACTUAL_RETAINED_STML_CODEC_AND_TYPED_OBJECT')
 old=codec.previous_owner()
 need(old.event==first['event'] and old.evidence==evidence(first) and old.objects,
  'PTLA_CERTIFICATE_ACTUAL_RETAINED_DOVA_CODEC_AND_TYPED_OBJECT')
 def validate_seed(rows,event,actual,target):
  need(actual==current and target==spec and rows==baseline[1] and event in (first['event'],second['event'])
   and event['effective_session']<=rows[-1]['session'],'PTLA_CERTIFICATE_ONLY_BOTH_CONSUMED_EVENTS_AND_EXACT174_SEED')
  resources.seed_contract(parent,rows,baseline[2])
  need(history.full(root,current)['full_inputs']==21 and current['run']['state']==parent['run']['state'],
   'PTLA_CERTIFICATE_GENUINE_NEUTRAL21_STILL_UNCHANGED')
  fresh=archived_bases(root,parent,rows,baseline[2])
  need(fresh==originals,'PTLA_CERTIFICATE_BOTH_FRESH_ARCHIVES_AND_PERMISSIONS_UNCHANGED')
  return resources.fact()['committed_proof']
 initial=first_factory(first['event'],first['market_source'],old,old.native,inherited_root=Path(dova.__file__).parent)
 initial=bind_consumed(initial,first['event'],current,spec,validate_seed)
 joint=second_factory(second['event'],second['market_source'],codec,codec.native,inherited_root=Path(dova.__file__).parent,previous_class=initial)
 joint=bind_consumed(joint,second['event'],current,spec,validate_seed)
 need(joint.append is Certificate.append and issubclass(joint,initial),'PTLA_CERTIFICATE_ORIGINAL_B19_APPEND_AND_COMPLETE_TWO_MODEL_CHAIN')
 return joint
