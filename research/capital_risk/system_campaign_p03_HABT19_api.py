"""Whole original future APIs for one HABT term and the complete DOVA history."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p03_thor_api as prior
import system_campaign_p03_HABT19_data as data
HERE=Path(__file__).parent
OVERLAY='p03-HABT-ordinary19-overlay.json'
DIRECTORY='p03-HABT-ordinary19-adoption'
QUALIFICATION='p03-HABT-ordinary19-input-qualification.json'
FUNCTIONS=prior.FUNCTIONS
def qualifier_save(path,value):
 path=Path(path)
 if path.name=='future-input-qualification.json':
  data.need(value['passed'] is True and value['packet_checks']==2 and value['financial_sessions_advanced']==0,'HABT_WHOLE_ORIGINAL_TWO_PACKET_CHECKS');path=path.with_name(QUALIFICATION)
 return original.save(path,value)
def api(parent,spec,**unused):
 data.parent_contract(parent,spec);codec=data.codec(parent,spec)
 def selected(arm,*,cursor=None):
  data.need((arm,cursor)==('P03','2020-02-28'),'HABT_EXACT_ACTUAL543_PARENT_CLOCK');return codec,data.CATALOG,data.terms()
 from system_campaign_bounded_sensor_input import SCHEMA
 scope=dict(vars(original),__file__=__file__,HERE=HERE,selected=selected,OVERLAY=OVERLAY,completion_session=data.completion_session,validate_input=prior.full_branch_input,validate_dova_input=prior.validate_dova_input,DOVA_SCHEMA=SCHEMA,original_ordinary_selection=lambda *a:None,supplemental_selection=lambda *a:([],[]))
 exec(compile(ast.Module(body=[prior.remaining_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-remaining-ordinary-DOVA-history>','exec'),scope)
 for name in FUNCTIONS:
  fn=getattr(original,name);data.need(fn.__closure__ is None,'HABT_WHOLE_CLOSED_ORIGINAL_API:'+name)
  bound=FunctionType(fn.__code__,dict(scope,save=qualifier_save) if name=='qualify' else scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=deepcopy(fn.__kwdefaults__);scope[name]=bound
 return SimpleNamespace(**{n:scope[n] for n in FUNCTIONS},selected=selected,OVERLAY=OVERLAY,whole_original_hydrate=scope['hydrate'],original_namespace=scope)
def source_names():return (Path(__file__).name,*data.source_names())
