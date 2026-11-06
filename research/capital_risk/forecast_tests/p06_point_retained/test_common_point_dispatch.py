"""Actual admitted metadata and reversible mode hooks; no financial imports."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
import system_campaign_bounded_lifecycle_dispatch as common
import system_campaign_p06_abmd_retained as retained
import system_campaign_p06_abmd_reporting as reporting
from system_campaign_financial_partial import root_spec


@pytest.fixture
def routes(monkeypatch,tmp_path):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    # Bind the immutable original financial request while the active campaign
    # moves to other arms; the actual P06 root remains authoritative.
    captured=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial330-source-snapshot/system-campaign-factual-request.json')
    (tmp_path/'system-campaign-factual-request.json').write_bytes(captured.read_bytes())
    monkeypatch.setattr(common,'HERE',tmp_path)
    calls=[]
    @contextmanager
    def scope(module,spec,**kwargs):
        calls.append(kwargs['mode']);old=module.factual_overlay_needed
        module.factual_overlay_needed=lambda target:False
        try:yield
        finally:module.factual_overlay_needed=old
    def reject(*a,**k):raise AssertionError('ADMITTED_TARGET_ENTERED_READONLY_ONLY_BRIDGE')
    monkeypatch.setattr(retained,'entry_context',scope)
    monkeypatch.setattr(reporting,'entry_context',reject)
    return calls


@pytest.mark.parametrize('mode',['preflight','economic','review'])
def test_actual_admitted_context_owns_entire_mode_and_restores(routes,mode):
    original=lambda target:True;module=SimpleNamespace(factual_overlay_needed=original)
    with common.entry(module,root_spec('P06'),mode=mode,evidence='DATA_EVIDENCE',out='DATA_OUTPUT'):
        assert module.factual_overlay_needed(root_spec('P06')) is False
        assert routes==[mode]
    assert module.factual_overlay_needed is original


def test_removed_admission_guard_really_misroutes_actual_target(routes):
    spec=root_spec('P06');module=SimpleNamespace(factual_overlay_needed=lambda target:True)
    with common.entry(module,spec,mode='preflight',out='DATA_OUTPUT'):pass
    fn=next(n for n in ast.parse(Path(common.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='entry')
    candidates=[n.test for n in ast.walk(fn) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp)
                and "'root_admission' not in spec" in [ast.unparse(v) for v in n.test.values]
                and any(isinstance(v,ast.Call) and ast.unparse(v.func)=='reporting.selected' for v in ast.walk(n.test))]
    assert len(candidates)==1
    test=candidates[0];test.values=[v for v in test.values if ast.unparse(v)!="'root_admission' not in spec"]
    scope=dict(vars(common));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-actual-admission-routing-guard>','exec'),scope)
    with pytest.raises(AssertionError,match='ADMITTED_TARGET_ENTERED_READONLY_ONLY_BRIDGE'):
        with scope['entry'](module,spec,mode='preflight',out='DATA_OUTPUT'):pass
