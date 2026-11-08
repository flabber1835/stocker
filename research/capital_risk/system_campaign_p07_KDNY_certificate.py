"""One original joint ABMD certificate, then the original second-event factory."""
import ast,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_abmd_certificate as frozen
import system_campaign_p07_vivo_certificate as continuation
import system_campaign_p07_abmd_lifecycle as original_lifecycle
import system_campaign_p07_abmd_models as original_models
import system_campaign_p07_abmd_origin as original_origin
import system_campaign_p07_KDNY_resources as resources
history,source=resources.history,resources.source
ZOGENIX_ARGUMENTS=frozenset(('zogenix_codec','zogenix_native','zogenix_source'))


def bind_arguments(factory,**arguments):
 """Supply inherited constructor inputs without changing any class method."""
 need(callable(factory) and set(arguments)==ZOGENIX_ARGUMENTS,'KDNY_CONSTRUCTOR_ALL_THREE_EXISTING_ZOGENIX_ARGUMENTS')
 def constructor(*args,**kwargs):
  need(not ZOGENIX_ARGUMENTS.intersection(kwargs),'KDNY_CONSTRUCTOR_NO_REPLACED_INHERITED_ARGUMENT')
  return factory(*args,**kwargs,**arguments)
 return constructor


def continuation_namespace():
 """Use the two complete qualified adapter functions; no metadata rewriting."""
 raw=continuation.source()
 nodes=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name in ('factory_tree','compile_factory')]
 need(len(nodes)==2,'KDNY_CERTIFICATE_TWO_WHOLE_ORIGINAL_CONSUMED_FACTORY_ADAPTERS')
 scope=dict(frozen=frozen,models=original_models,ast=ast,Path=Path,sha=sha,need=need,
  FROZEN_SHA='4f3db7f1cefffbad4c6eb48c0efe82678282c96c2a7b97c039db2307b9d86baa')
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'<whole-original-ABMD-constructor-adapter-functions>','exec'),scope)
 return scope


def continuation_tree():return continuation_namespace()['factory_tree'](Path(frozen.__file__).read_bytes())


def compile_continued(qualified):return continuation_namespace()['compile_factory'](qualified)


def certificate_class(codec,native,market,parent,current,spec,baseline,root,*,mixed):
 from full_system_core import hosted
 hosted()
 import system_campaign_uncertainty_context as base
 import system_campaign_financial_branches as branches
 from system_campaign_uncertainty_math import Interval
 from system_campaign_abmd_bounded_catalog import evidence
 from system_campaign_bounded_sensor_event_review import permissions
 from system_campaign_second_bounded_factory import mark,second_factory
 from system_campaign_second_bounded_codec import SuccessorCodec
 need(type(codec)is SuccessorCodec and base.growth is branches.growth is mixed,
  'KDNY_CERTIFICATE_ACTUAL_SUCCESSOR_CODEC_AND_ORIGINAL_MIXED_GROWTH_CONTEXT')
 root=Path(root);source.parent_contract(parent,spec);resources.seed_contract(parent,baseline[1],baseline[2])
 need(history.full(root,current)['full_inputs']==27 and current['run']['state']==parent['run']['state'],
  'KDNY_CERTIFICATE_ONLY_GENUINE_NEUTRAL27_AND_ENTIRE26_PREDECESSOR')
 value=original_lifecycle.catalog();old_codec=codec.previous_owner()
 need(old_codec.event==value['event'] and old_codec.evidence==evidence(value) and old_codec.objects,
  'KDNY_CERTIFICATE_ACTUAL_ORIGINAL_ABMD_CODEC_AND_LOADED_TYPED_OBJECT')
 old_descriptors=history.previous.actual_event_descriptors(root,parent['repairs'])
 allowed,resolutions=permissions(root,baseline[1],value,through=parent['source_cursor'],input_descriptors=old_descriptors)
 need(len(resolutions)==1 and resolutions[0] in resources.fact()['historical_archive_resolutions'],
  'KDNY_CERTIFICATE_EXACT_ORIGINAL_COMMITTED_ABMD_ARCHIVE_PERMISSION')
 resolution,=resolutions;archive=(root/resolution['actual']).read_bytes()
 need(sha(archive)==resolution['gzip_sha256'],'KDNY_CERTIFICATE_ORIGINAL_ABMD_ARCHIVE_BYTES')
 origin_raw=(root/original_origin.ORIGIN).read_bytes()
 need(sha(origin_raw)==spec['retained_abmd']['origin_sha256'],'KDNY_CERTIFICATE_UNCHANGED_ACTUAL_ABMD_NEUTRAL_ORIGIN')
 initial=frozen.certificate_class(value['event'],value['market_source'],old_codec,old_codec.native,
  mixed=mixed,inherited_root=Path(frozen.__file__).parent)
 def retained(rows,actual_event,actual_source,actual_codec):
  need(actual_event==value['event'] and actual_source==value['market_source'] and actual_codec is old_codec,
   'KDNY_CERTIFICATE_ORIGINAL_CONSUMED_FACTORY_EVENT_SOURCE_AND_CODEC')
  resources.seed_contract(parent,rows,baseline[2])
  need(rows==baseline[1] and history.full(root,current)['full_inputs']==27
   and current['run']['state']==parent['run']['state'] and (root/original_origin.ORIGIN).read_bytes()==origin_raw
   and (root/resolution['actual']).read_bytes()==archive,
   'KDNY_CERTIFICATE_ENTIRE949_CURRENT_NEUTRAL27_AND_FRESH_ORIGINAL_ARCHIVES')
  fresh_allowed,fresh_resolutions=permissions(root,rows,value,through=parent['source_cursor'],input_descriptors=old_descriptors)
  need(fresh_allowed==allowed and fresh_resolutions==resolutions,'KDNY_CERTIFICATE_NO_PRIOR_TRANSITION_REPLAY_OR_PERMISSION_CHANGE')
  return True
 continued=compile_continued(retained)(initial.__mro__[1],value['event'],value['market_source'],old_codec,old_codec.native,
  witness=initial.witness,interval_class=Interval)
 need(continued.append is initial.append is branches.Certificate.append
  and continued.__mro__[1:]==initial.__mro__[1:] and continued.witness is initial.witness,
  'KDNY_CERTIFICATE_ALL_ORIGINAL_ABMD_JOINT_COOPERATIVE_CODE_AND_BINDINGS')
 mark(continued,value['event'],old_codec)
 return second_factory(source.catalog()['event'],market,codec,native,inherited_root=Path(frozen.__file__).parent,previous_class=continued)
