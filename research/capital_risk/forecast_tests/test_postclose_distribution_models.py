"""Genuine existing history and whole source bindings; no fabricated successor."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('POSTCLOSE_MODELS_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_models as p
from system_campaign_abmd_bounded_catalog import evidence

@pytest.fixture(scope='module')
def actual():
 f=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial343-P07-source-snapshot/capture-P07-13534905567-001')
 if not f.exists():pytest.skip('authenticated FIN343 DATA required')
 root=Path('\\\\?\\'+str((f/'verified-output').resolve()));mf=json.loads((f/'authenticated-manifest.json').read_bytes())['members']
 spec=p.runtime.selected_spec();raw=(root/spec['selected_checkpoint']).read_bytes()
 assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[spec['selected_checkpoint']]==spec['selected_file']
 return root,json.loads(gzip.decompress(raw)),spec

def test_genuine_complete_previous_parent_is_still_verified_without_new_input(actual):
 root,parent,spec=actual;before=p.saved.digest(parent);result=p.full(root,parent)
 assert result['passed'] and result['full_inputs']==25 and result['new_input_adopted'] is False
 assert p.saved.digest(parent)==before

def test_actual_old_model_result_and_entire_original_function_bodies(actual,monkeypatch):
 root,parent,spec=actual;old=p.saved.models.models();monkeypatch.setattr(p.saved.models,'models',lambda:old)
 value=p.models();catalog=p.saved.original_lifecycle.catalog()
 result=value.validate_full(root,parent,catalog,evidence(catalog),input_hash=lambda b,r:p.saved.digest(dict(base=b,repairs=r)),root_metadata=p.saved.original_lifecycle.initial_spec())
 assert result['full_input_count']==25 and result['bounded_descriptor']==parent['repairs'][23] and len(result['legacy_models'])==1
 assert value.deepcopy is old.deepcopy
 for name in ('legacy_validator','receipt_reader','model_tree','branch_tree','plan'):
  assert getattr(value,name).__code__ is getattr(old,name).__code__
 assert value.legacy_validator.__globals__['validate_full'] is value.validate_full
 assert value.legacy_validator.__globals__['read_legacy_receipt'] is value.read_legacy_receipt

def test_old_origin_verifier_remains_whole_and_hosted(actual,monkeypatch):
 root,parent,_=actual;old=p.saved.models.origin();monkeypatch.setattr(p.saved.models,'origin',lambda:old);value=p.origin()
 assert value.preserve.__code__ is old.preserve.__code__
 assert value.preserve.__globals__['verify'] is value.verify and value.deepcopy is old.deepcopy
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):value.verify(root,parent,p.saved.original_lifecycle.catalog())

def test_legacy_routing_AST_undo_preserves_every_other_original_statement():
 raw=Path(p.saved.retained.legacy_original.__file__).read_bytes()
 before=p.saved.retained.legacy_tree(raw);after=p.legacy_tree(raw)
 fn=next(n for n in after.body if n.name=='suffix')
 p.saved.models.replace_count(fn,'(23, 24, 25, 26)','(23, 24, 25)',1,'UNDO_FINITE_COUNT')
 fn=next(n for n in after.body if n.name=='future_tree')
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=="(len(cp['repairs']) in (24,25,26) and entry==cp['repairs'][23]) or (len(cp['repairs'])==26 and entry==cp['repairs'][25])"]
 site.value="len(cp['repairs']) in (24,25) and entry==cp['repairs'][23]"
 assert ast.dump(after)==ast.dump(before)

def test_lifecycle_bindings_are_private_and_preserve_complete_code(actual):
 _,_,spec=actual;old_guard=p.saved.original_lifecycle.valid_retained;value=p.lifecycle()
 assert value.valid_retained(spec) is True and p.saved.original_lifecycle.valid_retained is old_guard
 assert value.phase.__code__.co_code==p.saved.original_lifecycle.phase.__code__.co_code
 original=next(n for n in ast.parse(Path(p.saved.original_lifecycle.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='phase')
 retained=next(n for n in p.saved.retained.lifecycle_tree(Path(p.saved.original_lifecycle.__file__).read_bytes()).body if n.name=='phase')
 assert ast.dump(original)==ast.dump(retained)
 assert value.phase.__globals__['valid_retained'] is value.valid_retained
 phase=value.phase(spec);assert phase['proof_rows']==929 and phase['source_cursor']=='2023-06-30'
 assert value.runtime_api.__globals__['models'].validate_full.__module__==p.__name__

def test_old_event_descriptors_are_the_genuine_archived24_epoch(actual):
 root,parent,_=actual;result=p.actual_event_descriptors(root,parent['repairs'])
 assert result==p.saved.metadata(p.runtime.selected_spec())['historical_event_descriptors'] and len(result)==24

def test_old_parent_cannot_be_misreported_as_a_completed_new_boundary(actual):
 root,parent,_=actual
 with pytest.raises(ValueError,match='ONLY_GENUINE_CURRENT26'):p.genuine_parent(root,parent)

def test_exact_payload_guard_removal_on_explicit_noncanonical_input_DTO(actual,monkeypatch):
 _,parent,spec=actual;names=p.history.paths(spec);doc=p.runtime.typed.document()
 members={names['OVERLAY']:p.runtime.source.encoded(doc),
  names['PAYLOAD']:p.runtime.source.encoded(dict(EXPLICIT_NONCANONICAL_WRONG_PAYLOAD_DTO=True))}
 checked=[];monkeypatch.setattr(p.runtime,'packet_qualification',lambda *args:checked.append(args[0]['sha256']))
 with pytest.raises(ValueError,match='COMPLETE_TYPED_DOCUMENT'):p.document(parent,members.__getitem__)
 assert checked==[]
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_MODELS_COMPLETE_TYPED_DOCUMENT_AND_ORIGINAL_PAYLOAD' else original(ok,label))
 assert p.document(parent,members.__getitem__)==doc and checked==[parent['sha256']]

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
