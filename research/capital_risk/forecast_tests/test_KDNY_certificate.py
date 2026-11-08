"""Whole constructor adapter and opaque cooperative class DTOs only."""
import ast,sys
from dataclasses import make_dataclass
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('KDNY_CERTIFICATE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_KDNY_certificate as p


def test_entire_original_ABMD_factory_AST_undo():
 raw=Path(p.frozen.__file__).read_bytes();new=p.continuation_tree()
 old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='extend_joint')
 guard,=[n for n in ast.walk(new) if isinstance(n,ast.Call) and ast.unparse(n.func)=='qualified_retained_seed']
 enclosing,=[n for n in ast.walk(new) if isinstance(n,ast.Call) and n.args and n.args[0] is guard]
 enclosing.args[0]=ast.parse("self.seed and self.seed[-1]['session'] < NATIVE",mode='eval').body
 assert ast.dump(new)==ast.dump(old)


def test_complete_constructor_calls_explicit_seed_guard_and_keeps_superclass():
 value=p.original_lifecycle.catalog();native=make_dataclass('ExplicitNoncanonicalNativeDTO',[(k,object) for k in value['native']])(**value['native'])
 codec=SimpleNamespace(event=value['event']);calls=[]
 class ExplicitNoncanonicalJointDTO:
  def __init__(self,rows):self.seed=rows
  def append(self):pass
 def guard(rows,event,source,actual):calls.append((rows,event,source,actual));return True
 witness=lambda *a:None
 Continued=p.compile_continued(guard)(ExplicitNoncanonicalJointDTO,value['event'],value['market_source'],codec,native,witness=witness,interval_class=object)
 rows=['EXPLICIT_NONCANONICAL_SEED_DTO'];obj=Continued(rows)
 assert obj.seed is rows and calls==[(rows,value['event'],value['market_source'],codec)]
 assert Continued.__mro__[1] is ExplicitNoncanonicalJointDTO and Continued.append is ExplicitNoncanonicalJointDTO.append
 assert Continued.witness is witness


def test_local_shared_financial_factory_is_closed():
 with pytest.raises(ValueError):p.certificate_class(None,None,None,None,None,None,None,None,mixed=lambda values:None)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
