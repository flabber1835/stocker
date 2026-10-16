"""The attended test's narrow startup grant cannot waive production fences."""
import ast
from datetime import datetime,timedelta,timezone
import inspect
from types import SimpleNamespace

import pytest

from tools import production_gateway_rehearsal as module
from tools.live_paper_rehearsal import Refused


@pytest.mark.parametrize('damage',[None,'database','system','restart','deployment','owner','unknown-reason'])
def test_fresh_empty_test_start_waiver_is_bound_to_actual_private_incarnation(monkeypatch,damage):
    started=datetime(2026,10,16,14,tzinfo=timezone.utc)
    saved=dict(test_database='rehearsal_execution_fixture',test_system_id='123456789',test_postmaster_start=started.isoformat())
    values=[saved['test_database'],saved['test_system_id'],started]
    if damage=='database':values[0]='sentinel'
    elif damage=='system':values[1]='production-system'
    elif damage=='restart':values[2]+=timedelta(seconds=1)
    deployment='foreign' if damage=='deployment' else 'attended-fixture'
    reason='PostgreSQL restarted during XNYS session 2026-10-16'
    if damage=='unknown-reason':reason='restore anchor changed'
    def fenced():
        if damage=='owner':raise Refused('attended owner lost')
    run=SimpleNamespace(saved=saved,deployment_id='attended-fixture',production_fenced=fenced)
    conn=SimpleNamespace(execute=lambda sql:SimpleNamespace(fetchone=lambda:tuple(values)))
    monkeypatch.setattr(module.binding,'require',lambda conn:SimpleNamespace(deployment_id=deployment))
    tree=ast.parse(inspect.getsource(module.main))
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='attended_fresh_database')
    namespace={**vars(module),'run':run,'original_restart_fence':lambda *a,**k:reason}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'attended-startup-grant','exec'),namespace)
    grant=namespace['attended_fresh_database']
    if damage=='owner':
        with pytest.raises(Refused,match='owner lost'):grant(conn,started.date())
    else:
        assert grant(conn,started.date())==(reason if damage else '')


def test_full_gateway_driver_uses_actual_production_callbacks():
    for name in ('prepare','recover','execute'):
        tree=ast.parse(inspect.getsource(module).replace('\r\n','\n'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GatewayCampaign')
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        body=ast.unparse(method)
        assert 'automation_runtime.ProductionAutomation.'+name+'(self, context)' in body
        assert '_execute_session_locked' not in body
