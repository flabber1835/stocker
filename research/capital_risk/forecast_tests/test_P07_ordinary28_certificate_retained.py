"""Original constructor/code fidelity and opaque class DTOs, never a kernel."""
import ast,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_RETAINED_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_certificate as p
import system_campaign_p07_ordinary28_retained as r
need=p.need

def class_DTO(*,unrelated=False):
 marker=object()
 class ExplicitNoncanonicalConstructorDTO:
  def __init__(self,rows):
   self.seed=rows
   assert marker is not None
   need(False,'PRIOR_COMMITTED_B19_SEED')
   if unrelated:need(False,'EXPLICIT_NONCANONICAL_UNRELATED_GUARD')
 return ExplicitNoncanonicalConstructorDTO

def test_consumed_constructor_keeps_exact_original_code_closure_and_validates_seed():
 cls=class_DTO();original=cls.__init__;rows=['EXPLICIT_NONCANONICAL_972_SEED_DTO'];event={'EXPLICIT_NONCANONICAL_EVENT_DTO':True};current={'EXPLICIT_NONCANONICAL_CURRENT_DTO':True};spec={'EXPLICIT_NONCANONICAL_SPEC_DTO':True};calls=[]
 def validate(seed,e,cp,target):
  assert seed is rows and e is event and cp is current and target is spec;calls.append(seed);return {'EXPLICIT_NONCANONICAL_VALIDATION_DTO':True}
 result=p.bind_consumed(cls,event,current,spec,validate)
 assert result is cls and cls.__init__.__code__ is original.__code__ and cls.__init__.__closure__ is original.__closure__
 assert cls(rows).seed is rows and calls==[rows]

def test_consumed_constructor_cannot_bypass_an_unrelated_original_guard():
 cls=class_DTO(unrelated=True);p.bind_consumed(cls,{}, {},{},lambda *args:True)
 with pytest.raises(ValueError,match='UNRELATED_GUARD'):cls(['EXPLICIT_NONCANONICAL_SEED_DTO'])

def test_actual_seed_validator_refusal_propagates():
 cls=class_DTO()
 def refuse(*args):raise ValueError('EXPLICIT_NONCANONICAL_WRONG_SEED_REFUSED')
 p.bind_consumed(cls,{},{},{},refuse)
 with pytest.raises(ValueError,match='WRONG_SEED_REFUSED'):cls(['EXPLICIT_NONCANONICAL_BAD_SEED_DTO'])

def test_constructor_without_original_closure_is_refused():
 class ExplicitNoncanonicalWrongConstructorDTO:
  def __init__(self,rows):self.seed=rows
 with pytest.raises(ValueError,match='KEEP_ENTIRE_ORIGINAL_BOUNDED_CONSTRUCTOR_CLOSURE'):
  p.bind_consumed(ExplicitNoncanonicalWrongConstructorDTO,{},{},{},lambda *args:True)

def test_original_archive_resolution_requires_every_exact_declared_identity():
 value=dict(actual='EXPLICIT_NONCANONICAL_ARCHIVE_DTO',gzip_sha256='GZIP_DTO',outer_sha256='OUTER_DTO',state_sha256='STATE_DTO',input_sha256='INPUT_DTO')
 assert p.require_resolution(value,[value]) is value
 with pytest.raises(ValueError,match='EXACT_DECLARED_ARCHIVE'):p.require_resolution(dict(value,input_sha256='WRONG_DTO'),[value])
 with pytest.raises(ValueError,match='EXACT_DECLARED_ARCHIVE'):p.require_resolution(dict(value,OMITTED_GUARD_DTO=True),[value])

def test_archive_data_guard_uses_genuine_archived26_not_a_sliced_current_axis():
 tree=ast.parse(Path(p.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='archived_bases')
 calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='history.previous.previous.actual_event_descriptors']
 assert len(calls)==1 and ast.unparse(calls[0].args[1])=="archived26['repairs']"
 assert not any(isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Slice) for n in ast.walk(fn))

def test_entire_original_consumed_ABMD_factory_AST_undo():
 raw=Path(p.original.frozen.__file__).read_bytes();new=p.original.continuation_tree();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='extend_joint')
 call=next(n for n in ast.walk(new) if isinstance(n,ast.Call) and ast.unparse(n.func)=='qualified_retained_seed')
 guard=next(n for n in ast.walk(new) if isinstance(n,ast.Call) and n.args and n.args[0]is call)
 guard.args[0]=ast.parse("self.seed and self.seed[-1]['session'] < NATIVE",mode='eval').body
 assert ast.dump(new)==ast.dump(old)

def test_original_codec_context_code_object_and_historical_metadata_resolver_are_unchanged():
 fn=r.codec_function();old=r.original.codecs.__wrapped__
 assert fn.__code__ is old.__code__ and fn.__defaults__==old.__defaults__ and fn.__kwdefaults__==old.__kwdefaults__
 h=fn.__globals__['history'];assert h.full is r.history.full and h.archived_parent is r.original.history.archived_parent and h.spec is r.original.history.spec

def test_installed_chain_and_all_three_zogenix_resolvers_are_exact_original_functions():
 assert r.installed is r.original.installed and r.active_branch is r.original.active_branch and r.zogenix_arguments is r.original.zogenix_arguments
 assert p.original.ZOGENIX_ARGUMENTS=={'zogenix_codec','zogenix_native','zogenix_source'}

def test_entire_original_mixed_growth_context_AST_undo():
 raw=Path(r.prior_growth.additional_runtime.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='growth_scope');new=r.growth_tree()
 index,imp=next((i,n) for i,n in enumerate(old.body) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_uncertainty')
 new.body.insert(index,imp);assert ast.dump(new)==ast.dump(old)

def test_exact_current_metadata_phase_retains_all972_rows():
 s=r.resources.spec();assert r.phase(s)==dict(rows=972,new_rows=23,retained_rows=949)
 assert r.selected(s) and not r.selected(dict(s,root_admission_sha256='WRONG_ROOT_DTO'))

def test_local_factories_contexts_and_physical_reads_are_closed():
 with pytest.raises(ValueError):p.certificate_class(None,None,None,None,None,None,mixed=lambda values:None)
 with pytest.raises(ValueError):
  with r.codecs(None,None,None,None):pass
 with pytest.raises(ValueError):r.physical(None,None)
 with pytest.raises(ValueError):r.proof_scope(None,None,None)
 with pytest.raises(ValueError):r.growth_scope(None,None,None)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
