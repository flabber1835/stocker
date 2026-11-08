"""Complete original workers/guards and exact profile DATA; no local finance."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('KDNY_RUNTIME_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_KDNY_entry as p
r,retained=p.runtime,p.retained


def test_actual949_root_and_complete_original_phase_metadata():
 spec=p.history.spec();assert retained.phase(spec)==dict(rows=949,new_rows=20,retained_rows=929)
 life=retained.lifecycle();assert life.valid_retained(spec) and life.phase(spec)['proof_rows']==949
 assert p.validate_metadata(spec)==dict(rows=949,new_rows=20,retained_rows=929,completed=1403,source_cursor='2023-07-31')


def test_whole_original_retained_declaration_AST_undo():
 raw=Path(retained.original_lifecycle.__file__).read_bytes();new=retained.declaration_tree(raw)
 site,=[n for n in ast.walk(new) if isinstance(n,ast.Compare) and ast.unparse(n)=="len(spec['repairs']) == 26"]
 site.comparators[0].value=24
 original=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='valid_retained')
 assert ast.dump(new)==ast.dump(original)


def test_whole_original_canonical_adopter_AST_undo():
 original=next(n for n in ast.parse(Path(r.legacy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
 new=r.adoption_tree();mapping=next(n.value for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
 assert mapping.keys.pop().value==r.history.DIRECTORY and mapping.values.pop().value==r.history.OVERLAY
 assert ast.dump(new)==ast.dump(original)


def test_nested_boundary_keeps_full_original_input_path(monkeypatch):
 seen=[];monkeypatch.setattr(r.legacy,'boundary',lambda *a:seen.append(a) or 'EXPLICIT_NONCANONICAL_BOUNDARY_DTO')
 out=Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO');parent={'EXPLICIT_NONCANONICAL_PARENT_DTO':True}
 fn=r.adopter().__globals__['boundary']
 assert fn(out,r.history.DIRECTORY,parent,Path(r.history.OVERLAY).name,r.source.NATIVE)=='EXPLICIT_NONCANONICAL_BOUNDARY_DTO'
 assert seen==[(out,r.history.DIRECTORY,parent,r.history.OVERLAY,r.source.NATIVE)]
 with pytest.raises(ValueError,match='NESTED'):fn(out,r.history.DIRECTORY,parent,'wrong.json',r.source.DAY)


def test_original_financial_worker_has_only_qualified_writer_dispatch():
 bindings={n:lambda *a,**k:None for n in ('Certificate','preserve','retained_seed','active_codec','unchanged_input_phase','own_unchanged_input_phase','unchanged_input_receipt')}
 fn=r.retained_worker(bindings,None,None,None,(None,None,None),Path('EXPLICIT_NONCANONICAL_VIEW_DTO'))
 assert fn.__globals__['Certificate'] is bindings['Certificate']
 new=next(n for n in ast.parse(ast.unparse(retained.bodies.body_tree('run_retained'))).body if isinstance(n,ast.FunctionDef))
 # The already-qualified writer adapter separately proves a complete AST undo.
 import system_campaign_p03_thor_qualification_reuse as reuse
 assert 'qualification_present' in fn.__globals__ and callable(reuse.run_tree)
 assert fn.__name__==new.name=='run_retained'


def test_all_four_mature_functions_unchanged():
 import system_campaign_financial_resume as m
 assert p.mature_review(m).__name__=='review'


def test_codec_order_is_original_ABMD_then_KDNY_then_BWA():
 fn=next(n for n in ast.parse(Path(retained.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='codecs')
 outer=next(n for n in fn.body if isinstance(n,ast.With));assert ast.unparse(outer.items[0].context_expr)=='api.original_chain(root, parent, spec)'
 successor=next(n for n in outer.body if isinstance(n,ast.With));assert ast.unparse(successor.items[0].context_expr).startswith('SuccessorCodec(')
 projection=next(n for n in successor.body if isinstance(n,ast.With));assert ast.unparse(projection.items[0].context_expr)=='previous.projection(root)'


def request_dto(monkeypatch):
 monkeypatch.setattr(p,'declaration',lambda spec:dict(EXPLICIT_NONCANONICAL_DECLARATION_DTO=True))
 monkeypatch.setattr(p,'source_names',lambda:())
 spec=dict(arm='P07',root_admission_sha256=p.source.ROOT,outer_sha256='EXPLICIT_NONCANONICAL_OUTER_DTO')
 request=dict(execution_mode=p.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
  arms=['P07'],maximum_parallel_financial_workers=1,maximum_parallel_readonly_workers=0,admitted_checkpoints={'P07':spec['outer_sha256']},sources={},
  **{p.FIELD:{'P07':p.declaration(spec)}})
 return request,spec


@pytest.mark.parametrize('key,value',[('maximum_parallel_financial_workers',True),('maximum_parallel_financial_workers',2),('maximum_parallel_readonly_workers',1),('arms',['P07','P03']),('financial_resume_authorized',False)])
def test_financial_request_authority_and_worker_scope_cannot_expand(monkeypatch,key,value):
 request,spec=request_dto(monkeypatch);assert p.require_request(request,spec)
 request[key]=value
 with pytest.raises(ValueError,match='EXACT_QUALIFIED'):p.require_request(request,spec)


def test_financial_worker_count_guard_removal_falsifier(monkeypatch):
 request,spec=request_dto(monkeypatch);request['maximum_parallel_financial_workers']=2
 with pytest.raises(ValueError):p.require_request(request,spec)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='KDNY_ENTRY_EXACT_QUALIFIED_FINANCIAL_REQUEST_AND_ALL_SOURCE_PINS' else old(ok,label))
 assert p.require_request(request,spec)


def test_local_mutating_paths_are_closed():
 with pytest.raises(ValueError):r.prepare({},Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO'),{},Path('EXPLICIT_NONCANONICAL_SOURCE_DTO'))
 with pytest.raises(ValueError):r.run(None,None,None,None,None,None,spec=None,old=None)
 with pytest.raises(ValueError):r.review(None,None,None,spec=None,old=None)
 with pytest.raises(ValueError):
  with retained.codecs(None,None,None,None):pytest.fail('Local codec context opened')
 with pytest.raises(ValueError):
  with r.seed_view(None,None,None,None,None,None,None):pytest.fail('Local financial view opened')
 with pytest.raises(ValueError):
  with p.context(None,None,mode='economic',out=None,request=None):pytest.fail('Local financial entry opened')


def test_current_complete_request_and_exact_source_closure():
 import system_campaign_financial_resume as m
 raw=(C/m.REQUEST).read_bytes();request=json.loads(raw)
 if not request.get(p.FIELD):pytest.skip('The new closed financial request has not been selected yet')
 assert request==m.expected_request() and request['schema'].endswith('/236')
 assert p.require_request(request,p.history.spec())
 assert all(p.sha((C/n).read_bytes())==pin for n,pin in request['sources'].items())


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
