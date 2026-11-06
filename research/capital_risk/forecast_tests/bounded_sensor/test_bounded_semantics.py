"""Interpretation-source bytes and actual original pins; DATA only."""
import ast,json,shutil,sys
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_SEMANTIC_SOURCE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_bounded_sensor_semantics as data

@pytest.fixture
def source(tmp_path):
    root=Path(data.__file__).parent
    v=json.loads((root/'P03-own462-DOVA-source-bound-input-catalog-v1.json').read_bytes())
    for name in v['input_semantics_sources']:shutil.copyfile(root/name,tmp_path/name)
    return tmp_path,v

def test_complete_actual_interpretation_generation_and_original_math(source):
    root,v=source;assert data.verify(v,root) and len(v['input_semantics_sources'])==9

@pytest.mark.parametrize('change',['missing','foreign','changed_decoder','changed_lifecycle','changed_math','repinned_math'])
def test_missing_changed_or_repinned_interpretation_sources_refuse(source,change):
    root,v=source;pins=v['input_semantics_sources']
    if change=='missing':pins.pop('system_campaign_bounded_sensor_models.py')
    elif change=='foreign':pins['foreign.py']='0'*64
    else:
        name={'changed_decoder':'system_campaign_bounded_sensor_input.py','changed_lifecycle':'system_campaign_bounded_sensor_lifecycle_data.py',
              'changed_math':'system_campaign_uncertainty_math.py','repinned_math':'system_campaign_uncertainty_math.py'}[change]
        p=root/name;p.write_bytes(p.read_bytes()+b'\n# SYNTHETIC FOREIGN GENERATION\n')
        if change=='repinned_math':pins[name]=data.sha(p.read_bytes())
    with pytest.raises(ValueError):data.verify(v,root)

def removed(label):
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='verify')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-interpretation-source-guard-DATA-only>','exec'),scope)
    return scope['verify']

@pytest.mark.parametrize('label,change',[('BOUNDED_SEMANTICS_COMPLETE_EXACT_SOURCE_SET','missing'),
    ('BOUNDED_SEMANTICS_IMMUTABLE_ORIGINAL_B19_CONTEXT_MATH','repin'),
    ('BOUNDED_SEMANTICS_ALL_ACTUAL_INTERPRETATION_SOURCE_BYTES','changed')])
def test_guard_removal_really_accepts_unqualified_semantics(source,label,change):
    root,v=source;pins=v['input_semantics_sources']
    if change=='missing':pins.pop('system_campaign_bounded_sensor_models.py')
    else:
        name='system_campaign_uncertainty_math.py' if change=='repin' else 'system_campaign_bounded_sensor_input.py'
        p=root/name;p.write_bytes(p.read_bytes()+b'\n# SYNTHETIC FOREIGN GENERATION\n')
        if change=='repin':pins[name]=data.sha(p.read_bytes())
    with pytest.raises(ValueError):data.verify(v,root)
    assert removed(label)(v,root)

def test_legacy_legal_only_catalog_is_not_selectable_as_a_typed_input():
    root=Path(data.__file__).parent
    value=json.loads((root/'P03-own462-DOVA-source-bound-input-catalog-v1.json').read_bytes())
    value.pop('input_semantics_sources')
    with pytest.raises(ValueError,match='COMPLETE_EXACT_SOURCE_SET'):data.verify(value)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
