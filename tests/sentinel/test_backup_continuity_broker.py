"""Degraded continuity never masquerades as a newly verified external chain."""
from __future__ import annotations

import asyncio
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel.execution import authority_gate
from sentinel.execution.guarded import BrokerOperation


class Connection:
    def __init__(self):self.commits=0;self.closed=False
    def commit(self):self.commits+=1
    def close(self):self.closed=True


def test_fresh_broker_guard_uses_continuity_without_publishing_false_chain(monkeypatch):
    conn=Connection();calls=[]
    def proof(connection,**kwargs):
        calls.append(kwargs)
        return dict(enabled=True,backup_state='DEGRADED',independent_archive_current=False)
    def false_chain(*args,**kwargs):raise AssertionError('degraded proof must not become RUNTIME_CHAIN')
    monkeypatch.setattr(authority_gate.backup_runtime_authority,'require',proof)
    monkeypatch.setattr(authority_gate.operational_evidence,'record_backup_proof',false_chain)
    monkeypatch.setattr(authority_gate,'load_rollout_state',lambda c:SimpleNamespace(mode='dual'))
    monkeypatch.setattr(authority_gate.feed_inputs,'require_current',lambda c:SimpleNamespace(version=1))
    monkeypatch.setattr(authority_gate,'_authority_operation',lambda grant,operation:'EXECUTE_WRITE')
    arguments=dict(connection_factory=lambda:conn,paper_base_url='https://paper-api.alpaca.markets',
        runtime_identity=lambda:{},strategy_identity=lambda:{},validate_grant=lambda *args:None,
        authority_check=lambda *args,**kwargs:SimpleNamespace(certificate_sha256='a'*64))
    guard=authority_gate.build_fresh_execution_guard(**arguments)
    asyncio.run(guard.before_mutation(SimpleNamespace(),BrokerOperation.SUBMIT))
    assert calls==[dict(operation='broker submit mutation',allow_continuity=True)]
    assert conn.commits==0 and conn.closed
    # Execute the removed-observability-guard control against the same callback
    # fixture; it must now attempt the forbidden successful-chain publication.
    source=textwrap.dedent(inspect.getsource(authority_gate.build_fresh_execution_guard))
    needle='and backup_proof.get("backup_state") != "DEGRADED"'
    assert source.count(needle)==1
    namespace=dict(authority_gate.build_fresh_execution_guard.__globals__)
    exec('from __future__ import annotations\n'+source.replace(needle,''),namespace)
    mutant=namespace['build_fresh_execution_guard'](**arguments)
    with pytest.raises(AssertionError,match='degraded proof must not become'):
        asyncio.run(mutant.before_mutation(SimpleNamespace(),BrokerOperation.SUBMIT))
