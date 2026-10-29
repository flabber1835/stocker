"""A common factual basis cannot conceal different economic terms."""
import ast,copy
from pathlib import Path
import pytest
from system_campaign_basis import semantics
from system_campaign_facts import digest


def data():
    base={'bundle_sha256':'a'*64,'archive_sha256':'b'*64}
    refs={'facts':'c'*64,'compiler':'d'*64}
    one={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':'1'*64,
        'source_evidence':[{'reference':k,'sha256':v} for k,v in refs.items()],
        'suppress':[],'add':[{'session':'2020-01-02','security_id':'X','cash_per_share':42.}]}
    two={**copy.deepcopy(one),'predecessor_checkpoint_sha256':'2'*64,'add':[]}
    return base,refs,one,two


def test_own_identity_and_descriptor_partition_do_not_change_actual_fact_basis():
    base,refs,one,two=data();actual=semantics(base,[one,two],refs)
    assert actual==semantics(base,[two,one],refs)
    changed=copy.deepcopy(one);changed['predecessor_checkpoint_sha256']='9'*64
    assert actual==semantics(base,[changed],refs)
    changed['add'][0]['cash_per_share']=43.
    assert digest(actual)!=digest(semantics(base,[changed],refs))


def test_missing_reference_conflicting_cash_and_wrong_compiler_refuse():
    base,refs,one,two=data()
    with pytest.raises(ValueError,match='ALL_FACTS_PRESENT'):semantics(base,[],refs)
    two['add']=[{**one['add'][0],'cash_per_share':43.}]
    with pytest.raises(ValueError,match='CONFLICTING_TERM'):semantics(base,[one,two],refs)
    one['source_evidence'][0]['sha256']='0'*64
    with pytest.raises(ValueError,match='DECLARED_FACT_COMPILER'):semantics(base,[one],refs)


def test_actual_compiler_guard_removal_falsifier():
    base,refs,one,two=data();one['source_evidence'][0]['sha256']='0'*64
    with pytest.raises(ValueError,match='DECLARED_FACT_COMPILER'):semantics(base,[one],refs)
    tree=ast.parse(Path(semantics.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='semantics')
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if any(isinstance(v,ast.Constant) and v.value=='COMMON_BASIS_DECLARED_FACT_COMPILER' for v in ast.walk(n)):return None
            return self.generic_visit(n)
    node=Remove().visit(node);scope=dict(semantics.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-fact-compiler-guard>','exec'),scope)
    assert scope['semantics'](base,[one],refs)['declared_fact_compilers']['facts']=='0'*64
