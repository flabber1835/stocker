"""Complete original future API with both retained bounded inputs validated."""
import ast
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p03_thor_api as prior
import system_campaign_p03_PTLA_data as data
HERE=Path(__file__).parent
OVERLAY='ordinary-successors/'+data.ROOT+'/input-overlay.json'
DIRECTORY='ordinary-successors/'+data.ROOT+'/adoption'
QUALIFICATION='PTLA-original-packet-qualification.json'
FUNCTIONS=prior.FUNCTIONS


def qualifier_save(path,value):
 path=Path(path)
 if path.name=='future-input-qualification.json':
  data.need(value['passed'] is True and value['packet_checks']==2 and value['financial_sessions_advanced']==0,
   'PTLA_API_ENTIRE_ORIGINAL_TWO_PACKET_QUALIFICATIONS')
  path=path.with_name(QUALIFICATION)
 return original.save(path,value)


def api(parent,spec,*,validate_history):
 data.resources.parent_contract(parent,spec);codec=data.codec(parent,spec)
 data.need(callable(validate_history),'PTLA_API_EXPLICIT_WHOLE20_OR21_HISTORY_VISITOR')
 def selected(arm,*,cursor=None):
  data.need((arm,cursor)==('P03','2020-06-30'),'PTLA_API_GENUINE628_PARENT_CLOCK')
  return codec,data.CATALOG,data.terms()
 def full_branch(root,current):
  validate_history(root,current)
  data.need(current['repairs'][:20]==spec['repairs'] and len(current['repairs'])in (20,21),
   'PTLA_API_ENTIRE_UNMODIFIED20_HISTORY_BEFORE_BRANCH_LOOKUP')
  return current['repairs'][14]['sha256']
 def bounded_input(root,current,entry):
  full_branch(root,current)
  data.need(entry in (spec['repairs'][15],spec['repairs'][19]),'PTLA_API_ONLY_ORIGINAL_DOVA_AND_STML_DESCRIPTORS')
 from system_campaign_bounded_sensor_input import SCHEMA
 scope=dict(vars(original),__file__=__file__,HERE=HERE,selected=selected,OVERLAY=OVERLAY,completion_session=data.completion_session,
  validate_input=full_branch,validate_dova_input=bounded_input,DOVA_SCHEMA=SCHEMA,
  original_ordinary_selection=lambda *a:None,supplemental_selection=lambda *a:([],[]))
 exec(compile(ast.Module(body=[prior.remaining_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-remaining-with-full20-DOVA-and-STML-visitor>','exec'),scope)
 for name in FUNCTIONS:
  fn=getattr(original,name);data.need(fn.__closure__ is None,'PTLA_API_WHOLE_CLOSED_ORIGINAL_FUNCTION:'+name)
  bound=FunctionType(fn.__code__,dict(scope,save=qualifier_save) if name=='qualify' else scope,fn.__name__,fn.__defaults__)
  bound.__kwdefaults__=deepcopy(fn.__kwdefaults__);scope[name]=bound
 return SimpleNamespace(**{n:scope[n] for n in FUNCTIONS},selected=selected,OVERLAY=OVERLAY,original_namespace=scope)


def source_names():return (Path(__file__).name,*data.source_names())
