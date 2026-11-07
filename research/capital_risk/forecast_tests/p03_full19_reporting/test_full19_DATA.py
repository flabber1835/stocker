import ast,json,sys
from pathlib import Path
from copy import deepcopy
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('FULL18_REPORT_DATA_ONLY:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_full19_reporting as r
def test_actual_target_and_declaration():
    raw=json.loads((D/'P03-FIN352-raw-full19-target.json').read_bytes());target=r.qualify_target(raw);value=r.declaration(target)
    assert (value['completed'],value['full_inputs'],value['retained_rows'],value['new_financial_rows'])==(606,19,89,63)
    assert value['financial_reuse_seed_installed'] is value['financial_resume_authorized'] is False
@pytest.mark.parametrize('key,value',[('measured_closes',607),('selected_session','2020-06-09'),('financial_authority',True),('input_sha256','f'*64)])
def test_wrong_target_refuses(key,value):
    target=json.loads((D/'P03-FIN352-raw-full19-target.json').read_bytes());target[key]=value
    with pytest.raises(ValueError):r.qualify_target(target)
def test_whole_original_bridge_AST_undo():
    plan=json.loads((D/'AST-bindings.json').read_bytes());tree=ast.parse(Path(r.__file__).read_bytes())
    strings={v:k for k,v in plan['strings'].items()};ints={v:int(k) for k,v in plan['ints'].items()}
    class Undo(ast.NodeTransformer):
        def visit_Constant(self,node):
            value=ints.get(node.value,node.value) if type(node.value) is int else strings.get(node.value,node.value) if type(node.value) is str else node.value
            return ast.copy_location(ast.Constant(value),node)
    original=(C/'system_campaign_p03_full18_reporting.py').read_bytes();assert r.sha(original)==plan['old_source_sha256']
    assert ast.dump(Undo().visit(tree))==ast.dump(ast.parse(original))
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
    assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
    with pytest.raises(ImportError):Fence().find_spec(name)
