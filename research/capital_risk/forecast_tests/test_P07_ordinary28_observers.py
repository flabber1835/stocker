"""Opaque observer contexts and original code objects; no canonical instances."""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_OBSERVER_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_observers as p

class ExplicitNoncanonicalEventsDTO:
 def __init__(self,label,count,day,log,*,fail=False,suppress=False):
  self.label,self.log,self.fail,self.suppress=label,log,fail,suppress
  self.terms={(day,label+str(i)):dict(kind='CASH_MERGER',session=day,security_id=label+str(i)) for i in range(count)};self.scopes=[]
 def __enter__(self):
  self.log.append('enter:'+self.label)
  if self.fail:raise ValueError('EXPLICIT_NONCANONICAL_ENTRY_REFUSED')
  return self
 def __exit__(self,*args):self.log.append('exit:'+self.label);return self.suppress

def dto(*,fail=False,suppress=False):
 log=[];old=ExplicitNoncanonicalEventsDTO('OLD_DTO',23,'2023-08-09',log,suppress=suppress);new=ExplicitNoncanonicalEventsDTO('NEW_DTO',12,'2023-09-26',log,fail=fail)
 return old,new,log

def test_exact35_term_context_order_and_reverse_cleanup():
 old,new,log=dto();event=p.CashObservers(old,new,'2023-08-31')
 with event as entered:assert entered is event and len(event.terms)==35
 assert log==['enter:OLD_DTO','enter:NEW_DTO','exit:NEW_DTO','exit:OLD_DTO']
 with pytest.raises(ValueError,match='SINGLE_OWNED_ENTRY'):event.__enter__()
 with pytest.raises(ValueError,match='ONLY_ACTIVE_OWNED_EXIT'):event.__exit__(None,None,None)

def test_failed_second_entry_restores_the_first_context():
 old,new,log=dto(fail=True)
 with pytest.raises(ValueError,match='ENTRY_REFUSED'):
  with p.CashObservers(old,new,'2023-08-31'):pass
 assert log==['enter:OLD_DTO','enter:NEW_DTO','exit:OLD_DTO']

def test_suppressed_partial_entry_does_not_become_a_success():
 old,new,log=dto(fail=True,suppress=True)
 with pytest.raises(ValueError,match='BOTH_CONTEXTS_ENTERED'):
  with p.CashObservers(old,new,'2023-08-31'):pass
 assert log[-1]=='exit:OLD_DTO'

@pytest.mark.parametrize('change',['scope','count','stock','old_future','new_past','duplicate'])
def test_wrong_scope_count_kind_or_temporal_owner_is_refused(change):
 old,new,log=dto()
 if change=='scope':new.scopes=[{'EXPLICIT_NONCANONICAL_SCOPE_DTO':True}]
 elif change=='count':new.terms.pop(next(iter(new.terms)))
 elif change=='stock':next(iter(new.terms.values()))['kind']='CASH_PLUS_STOCK'
 elif change=='old_future':old.terms={('2023-09-26',sid):term for (day,sid),term in old.terms.items()}
 elif change=='new_past':new.terms={('2023-08-09',sid):term for (day,sid),term in new.terms.items()}
 else:
  new.terms.pop(next(iter(new.terms)));key,term=next(iter(old.terms.items()));new.terms[key]=term
 with pytest.raises(ValueError):p.CashObservers(old,new,'2023-08-31')
 assert log==[]

def test_temporal_guard_removal_really_accepts_two_simultaneously_active_wrappers(monkeypatch):
 old,new,log=dto();new.terms={('2023-08-09',sid):term for (day,sid),term in new.terms.items()}
 with pytest.raises(ValueError,match='CANONICAL_CALL_PARTITION'):p.CashObservers(old,new,'2023-08-31')
 original=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='ORDINARY28_OBSERVER_OLD_CONSUMED_NEW_FUTURE_CANONICAL_CALL_PARTITION' else original(ok,label))
 assert len(p.CashObservers(old,new,'2023-08-31').terms)==35

def test_all_original23_dates_are_before_1426_and_all_new12_are_after():
 before=p.vivo.data.catalog()['terms'];after=p.data.terms()
 assert len(before)==23 and len(after)==12 and max(t['added']['session'] for t in before)<='2023-08-31'<min(t['added']['session'] for t in after)
 assert not {t['security_id'] for t in before}&{t['security_id'] for t in after}

def test_complete_original_initializer_code_is_unchanged_and_only_declared_globals_bound():
 callback=lambda *args:[];fn=p.init_function(callback);old=p.future.ActualEvents.__init__
 assert fn.__code__ is old.__code__ and fn.__defaults__==old.__defaults__ and fn.__kwdefaults__==old.__kwdefaults__
 assert fn.__globals__['OVERLAY']==p.history.OVERLAY and fn.__globals__['source_scopes']is callback

def test_complete_original_cash_reviewer_code_and_same_day_compiler_are_unchanged():
 fn=p.review_function();old=p.vivo.review_cash
 assert fn.__code__ is old.__code__ and fn.__globals__['cash_tree']is old.__globals__['cash_tree']
 assert fn.__globals__['OBSERVATION']==p.OBSERVATION and fn.__globals__['exact']is p.review_exact
 assert fn.__globals__['data'].catalog()['terms']==p.data.terms()

def test_new_cash_review_writer_cannot_overwrite_the_old_positive_review(tmp_path):
 old=tmp_path/'p07-vivo-ordinary25-cash-review.json';old.write_bytes(b'EXPLICIT_NONCANONICAL_PRIOR_REVIEW_DTO')
 p.review_exact(old,b'EXPLICIT_NONCANONICAL_NEW_REVIEW_DTO')
 assert old.read_bytes()==b'EXPLICIT_NONCANONICAL_PRIOR_REVIEW_DTO'
 assert (tmp_path/p.NEW_REVIEW).read_bytes()==b'EXPLICIT_NONCANONICAL_NEW_REVIEW_DTO'

def test_actual_observer_factory_is_hosted_only():
 with pytest.raises(ValueError):p.observer(None,None,None,None)

def test_financial_import_fences():
 for n in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(x==n or x.startswith(n+'.') for x in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(n)
