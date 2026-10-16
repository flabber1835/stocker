"""Callback wiring retains one real-verifier scope through its postcondition."""
import asyncio
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime as module
from sentinel.execution.states import RuntimeState


@pytest.mark.parametrize('operation',['prepare','recover'])
@pytest.mark.parametrize('fail',[False,True])
def test_operational_callback_pins_factory_gateway_and_postcondition(monkeypatch,operation,fail):
    active = []
    closed = []
    conn = SimpleNamespace(close=lambda:closed.append(True))
    @contextmanager
    def pin(c, **kwargs):
        assert c is conn and not active
        active.append(True)
        try:
            yield object()
        finally:
            active.pop()
    cycle = SimpleNamespace(decision_session=date(2026,10,15),effective_session=date(2026,10,16),
        deployment_id='test',broker='alpaca',broker_account_id='paper',takeover_epoch=1)
    owner = object.__new__(module.ProductionAutomation)
    owner.connect = lambda:conn
    owner._operational_source_only = owner._dual_run_enabled = True
    owner._shadow_observation_id, owner._shadow_starting_cash = 'shadow', '50000'
    owner.sentinel_config = SimpleNamespace(base_url='https://paper-api.alpaca.markets')
    owner.automation_config = SimpleNamespace(fingerprint='f'*64)
    owner._assert_cycle_authority = lambda *a,**k:(cycle,SimpleNamespace(binding=object()))
    owner._require_operational_inputs = lambda c:None
    owner._recovery_identity_session = lambda c:('2026-10-16',True)
    def broker(c, session):
        assert active, 'production factory escaped callback publication pin'
        if fail:
            raise RuntimeError('fixture factory failure')
        return SimpleNamespace(capabilities=SimpleNamespace())
    owner._broker = broker
    def postcondition(*a,**k):
        assert active, 'prepared-plan postcondition escaped callback publication pin'
        return {}
    owner._require_dual_plan_shadow_match = postcondition
    for name in ('require_observation_integrity',):
        monkeypatch.setattr(module,name,lambda *a,**k:None)
    monkeypatch.setattr(module.feed_store,'require_feed_schema',lambda c:None)
    monkeypatch.setattr(module.schema,'require_runtime_schema',lambda c:None)
    monkeypatch.setattr(module.feed_inputs,'pinned',pin)
    monkeypatch.setattr(module,'_grant',lambda *a,**k:object())
    monkeypatch.setattr(module,'resolved_capability_graph',lambda broker:{})
    monkeypatch.setattr(module.journal,'in_flight_commands',lambda *a:[])
    plan = SimpleNamespace(plan_id='plan',data_version=1,publication_fingerprint='a'*64,
        fingerprint=lambda:'b'*64)
    async def prepare(**kwargs):
        assert active, 'paper preparation escaped callback publication pin'
        return SimpleNamespace(plan=plan,state_fingerprint='c'*64,sessions_replayed=0,
            warmup_sessions=0,superseded_plans=0)
    async def recover(**kwargs):
        assert active, 'paper recovery escaped callback publication pin'
        return SimpleNamespace(runtime_state=RuntimeState.BROKER_DEGRADED,observation=None,to_dict=lambda:{})
    monkeypatch.setattr(module.paper,'prepare_paper_plan',prepare)
    monkeypatch.setattr(module.paper,'recover_automated_paper_cycle',recover)
    context = SimpleNamespace(require_active=lambda:None)
    call = getattr(owner,operation)(context)
    if fail:
        with pytest.raises(RuntimeError,match='fixture factory failure'):
            asyncio.run(call)
    else:
        asyncio.run(call)
    assert not active and closed == [True]


@pytest.mark.parametrize('operation',['prepare','recover'])
def test_callback_scope_falsifier_detects_removed_pin(monkeypatch,operation):
    import inspect, textwrap
    source=textwrap.dedent(inspect.getsource(getattr(module.ProductionAutomation,operation)))
    broken=source.replace("if getattr(self, '_operational_source_only', False):",'if False:')
    assert broken!=source
    namespace={}
    exec(compile(broken,'callback-pin-falsifier','exec'),vars(module),namespace)
    monkeypatch.setattr(module.ProductionAutomation,operation,namespace[operation])
    with pytest.raises(AssertionError,match='production factory escaped'):
        test_operational_callback_pins_factory_gateway_and_postcondition(monkeypatch,operation,False)
