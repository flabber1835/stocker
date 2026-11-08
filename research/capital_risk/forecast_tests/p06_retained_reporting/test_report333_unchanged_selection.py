"""Whole target-selector AST and explicit noncanonical input-epoch DTOs."""
import ast,json
from copy import deepcopy
from pathlib import Path
import pytest
P=Path(__file__).parent
ORIGINAL=Path('C:/GitHub/stocker/.codex-tmp/select-p05-saved1070-report297-20261105.py')

def selected_tree():
    return next(n for n in ast.parse((P/'REPORT333-whole-unchanged-input-target-selector.py').read_bytes()).body if isinstance(n,ast.FunctionDef))

def comparisons():
    fn=selected_tree();a=[n for n in ast.walk(fn) if isinstance(n,ast.Compare)
        and ast.unparse(n) in ("cp['repairs'] == spec['repairs']","cp['run']['input_sha256'] == spec['input_sha256']")]
    assert len(a)==2;return a

def test_whole_target_selector_AST_undo_changes_only_the_two_input_epoch_predicates():
    old=next(n for n in ast.parse(ORIGINAL.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='build_target')
    fn=selected_tree()
    class Undo(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            text=ast.unparse(node)
            if text=="cp['repairs'] == spec['repairs']":
                self.count+=1;return ast.copy_location(ast.parse("cp['repairs'][:len(spec['repairs'])]==spec['repairs']",mode='eval').body,node)
            if text=="cp['run']['input_sha256'] == spec['input_sha256']":
                self.count+=1;return ast.copy_location(ast.parse("cp['run']['input_sha256']!=spec['input_sha256']",mode='eval').body,node)
            return self.generic_visit(node)
    undo=Undo();after=ast.fix_missing_locations(undo.visit(fn));assert undo.count==2
    assert ast.dump(old,include_attributes=False)==ast.dump(after,include_attributes=False)

def dto():
    spec=dict(EXPLICIT_NONCANONICAL_INPUT_EPOCH_DTO=True,repairs=[dict(input='ORIGINAL_METADATA_A')],input_sha256='NONCANONICAL_INPUT_A')
    current=dict(EXPLICIT_NONCANONICAL_INPUT_EPOCH_DTO=True,repairs=deepcopy(spec['repairs']),run=dict(input_sha256=spec['input_sha256']))
    return current,spec

def evaluate(nodes,cp,spec):
    body=deepcopy(nodes[0]) if len(nodes)==1 else ast.BoolOp(op=ast.And(),values=deepcopy(nodes))
    expression=ast.fix_missing_locations(ast.Expression(body=body))
    return eval(compile(expression,'<noncanonical-input-epoch-metadata-only>','eval'),{},dict(cp=cp,spec=spec))

def test_explicit_unchanged_input_metadata_is_accepted():
    cp,spec=dto();assert evaluate(comparisons(),cp,spec) is True

@pytest.mark.parametrize('which',['descriptors','hash'])
def test_each_new_input_identity_guard_has_meaningful_removal(which):
    cp,spec=dto();nodes=comparisons()
    if which=='descriptors':cp['repairs'].append(dict(input='FOREIGN_METADATA_B'))
    else:cp['run']['input_sha256']='FOREIGN_METADATA_B'
    assert evaluate(nodes,cp,spec) is False
    wrong="cp['repairs'] == spec['repairs']" if which=='descriptors' else "cp['run']['input_sha256'] == spec['input_sha256']"
    assert evaluate([n for n in nodes if ast.unparse(n)!=wrong],cp,spec) is True
