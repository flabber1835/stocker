"""Reject admitted metadata at the readonly-only routing seam; no book APIs."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
import system_campaign_bounded_lifecycle_dispatch as common
import system_campaign_p06_retained_reporting as reporting

def test_june_admission_route_guard_has_meaningful_removal(monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    raw=json.loads((Path(__file__).resolve().parents[2]/'system-campaign-financial-partials.json').read_bytes())['arms']['P06']
    # Explicitly unregistered, never serialized authority DTO. The worker's
    # actual root validator would reject it before any book operation.
    spec=deepcopy(raw);spec['EXPLICIT_NONCANONICAL_AUTHORITY_DTO']=True
    spec['root_admission']={'EXPLICIT_NONCANONICAL_AUTHORITY_DTO':True}
    assert reporting.selected(spec)
    def reject(*a,**k):raise AssertionError('ADMITTED_JUNE_TARGET_ENTERED_READONLY_BRIDGE')
    monkeypatch.setattr(reporting,'entry_context',reject)
    module=SimpleNamespace(factual_overlay_needed=lambda target:False)
    with common.entry(module,spec,mode='preflight',out='DATA_OUTPUT'):pass
    fn=next(n for n in ast.parse(Path(common.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='entry')
    targets=[n.test for n in ast.walk(fn) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp)
        and any(isinstance(v,ast.Call) and ast.unparse(v.func)=='retained_reporting.selected' for v in ast.walk(n.test))]
    assert len(targets)==1;condition=targets[0]
    condition.values=[n for n in condition.values if ast.unparse(n)!="'root_admission' not in spec"]
    scope=dict(vars(common));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-admitted-June-routing-guard>','exec'),scope)
    with pytest.raises(AssertionError,match='ADMITTED_JUNE_TARGET_ENTERED_READONLY_BRIDGE'):
        with scope['entry'](module,spec,mode='preflight',out='DATA_OUTPUT'):pass
