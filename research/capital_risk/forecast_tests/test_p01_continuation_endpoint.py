import ast
from pathlib import Path
from types import SimpleNamespace
import pytest

GUARD = Path(__file__).resolve().parents[1]/'p01_iac_unit_guard.py'


def first_gate(broken=False):
    tree=ast.parse(GUARD.read_bytes())
    cls,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='UnitGuard']
    fn,=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='advance']
    # Execute the actual date gate, stopping before canonical state is touched.
    fn.body=fn.body[:2]+[ast.parse("raise RuntimeError('POST_DATE_GATE')").body[0]]
    if broken:
        class OldBound(ast.NodeTransformer):
            def visit_Attribute(self,node):
                if ast.unparse(node)=='self.processing_endpoint': return ast.copy_location(ast.Name(id='END',ctx=ast.Load()),node)
                return self.generic_visit(node)
        fn=OldBound().visit(fn)
    def need(value,code):
        if not value: raise ValueError(code)
    ns={'EVENT':'2020-07-01','END':'2021-06-29','need':need}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-unit-date-gate>','exec'),ns)
    return ns['advance']


@pytest.mark.parametrize('day',['2021-06-30','2026-07-31'])
def test_actual_guard_allows_declared_future_endpoint(day):
    with pytest.raises(RuntimeError,match='POST_DATE_GATE'):
        first_gate()(SimpleNamespace(processing_endpoint='2026-07-31'),None,SimpleNamespace(session=day))


@pytest.mark.parametrize('day',['2020-06-30','2026-08-03'])
def test_actual_guard_retains_outside_scope_refusal(day):
    with pytest.raises(ValueError,match='EXACT_SELECTED_UNIT_SUFFIX_BOUND'):
        first_gate()(SimpleNamespace(processing_endpoint='2026-07-31'),None,SimpleNamespace(session=day))


def test_old_bound_falsifier():
    with pytest.raises(ValueError,match='EXACT_SELECTED_UNIT_SUFFIX_BOUND'):
        first_gate(broken=True)(SimpleNamespace(processing_endpoint='2026-07-31'),None,SimpleNamespace(session='2021-06-30'))
