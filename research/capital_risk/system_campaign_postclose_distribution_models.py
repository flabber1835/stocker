"""Complete new history with unchanged readers of genuine historical parents."""
import ast,json
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_p07_saved_proofs as saved
import system_campaign_postclose_distribution_history as history
import system_campaign_postclose_distribution_runtime as runtime
from system_campaign_facts import sha
from full_system_benchmark import need

def document(parent,member):
 spec=runtime.selected_spec();saved.parent_contract(parent,spec);names=history.paths(spec)
 value=runtime.payload();doc=runtime.typed.document()
 raw=member(names['OVERLAY']);obj=runtime.typed.DistributionInput.model_validate_json(raw)
 need(raw==runtime.source.encoded(doc) and obj.model_dump(mode='json',by_alias=True)==doc
  and member(names['PAYLOAD'])==runtime.source.encoded(value),
  'POSTCLOSE_MODELS_COMPLETE_TYPED_DOCUMENT_AND_ORIGINAL_PAYLOAD')
 runtime.packet_qualification(parent,spec,member);return doc

def full(root,current):
 root=Path(root);spec=runtime.selected_spec()
 return history.history(root,current,spec,member=lambda n:(root/n).read_bytes(),document=document)

def genuine_parent(root,current):
 need(len(current['repairs'])==26,'POSTCLOSE_MODELS_ONLY_GENUINE_CURRENT26_READER')
 full(root,current);spec=runtime.selected_spec()
 return history.archived_parent(spec,lambda n:(Path(root)/n).read_bytes())

def bind_functions(previous,**changes):
 """Use one private namespace; every original complete function keeps its code."""
 scope=dict(vars(previous))
 for n,fn in vars(previous).items():
  if isinstance(fn,FunctionType) and fn.__globals__.get('__name__')==scope.get('__name__'):
   need(fn.__closure__ is None,'POSTCLOSE_MODELS_NO_HIDDEN_FUNCTION_NAMESPACE_CLOSURE')
   bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=fn.__kwdefaults__
   need(bound.__code__ is fn.__code__,'POSTCLOSE_MODELS_IDENTICAL_COMPLETE_ORIGINAL_FUNCTION')
   scope[n]=bound
 scope.update(changes);return scope

def models():
 previous=saved.models.models();scope=bind_functions(previous)
 def metadata(root,current,fn,*args,**kwargs):
  parent=genuine_parent(root,current) if len(current['repairs'])==26 else current
  return fn(root,parent,*args,**kwargs)
 def validate(root,current,*args,**kwargs):
  result=metadata(root,current,previous.validate_full,*args,**kwargs)
  if len(current['repairs'])!=26:return result
  need(result['full_input_count']==25 and result['bounded_descriptor']==current['repairs'][23],
   'POSTCLOSE_MODELS_ENTIRE_ORIGINAL_HISTORICAL_MODEL_RESULT')
  return dict(result,full_input_count=26,historical_parent_inputs=25,complete_successor_history_verified=True)
 scope['validate_full']=validate
 scope['typed_descriptor']=lambda root,current,*a,**k:metadata(root,current,previous.typed_descriptor,*a,**k)
 scope['read_legacy_receipt']=lambda root,current,*a,**k:metadata(root,current,previous.read_legacy_receipt,*a,**k)
 return SimpleNamespace(**scope)

def origin():
 previous=saved.models.origin()
 def verify(root,current,catalog):
  parent=genuine_parent(root,current) if len(current['repairs'])==26 else current
  return previous.verify(root,parent,catalog)
 return SimpleNamespace(**bind_functions(previous,verify=verify))

def legacy_tree(raw):
 tree=saved.retained.legacy_tree(raw)
 fn,=[n for n in tree.body if n.name=='suffix']
 saved.models.replace_count(fn,'(23, 24, 25)','(23, 24, 25, 26)',1,
  'POSTCLOSE_MODELS_ONE_FINITE_LEGACY_SUFFIX_COUNT')
 fn,=[n for n in tree.body if n.name=='future_tree']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant)
  and n.value=="len(cp['repairs']) in (24,25) and entry==cp['repairs'][23]"]
 site.value="(len(cp['repairs']) in (24,25,26) and entry==cp['repairs'][23]) or (len(cp['repairs'])==26 and entry==cp['repairs'][25])"
 return ast.fix_missing_locations(tree)

def actual_event_descriptors(root,descriptors):
 if len(descriptors)!=26:return saved.retained.actual_event_descriptors(root,descriptors)
 spec=runtime.selected_spec();member=lambda n:(Path(root)/n).read_bytes();names=history.paths(spec)
 neutral=history.strict_json(member(names['NEUTRAL']));full(root,neutral)
 need(descriptors==neutral['repairs'],'POSTCLOSE_MODELS_REAL_NEUTRAL26_DESCRIPTOR_AXIS_BEFORE_OLD_EVENT_PERMISSION')
 parent=history.archived_parent(spec,member)
 return saved.retained.actual_event_descriptors(root,parent['repairs'])

def permissions(root,rows,catalog,*,through,input_descriptors):
 from system_campaign_bounded_sensor_event_review import permissions as original
 return original(root,rows,catalog,through=through,input_descriptors=actual_event_descriptors(root,input_descriptors))

def lifecycle():
 fn=saved.retained.lifecycle
 scope=dict(fn.__globals__,models=SimpleNamespace(models=models,origin=origin),legacy_tree=legacy_tree,
  actual_event_descriptors=actual_event_descriptors,permissions=permissions)
 bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=fn.__kwdefaults__
 value=bound();ns=bind_functions(value)
 exec(compile(ast.Module(body=[saved.retained_tree(Path(saved.original_lifecycle.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-retained-declaration-genuine25-parent>','exec'),ns)
 return SimpleNamespace(**ns)
