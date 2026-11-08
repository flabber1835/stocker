"""Whole lifecycle reuse and local financial fences for the exact174 seed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_RUNTIME_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PTLA_runtime as r
import system_campaign_p03_PTLA_models as models


@pytest.mark.parametrize('name',r.TEMPLATES)
def test_complete_original_template_has_only_declared_count_change(name):
 original=next(n for n in ast.parse(Path(r.original.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
 new=r.template_tree(name)
 if name=='neutral':
  site,=[n for n in ast.walk(new) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="history.full(root, actual)['full_inputs']"]
  assert site.comparators[0].value==21;site.comparators[0].value=20
 elif name=='seed_resolver':
  site,=[n for n in ast.walk(new) if isinstance(n,ast.Compare) and ast.unparse(n.left)=='len(value[1])']
  assert site.comparators[0].value==174;site.comparators[0].value=152
 elif name=='retained_worker':
  site,=[n for n in ast.walk(new) if isinstance(n,ast.keyword) and n.arg=='retained_rows']
  assert site.value.value==174;site.value.value=152
 assert ast.dump(new,include_attributes=False)==ast.dump(original,include_attributes=False)


def test_phase_counts_come_from_current_admitted_root():
 assert r.phase(r.history.spec())==dict(rows=174,new_rows=22,retained_rows=152)


def test_whole_functions_keep_new_history_and_physical_seed_callbacks():
 parent=dict(sha256='a'*64,EXPLICIT_NONCANONICAL_PARENT_DTO=True);api=r.functions(parent)
 assert api.seed_view.__wrapped__.__globals__['history'].full is r.history.full
 assert api.seed_resolver.__globals__['previous'].retained_contract is r.physical
 assert api.seed_resolver.__globals__['previous'].retained_phase is r.phase
 assert api.seed_view.__wrapped__.__globals__['history'].SOURCE==r.history.material_name(parent)


def test_complete_original_worker_binding_uses_actual_constructor_callable():
 parent=dict(sha256='a'*64,EXPLICIT_NONCANONICAL_PARENT_DTO=True);api=r.functions(parent)
 bindings={n:lambda *a,**k:None for n in ('Certificate','preserve','retained_seed','active_codec','unchanged_input_phase','own_unchanged_input_phase','unchanged_input_receipt')}
 fn=api.retained_worker(bindings,None,None,None,(None,None,None),Path('EXPLICIT_NONCANONICAL_VIEW_DTO'))
 assert fn.__globals__['Certificate']is bindings['Certificate'] and fn.__name__=='run_retained'


def test_old_and_second_codec_order_is_preserved():
 code=next(n for n in ast.parse(Path(models.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='codecs')
 outer=next(n for n in code.body if isinstance(n,ast.With));assert ast.unparse(outer.items[0].context_expr)=='base_context(root, current, spec)'
 first=next(n for n in outer.body if isinstance(n,ast.With));assert ast.unparse(first.items[0].context_expr).startswith('InputCodec(')
 second=next(n for n in first.body if isinstance(n,ast.With));assert ast.unparse(second.items[0].context_expr).startswith('SuccessorCodec(')
 binding=next(n for n in code.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='InputCodec')
 assert ast.unparse(binding.value)=='dova.InputCodec' and callable(models.dova.InputCodec)


def test_local_financial_and_model_paths_closed():
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.prepare(None,None,None,None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.run(None,None,None,None,None,None,spec=None,old=None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.review(None,None,None,spec=None,old=None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):r.seed_reader()(None,None,None)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):models.installed()
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  with models.codecs(None,None,None,None,base_context=None):pytest.fail('Opened local financial model context')


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
