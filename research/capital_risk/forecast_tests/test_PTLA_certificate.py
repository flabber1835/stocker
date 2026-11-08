"""Prior event permissions and whole consumed-constructor binding, opaque DATA."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_CERTIFICATE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
from full_system_benchmark import need
import system_campaign_p03_PTLA_certificate as c


def resolution_dto():
 value={k:'EXPLICIT_NONCANONICAL_RESOLUTION_DTO_'+k for k in ('actual','gzip_sha256','outer_sha256','state_sha256','input_sha256')}
 return value,dict(value,prior_event_basis_revalidated=True,prior_transition_reexecuted=False)


@pytest.mark.parametrize('change',['undeclared','not_revalidated','replayed'])
def test_prior_archive_permission_cannot_expand(change):
 declared,resolution=resolution_dto();assert c.require_resolution(resolution,[declared])==declared
 if change=='undeclared':resolution['gzip_sha256']='EXPLICIT_NONCANONICAL_CHANGED_HASH_DTO'
 elif change=='not_revalidated':resolution['prior_event_basis_revalidated']=False
 else:resolution['prior_transition_reexecuted']=True
 with pytest.raises(ValueError,match='ONLY_DECLARED_PRIOR_ARCHIVE_NO_REPLAY'):c.require_resolution(resolution,[declared])


def test_archive_membership_guard_removal_falsifier(monkeypatch):
 declared,resolution=resolution_dto();resolution['gzip_sha256']='EXPLICIT_NONCANONICAL_CHANGED_HASH_DTO'
 with pytest.raises(ValueError):c.require_resolution(resolution,[declared])
 old=c.need;monkeypatch.setattr(c,'need',lambda ok,label:None if label=='PTLA_CERTIFICATE_ONLY_DECLARED_PRIOR_ARCHIVE_NO_REPLAY' else old(ok,label))
 assert c.require_resolution(resolution,[declared])['gzip_sha256']!=declared['gzip_sha256']


def test_complete_existing_consumed_constructor_code_and_closure_are_reused():
 token=object()
 class EXPLICIT_NONCANONICAL_CLOSURE_DTO:
  def __init__(self,seed):
   self.seed=seed
   need(False,'PRIOR_COMMITTED_B19_SEED')
   self.token=token
 original=EXPLICIT_NONCANONICAL_CLOSURE_DTO.__init__;seen=[]
 event={'EXPLICIT_NONCANONICAL_EVENT_DTO':True};current={'EXPLICIT_NONCANONICAL_CURRENT_DTO':True};spec={'EXPLICIT_NONCANONICAL_SPEC_DTO':True}
 def validate(*args):seen.append(args);return {'EXPLICIT_NONCANONICAL_QUALIFICATION_DTO':True}
 bound=c.bind_consumed(EXPLICIT_NONCANONICAL_CLOSURE_DTO,event,current,spec,validate)
 assert bound is EXPLICIT_NONCANONICAL_CLOSURE_DTO and bound.__init__.__code__ is original.__code__ and bound.__init__.__closure__ is original.__closure__
 seed=['EXPLICIT_NONCANONICAL_SEED_DTO'];instance=bound(seed)
 assert instance.token is token and seen==[(seed,event,current,spec)]


def test_actual_financial_constructor_remains_hosted_only():
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):c.certificate_class(None,None,None,None,None,None)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
