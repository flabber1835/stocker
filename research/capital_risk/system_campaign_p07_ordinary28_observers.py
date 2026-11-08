"""Unchanged old23/new12 cash observers and whole original cash DATA reviews."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_financial_future as future
import system_campaign_p07_KDNY_runtime as original
import system_campaign_p07_ordinary28_history as history
data,resources=history.data,history.resources
vivo=original.retained.previous.vivo
OBSERVATION='p07-ordinary28-observation'
NEW_REVIEW='p07-ordinary28-new-cash-review.json'
REVIEW='p07-ordinary28-complete-cash-review.json'

class CashObservers:
 def __init__(self,prior,additional,through):
  need(prior.scopes==additional.scopes==[] and len(prior.terms)==23 and len(additional.terms)==12,
   'ORDINARY28_OBSERVER_EXACT23_AND12_WITHOUT_SOURCE_ONLY_SCOPES')
  need(not set(prior.terms)&set(additional.terms) and all(t['kind']=='CASH_MERGER' for t in [*prior.terms.values(),*additional.terms.values()])
   and all(day<=through for day,sid in prior.terms) and all(day>through for day,sid in additional.terms),
   'ORDINARY28_OBSERVER_OLD_CONSUMED_NEW_FUTURE_CANONICAL_CALL_PARTITION')
  self.prior,self.additional=prior,additional;self.terms={**prior.terms,**additional.terms};self._stack=None;self._entered=False

 def __enter__(self):
  need(not self._entered,'ORDINARY28_OBSERVER_SINGLE_OWNED_ENTRY');self._entered=True
  with ExitStack() as stack:
   stack.enter_context(self.prior);stack.enter_context(self.additional);self._stack=stack.pop_all()
  need(self._stack is not None,'ORDINARY28_OBSERVER_BOTH_CONTEXTS_ENTERED')
  return self

 def __exit__(self,*args):
  need(self._stack is not None,'ORDINARY28_OBSERVER_ONLY_ACTIVE_OWNED_EXIT')
  stack,self._stack=self._stack,None;return stack.__exit__(*args)

def init_function(source_scopes):
 fn=future.ActualEvents.__init__;need(fn.__closure__ is None,'ORDINARY28_OBSERVER_WHOLE_CLOSED_ORIGINAL_INITIALIZER')
 bound=FunctionType(fn.__code__,dict(fn.__globals__,OVERLAY=history.OVERLAY,source_scopes=source_scopes),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'ORDINARY28_OBSERVER_UNCHANGED_INITIALIZER_CODE_OBJECT')
 return bound

def observer(root,parent,spec,out):
 from full_system_core import hosted
 hosted();root,out=Path(root),Path(out);data.parent_contract(parent,spec)
 current=history.strict_json((root/history.NEUTRAL).read_bytes())
 need(history.full(root,current)['full_inputs']==28 and current['run']['state']==parent['run']['state'],
  'ORDINARY28_OBSERVER_GENUINE_NEUTRAL28_BEFORE_ANY_EVENT_HOOK')
 api=history.api_module.api(parent,spec,validate_history=history.full)
 event=future.ActualEvents.__new__(future.ActualEvents);init_function(api.source_scopes)(event,root,'P07',cp=parent)
 need(event.terms=={(t['added']['session'],t['security_id']):t['added'] for t in data.terms()},
  'ORDINARY28_OBSERVER_ALL12_EXACT_COMMITTED_ADDITIONS')
 event.out=out/OBSERVATION;event.out.mkdir(parents=True,exist_ok=True)
 old=original.ordinary(root,out)
 return CashObservers(old,event,parent['source_cursor'])

def review_exact(path,raw):
 path=Path(path)
 if path.name=='p07-vivo-ordinary25-cash-review.json':path=path.with_name(NEW_REVIEW)
 return exact(path,raw)

def review_function():
 fn=vivo.review_cash;need(fn.__closure__ is None,'ORDINARY28_OBSERVER_WHOLE_CLOSED_ORIGINAL_CASH_REVIEW')
 values=SimpleNamespace(**dict(vars(vivo.data),catalog=lambda:dict(terms=data.terms())))
 bound=FunctionType(fn.__code__,dict(fn.__globals__,data=values,OBSERVATION=OBSERVATION,exact=review_exact),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'ORDINARY28_OBSERVER_UNCHANGED_COMPLETE_CASH_REVIEW_CODE_OBJECT')
 return bound

def review(root,current,out):
 root,out=Path(root),Path(out)
 need(history.full(root,current)['full_inputs']==28,'ORDINARY28_OBSERVER_COMPLETE28_HISTORY_BEFORE_CASH_REVIEW')
 old=vivo.review_cash(root,current,out)
 prior=json.loads((root/resources.PREFIX/'origin/prior-hosted-cash-review.json').read_bytes())
 need(prior['passed']is True and prior['events']==old,'ORDINARY28_OBSERVER_ALL23_ORIGINAL_EVENTS_MATCH_PRIOR_POSITIVE_REVIEW')
 new=review_function()(root,current,out)
 result=dict(passed=True,inherited_terms=23,new_terms=12,total_terms=35,inherited_events=old,new_events=new,
  entire_original_review_reused=True,original_observer_methods_unchanged=True,financial_sessions_reexecuted=0)
 exact(out/REVIEW,data.encoded(result));return result

def source_names():return (Path(__file__).name,Path(original.__file__).name,Path(vivo.__file__).name,*history.source_names())
