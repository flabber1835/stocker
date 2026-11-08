"""Exercise the original call using its inherited signature and opaque DTOs."""
import ast,hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('KDNY_CONSTRUCTOR_ARGUMENT_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_KDNY_runtime as r
f=r.factories


def opaque_signature_class():
 tree=ast.parse((C/'system_campaign_zogenix_sensor.py').read_bytes())
 sensor=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SensorCertificate')
 init=next(n for n in sensor.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
 assert {n.arg for n in init.args.kwonlyargs}==f.ZOGENIX_ARGUMENTS
 body=ast.parse("self.forwarded={'zogenix_codec':zogenix_codec,'zogenix_native':zogenix_native,'zogenix_source':zogenix_source}\nself.opaque_args=args\nself.opaque_extra=kwargs").body
 dto=ast.ClassDef(name='EXPLICIT_NONCANONICAL_SENSOR_SIGNATURE_DTO',bases=[],keywords=[],decorator_list=[],
  body=[ast.FunctionDef(name='__init__',args=deepcopy(init.args),body=body,decorator_list=[])])
 scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=[dto],type_ignores=[])),'<opaque-DATA-class-original-required-signature-only>','exec'),scope)
 return scope[dto.name]


def argument_dtos():
 return dict(zogenix_codec=object(),zogenix_native=object(),zogenix_source={'EXPLICIT_NONCANONICAL_SOURCE_DTO':True})


def original_constructor_call():
 fn=next(n for n in ast.parse(Path(r.legacy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='run_retained')
 return next(n for n in fn.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='Certificate')


def test_whole_original_worker_constructor_call_with_actual_inherited_signature():
 Factory=opaque_signature_class();arguments=argument_dtos();constructor=f.bind_arguments(Factory,**arguments)
 scope=dict(Certificate=constructor,out=object(),codec=object(),alder=SimpleNamespace(native=object()),hashes={},rows=[],source={'EXPLICIT_NONCANONICAL_EVENT_DTO':True})
 exec(compile(ast.Module(body=[original_constructor_call()],type_ignores=[]),'<whole-original-worker-constructor-call-opaque-DATA>','exec'),scope)
 assert scope['certificate'].forwarded==arguments
 assert scope['certificate'].opaque_extra==dict(seed=scope['rows'],event_source=scope['source'])
 candidate=constructor(scope['out'],scope['codec'],scope['alder'].native,scope['hashes'],seed=scope['rows'],event_source=scope['source'])
 assert candidate.forwarded==scope['certificate'].forwarded


def test_original_missing_argument_failure_is_reproduced_by_signature_dto():
 scope=dict(Certificate=opaque_signature_class(),out=object(),codec=object(),alder=SimpleNamespace(native=object()),hashes={},rows=[],source={})
 with pytest.raises(TypeError,match='zogenix_codec.*zogenix_native.*zogenix_source'):
  exec(compile(ast.Module(body=[original_constructor_call()],type_ignores=[]),'<reproduce-request237-required-signature-failure-only>','exec'),scope)


@pytest.mark.parametrize('missing',sorted(f.ZOGENIX_ARGUMENTS))
def test_any_missing_inherited_argument_is_refused(missing):
 args=argument_dtos();del args[missing]
 with pytest.raises(ValueError,match='ALL_THREE'):f.bind_arguments(opaque_signature_class(),**args)


@pytest.mark.parametrize('replaced',sorted(f.ZOGENIX_ARGUMENTS))
def test_inherited_argument_replacement_is_refused(replaced):
 constructor=f.bind_arguments(opaque_signature_class(),**argument_dtos())
 with pytest.raises(ValueError,match='NO_REPLACED'):constructor(**{replaced:object()})


def test_same_bound_constructor_used_for_canary_and_original_worker():
 run=next(n for n in ast.parse(Path(r.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='run')
 candidate=next(n for n in ast.walk(run) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='candidate')
 assert ast.unparse(candidate.value.func)=='constructor'
 binding=next(n for n in ast.walk(run) if isinstance(n,ast.Call) and ast.unparse(n.func)=='retained_worker')
 assert next(k.value.id for k in binding.args[0].keywords if k.arg=='Certificate')=='constructor'
 make=next(n for n in ast.walk(run) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='constructor')
 assert ast.unparse(make.value)=='factories.bind_arguments(C, **retained.zogenix_arguments(codec, view))'


def test_whole_previous_runtime_restored_by_only_three_constructor_bindings():
 tree=ast.parse(Path(r.__file__).read_bytes())
 class Undo(ast.NodeTransformer):
  counts=[0,0,0]
  def visit_Assign(self,node):
   if len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
    if node.targets[0].id=='constructor':
     assert ast.unparse(node.value)=='factories.bind_arguments(C, **retained.zogenix_arguments(codec, view))'
     self.counts[0]+=1;return None
    if node.targets[0].id=='candidate':
     assert node.value.func.id=='constructor';node.value.func.id='C';self.counts[1]+=1
   return self.generic_visit(node)
  def visit_keyword(self,node):
   if node.arg=='Certificate' and isinstance(node.value,ast.Name) and node.value.id=='constructor':
    node.value.id='C';self.counts[2]+=1
   return self.generic_visit(node)
 undo=Undo();tree=undo.visit(tree)
 assert undo.counts==[1,1,1]
 assert hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()=='b9a4f3bea8e5a2db15a90a0b032c184e8d0ff6a87bb0b92564da8c8cf7dababb'


def test_actual_loader_argument_resolution_remains_hosted_only():
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.retained.zogenix_arguments(None,None)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
