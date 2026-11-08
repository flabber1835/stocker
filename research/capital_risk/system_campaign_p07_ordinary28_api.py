"""Whole original future API, finite twelve-term batch and complete history."""
import ast
from copy import deepcopy
from functools import wraps
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_future as original
import system_campaign_p07_ordinary28_data as data
HERE=Path(__file__).parent
OVERLAY='ordinary-successors/'+data.ROOT+'/input-overlay.json'
DIRECTORY='ordinary-successors/'+data.ROOT+'/adoption'
QUALIFICATION='P07-ordinary28-original-packet-qualification.json'
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes')

def remaining_tree(raw):
 data.need(data.sha(raw)==data.FUTURE_SHA,'ORDINARY28_WHOLE_ORIGINAL_REMAINING_FUNCTION')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='remaining_ordinary_terms']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FUTURE_INHERITED_ORDINARY_EXACT_RETAINED_TYPED_INPUT' for a in n.args)]
 data.need(ast.unparse(site.args[0])=="doc['schema'] == INPUT and validate_input(Path(root), cp) == entry['sha256']",'ORDINARY28_ONE_EXACT_ORIGINAL_TYPED_DISPATCH_SITE')
 site.args[0]=ast.parse('known_nonterminal_input(Path(root),cp,entry) is True',mode='eval').body
 return ast.fix_missing_locations(fn)

def known_input(root,current,entry,spec,validate_history):
 v=data.fact();result=validate_history(root,current)
 data.need(result['passed']is True and result['full_inputs']==len(current['repairs'])
  and len(current['repairs'])in (27,28) and current['repairs'][:27]==spec['repairs']
  and entry in [x['descriptor'] for x in v['nonterminal_descriptors']],
  'ORDINARY28_COMPLETE_CURRENT_HISTORY_AND_ONLY_FIVE_ORIGINAL_TYPED_INPUTS')
 return True

def qualifier_save(path,value):
 path=Path(path)
 if path.name=='future-input-qualification.json':
  data.need(value['passed']is True and value['packet_checks']==24 and value['financial_sessions_advanced']==0,
   'ORDINARY28_ENTIRE_ORIGINAL24_PACKET_CHECKS')
  path=path.with_name(QUALIFICATION)
 return original.save(path,value)

def api(parent,spec,*,validate_history):
 data.parent_contract(parent,spec);codec=data.codec(parent,spec)
 data.need(callable(validate_history),'ORDINARY28_EXPLICIT_COMPLETE_CURRENT_HISTORY_CALLBACK')
 batch=data.terms()
 def selected(arm,*,cursor=None):
  data.need((arm,cursor)==('P07','2023-08-31'),'ORDINARY28_GENUINE1426_PARENT_CLOCK')
  return codec,data.CATALOG,deepcopy(batch)
 raw=Path(original.__file__).read_bytes();data.need(data.sha(raw)==data.FUTURE_SHA,'ORDINARY28_ENTIRE_ORIGINAL_FUTURE_API_BYTES')
 scope=dict(vars(original),__file__=__file__,HERE=HERE,selected=selected,OVERLAY=OVERLAY,completion_session=data.completion_session,
  known_nonterminal_input=lambda root,cp,entry:known_input(root,cp,entry,spec,validate_history),
  original_ordinary_selection=lambda *a:None,supplemental_selection=lambda *a:([],[]))
 exec(compile(ast.Module(body=[remaining_tree(raw)],type_ignores=[]),'<whole-original-remaining-complete-history-dispatch>','exec'),scope)
 for name in FUNCTIONS:
  fn=getattr(original,name);data.need(fn.__closure__ is None,'ORDINARY28_WHOLE_CLOSED_ORIGINAL_FUNCTION:'+name)
  bound=FunctionType(fn.__code__,dict(scope,save=qualifier_save) if name=='qualify' else scope,fn.__name__,fn.__defaults__)
  bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
  if name=='hydrate':
   whole=bound
   @wraps(whole)
   def guarded(current,arm,*,source_root=None):
    from full_system_core import hosted
    hosted()
    from research.pooled_input_support.bundle import axis
    data.need(source_root is not None,'ORDINARY28_ACTUAL_COMPLETE_SOURCE_ROOT_REQUIRED')
    data.parent_contract(current,spec);proof=validate_history(Path(source_root),current)
    data.need(proof['passed']is True and proof['full_inputs']==27,'ORDINARY28_COMPLETE_GENUINE27_BEFORE_HYDRATION')
    dates=axis()
    for term in batch:data.completion_session(term,dates)
    return whole(current,arm,source_root=source_root)
   bound=guarded
  scope[name]=bound
 return SimpleNamespace(**{n:scope[n] for n in FUNCTIONS},selected=selected,OVERLAY=OVERLAY,original_namespace=scope)

def source_names():return (Path(__file__).name,*data.source_names())
