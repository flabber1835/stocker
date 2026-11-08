"""Whole-body equivalence and opaque DTO input ordering; no financial imports."""
import ast,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('KDNY_PACKET_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_KDNY_preparation as p


def test_whole_absent_bar_qualifier_AST_undo():
 raw=Path(p.original.__file__).read_bytes();fn=p.packet_tree(raw)
 for n in ast.walk(fn):
  if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value in (p.NATIVE,p.DAY):n.value={p.NATIVE:'2022-12-21',p.DAY:'2022-12-22'}[n.value]
 limits,=[n for n in ast.walk(fn) if isinstance(n,ast.List) and ast.unparse(n)=='[40.0, 44.0]']
 limits.elts=[ast.Constant(380.),ast.Constant(415.)]
 apply,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='apply_cumulative']
 apply.func=ast.parse('backtest.apply_repair',mode='eval').body
 original,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_packets']
 assert ast.dump(fn)==ast.dump(original)


def test_whole_original_body_retains_absence_and_point_selection_refusals():
 fn=p.packet_tree(Path(p.original.__file__).read_bytes())
 text=ast.unparse(fn)
 assert "range_ == [40.0, 44.0]" in text and "point['selected'] is False and interval is None" in text
 for name in ('ABMD_PREPARATION_NO_FABRICATED_COMPLETION_BAR','ABMD_PREPARATION_ORIGINAL_INCOMPLETE_GUARD_MISSING','ABMD_PREPARATION_PARSER_FALSIFIER_ACCEPTED'):
  assert name in text


def test_all_retained_inputs_apply_in_original_order_before_new_object():
 inputs=[f'EXPLICIT_NONCANONICAL_INPUT_DTO_{n}' for n in range(26)];seen=[]
 def apply(packet,obj):seen.append(obj);return packet+[obj]
 whole=p.packet_qualifier(inputs,apply);callback=whole.__globals__['apply_cumulative']
 final='EXPLICIT_NONCANONICAL_KDNY_INPUT_DTO';assert callback([],final)==inputs+[final]
 assert seen==inputs+[final]


def test_changed_original_qualifier_source_refused():
 with pytest.raises(ValueError,match='WHOLE_ORIGINAL'):p.packet_tree(Path(p.original.__file__).read_bytes()+b'\n')


def test_local_packet_qualification_stays_closed():
 with pytest.raises(ValueError):p.qualify_packets({},Path('EXPLICIT_NONCANONICAL_DTO'),None,None,{},[])


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
