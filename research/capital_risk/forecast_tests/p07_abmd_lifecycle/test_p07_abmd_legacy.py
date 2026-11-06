"""Whole legacy AST undo and explicit additional-model metadata boundaries."""
import ast,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_ABMD_LEGACY_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(1,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
import system_campaign_p07_abmd_legacy as data

def dump(node):return ast.dump(node,include_attributes=False)
def function(raw,name):return data.legacy_data.original.function(raw,name)

def test_full_original_neutral_verifier_AST_undo():
    raw=Path(data.legacy_runtime.__file__).read_bytes();before=function(raw,'verify_neutral');after=data.neutral_tree(raw)
    after=data.models.replace(after,"successor['repairs'] == current['repairs'][:23]","successor['repairs'] == current['repairs']",'undo_boundary')
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Call(self,n):
            if isinstance(n.func,ast.Name) and n.func.id=='neutral_input_hashes':
                self.hits+=1;return ast.parse("successor['run']['input_sha256'] == current['run']['input_sha256']",mode='eval').body
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after);assert undo.hits==1 and dump(after)==dump(before)

def test_entire_old_additional_runtime_AST_undo():
    raw=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/system_campaign_financial_additional_sensor_runtime.py').read_bytes()
    before=data.legacy_data.runtime_tree(raw);after=data.runtime_tree(raw)
    oldrun=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='run_retained')
    newrun=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='run_retained')
    index=next(i for i,n in enumerate(oldrun.body) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_uncertainty_archive')
    newrun.body.insert(index,deepcopy(oldrun.body[index]))
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Call(self,n):
            if isinstance(n.func,ast.Name) and n.func.id=='resolution_counts_valid':
                self.hits+=1;return ast.parse('len(resolutions)==1',mode='eval').body
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after);assert undo.hits==1 and dump(after)==dump(before)

@pytest.mark.parametrize('name,adapter,marker,replacement',[
 ('active_branch','active_tree','qualified_lower_loader(backtest.load_repair)','backtest.load_repair'),
 ('review_ordinary','review_ordinary_tree','review_bounded_origin(parent, current, evidence, out, spec)',"parent['repairs'] == current['repairs']")])
def test_original_chain_inspector_and_ordinary_review_AST_undo(name,adapter,marker,replacement):
    filename='system_campaign_financial_additional_sensor_runtime.py' if name=='active_branch' else 'system_campaign_ordinary_augmentation_runtime.py'
    raw=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk',filename).read_bytes()
    before=function(raw,name);after=getattr(data,adapter)(raw)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Call(self,n):
            if ast.unparse(n)==marker:self.hits+=1;return ast.parse(replacement,mode='eval').body
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after);assert undo.hits==1 and dump(after)==dump(before)

def test_entire_original_ordinary_typed_predicate_AST_undo():
    raw=Path(data.legacy_runtime.__file__).read_bytes();before=function(raw,'future_api');after=data.future_tree(raw)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_BoolOp(self,n):
            if (isinstance(n.op,ast.Or) and len(n.values)==2 and
                    ast.unparse(n.values[0])=="entry in [phase['original_branch_descriptor'], *modeled]"):
                self.hits+=1;return n.values[0]
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after);assert undo.hits==1 and dump(after)==dump(before)

def test_entire_original_archive_preserver_AST_undo():
    raw=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/system_campaign_uncertainty_archive.py').read_bytes()
    before=function(raw,'preserve');after=data.archive_tree(raw)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_BoolOp(self,n):
            if ast.unparse(n)=='not target.exists() or same_existing_archive(actual, target, proof)':
                self.hits+=1;return ast.parse('not target.exists()',mode='eval').body
            return self.generic_visit(n)
    undo=Undo();after=undo.visit(after);assert undo.hits==1 and dump(after)==dump(before)

def test_original_archive_resolver_reads_authenticated_prefix_without_checkpoint_alias():
    raw=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/system_campaign_uncertainty_archive.py').read_bytes()
    before=function(raw,'resolve');after=data.archive_resolver_tree(raw)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_Constant(self,n):
            if n.value==data.origin.DIRECTORY+'/prior-committed-certificate.jsonl':self.hits+=1;return ast.Constant('uncertainty-certificate.jsonl')
            return n
    undo=Undo();after=undo.visit(after);assert undo.hits==1 and dump(after)==dump(before)

def test_metadata_boundary_checks_both_own_hashes_without_checkpoint_projection():
    ih=lambda base,repairs:data.models.digest(dict(base=base,repairs=repairs))
    successor=dict(base={'noncanonical':True},repairs=list(range(23)),run={})
    current=dict(base=successor['base'],repairs=list(range(24)),run={})
    successor['run']['input_sha256']=ih(successor['base'],successor['repairs']);current['run']['input_sha256']=ih(current['base'],current['repairs'])
    value=dict(adopted_input_sha256=successor['run']['input_sha256'])
    assert data.neutral_input_hashes(successor,current,value,ih)
    assert successor['run']['input_sha256']!=current['run']['input_sha256']
    current['run']['input_sha256']=successor['run']['input_sha256'];assert not data.neutral_input_hashes(successor,current,value,ih)

def test_idempotent_copy_checks_exact_existing_noncanonical_resource(tmp_path):
    source=tmp_path/'synthetic-metadata.json';source.write_bytes(b'{"synthetic":true}\n')
    assert data.safe_copy(source,source)==str(source)
    target=tmp_path/'other.json';data.safe_copy(source,target);assert target.read_bytes()==source.read_bytes()
    with pytest.raises(ValueError):data.safe_copy(tmp_path/'missing.json',tmp_path/'missing.json')

def test_new_suffix_after_event_and_complete_origin_span_are_distinct():
    calls=[];catalog={'event':{'effective_session':'2022-12-22'}}
    current={'noncanonical_metadata_DTO':True,'repairs':['NONCANONICAL-24-INPUT-IDENTITY']}
    def reader(where,rows,value,**kw):
        calls.append((rows,kw));return {'synthetic-permission':('2022-12-22','ABMD',[380.,415.])},[{'synthetic':True}]
    assert data.added_permissions(None,[],catalog,current,reader)==({},[])
    assert data.added_permissions(None,[{'session':'2023-01-03'}],catalog,current,reader)==({},[])
    assert calls==[]
    rows=[{'session':'2022-12-21'},{'session':'2022-12-23'}]
    allowed,resolved=data.added_permissions(None,rows,catalog,current,reader)
    assert resolved and allowed and calls==[(rows,dict(through='2022-12-23',input_descriptors=current['repairs']))]
    # Passing a whole origin span with a missing event still invokes the strict
    # reader, whose cardinality guard refuses the missing December22 row.
    from system_campaign_bounded_sensor_event_review import permissions
    with pytest.raises(ValueError,match='REQUIRED_COMMITTED_EVENT_PROOF'):
        data.added_permissions(None,rows,catalog,current,permissions)

def test_api_refuses_before_any_local_financial_import(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        data.build(None,None,None,None,phase=None,root_metadata=None,review_bounded_origin=None)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
