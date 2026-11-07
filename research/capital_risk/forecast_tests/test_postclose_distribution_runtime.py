"""Original whole financial routines and pure evidence readers; no local book execution."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('POSTCLOSE_RUNTIME_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_runtime as p

@pytest.fixture(scope='module')
def actual():
 f=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial343-P07-source-snapshot/capture-P07-13534905567-001')
 if not f.exists():pytest.skip('authenticated FIN343 DATA required')
 root=Path('\\\\?\\'+str((f/'verified-output').resolve()))
 spec=p.selected_spec();raw=(root/'book/checkpoint.json.gz').read_bytes()
 assert dict(bytes=len(raw),sha256=p.sha(raw))==spec['selected_file']
 return json.loads(gzip.decompress(raw)),spec

def test_original_financial_observer_has_every_identical_method_and_only_distinct_output():
 cls=p.observer_type();methods={n:f for n,f in vars(p.original.Observer).items() if isinstance(f,FunctionType)}
 assert set(n for n,f in vars(cls).items() if isinstance(f,FunctionType))==set(methods)
 for name,fn in methods.items():
  bound=getattr(cls,name)
  assert bound.__code__ is fn.__code__ and bound.__defaults__==fn.__defaults__ and bound.__closure__ is None
  for key,value in fn.__globals__.items():
   assert bound.__globals__[key] is value if key!='ACTUAL' else bound.__globals__[key]==p.ACTUAL
 assert p.ACTUAL!=p.original.ACTUAL

def test_complete_original_qualifier_AST_undo_restores_every_check():
 raw=Path(p.original.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualify')
 after=p.qualifier_tree(raw)
 original_block=next(n for n in before.body if isinstance(n,ast.With));changed_block=next(n for n in after.body if isinstance(n,ast.With))
 start=next(i for i,n in enumerate(original_block.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='record')
 assert ast.unparse(changed_block.body[-1])=='retained_stack(cp, out)'
 changed_block.body[-1:]=deepcopy(original_block.body[start:])
 minimum=next(n for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='ordinary_min')
 assert ast.unparse(minimum.value)=='day'
 minimum.value=deepcopy(next(n.value for n in before.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='ordinary_min'))
 call,=[n for n in ast.walk(after) if isinstance(n,ast.Call) and ast.unparse(n.func)=='ctx.codec.load']
 call.func=ast.parse('repair.load_repair',mode='eval').body
 keyword,=[k for n in ast.walk(after) if isinstance(n,ast.Call) for k in n.keywords if k.arg=='retained_stack_and_typed_parser_falsifiers']
 keyword.arg='original_ordinary_packet_notional_and_parser_falsifiers'
 assert ast.dump(after)==ast.dump(before)

def test_payload_binds_actual_parent_source_and_descriptor_without_new_cash(actual):
 parent,spec=actual;value=p.payload();names=p.history.paths(spec)
 assert value['binding']['spin']['session']=='2023-07-05' and value['new_ordinary_cash_terms']==[]
 assert value['parent_outer_sha256']==parent['sha256'] and value['parent_state_sha256']==parent['run']['state_sha256']
 assert value['source_payload']==p.source.normalize(p.source.catalog())
 assert value['descriptor_sha256']==p.sha(p.source.encoded(p.typed.document()))
 assert len(names)==len(set(names.values())) and all(v.startswith('distribution-successors/'+p.saved.ROOT+'/') for v in names.values())

def test_pre_event_review_reads_no_invented_event(actual,tmp_path):
 parent,_=actual
 assert p.review_event(p.payload(),tmp_path,parent)==dict(passed=True,event_committed=False,financial_sessions_admitted=0)
 assert list(tmp_path.iterdir())==[]

def pure_qualification_dtos(parent,spec):
 value=p.payload();quantity=sum((p.Fraction(str(v['quantity'])) for v in value['binding']['parent_positions']),p.Fraction(0))
 report=dict(passed=True,financial_sessions_advanced=0,binding_sha256=p.digest(value['binding']),
  source_payload_sha256=p.sha(p.source.encoded(value['source_payload'])),spin=p.source.original.consideration(value['binding'],quantity,10),
  canonical_primitives_delegated=True,original_financial_source_changed=False,
  original_native_quote_proxy_duplicate_role_falsifiers=True,retained_stack_and_typed_parser_falsifiers=True,loaded_minimum_boundary='2023-07-05')
 retained=dict(passed=True,financial_sessions_advanced=0,new_ordinary_cash_terms=0,
  retained_inputs=[dict(descriptor=d,loaded_sha256=d['sha256']) for d in parent['repairs']])
 names=p.history.paths(spec)
 return {names['QUALIFICATION']:report,names['RETAINED_QUALIFICATION']:retained}

@pytest.mark.parametrize('corrupt',['none','cash','binding','primitive','old_descriptor','spin'])
def test_explicit_noncanonical_qualification_DTO_guards(actual,corrupt):
 parent,spec=actual;docs=pure_qualification_dtos(parent,spec);names=p.history.paths(spec)
 report,retained=docs[names['QUALIFICATION']],docs[names['RETAINED_QUALIFICATION']]
 if corrupt=='cash':retained['new_ordinary_cash_terms']=1
 elif corrupt=='binding':report['binding_sha256']='f'*64
 elif corrupt=='primitive':report['canonical_primitives_delegated']=False
 elif corrupt=='old_descriptor':retained['retained_inputs'].pop()
 elif corrupt=='spin':report['spin']={'EXPLICIT_NONCANONICAL_WRONG_FINANCIAL_RESULT_DTO':True}
 member=lambda n:p.source.encoded(docs[n])
 if corrupt=='none':assert p.packet_qualification(parent,spec,member) is True
 else:
  with pytest.raises(ValueError):p.packet_qualification(parent,spec,member)

def test_packet_qualification_guard_removal_falsifier(actual,monkeypatch):
 parent,spec=actual;docs=pure_qualification_dtos(parent,spec)
 docs[p.history.paths(spec)['QUALIFICATION']]['spin']={'EXPLICIT_NONCANONICAL_WRONG_FINANCIAL_RESULT_DTO':True}
 member=lambda n:p.source.encoded(docs[n])
 with pytest.raises(ValueError):p.packet_qualification(parent,spec,member)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_COMPLETE_ORIGINAL_HOSTED_PACKET_PRIMITIVE_AND_PARSER_QUALIFICATION' else original(ok,label))
 assert p.packet_qualification(parent,spec,member) is True

@pytest.mark.parametrize('entry',['reconstruct_source','verify_payload','observer','retained_stack','qualify','prepare','context'])
def test_hosted_entry_refuses_before_financial_import_or_file_write(actual,tmp_path,monkeypatch,entry):
 parent,spec=actual;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 calls=dict(reconstruct_source=lambda:p.reconstruct_source(parent,tmp_path),verify_payload=lambda:p.verify_payload(tmp_path),
  observer=lambda:p.observer(tmp_path),retained_stack=lambda:p.retained_stack(parent,tmp_path),
  qualify=lambda:p.qualify(parent,tmp_path,None,None,None),prepare=lambda:p.prepare(parent,tmp_path),
  context=lambda:p.ProjectionContext(tmp_path,payload=(p.payload(),p.source.encoded(p.payload()))).__enter__())
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):calls[entry]()
 assert list(tmp_path.iterdir())==[]

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
