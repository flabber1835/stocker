"""Fresh-process production policy probes for prefix ownership and restore fencing."""
import os
import subprocess
import sys
import pytest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg

SCRIPT=r'''
import asyncio,sys
from decimal import Decimal as D
from sentinel import binding as B, schema
from sentinel.execution import journal,reconcile as R,alpaca,recovered_order_policy as policy
from sentinel.execution.contract import BrokerInstrument,Side
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import RuntimeState
from sentinel.feed import store
assert policy.strict_enabled()
assert journal.adopt_recovered_order is policy.refuse_unauthenticated_recovered_order
assert getattr(alpaca.strict_advance,'_sentinel_restore_grade_guard',False)
c=store.connect(sys.argv[1])
store.migrate_schema(c)
schema.ensure_schema(c)
b=SimulatedBroker()
B.bind(c,deployment_id='audit399',broker='sim',broker_account_id='SIM-ACCOUNT')
with c.cursor() as cur:
    cur.execute('UPDATE sentinel_account_binding SET established_at=%s WHERE id=1',(b.now,))
c.commit()
dep=DeploymentIdentity('audit399','sim','SIM-ACCOUNT',1)
mode=sys.argv[2]
if mode=='prefix':
    key='sntl-manual-unattributed'
    asyncio.run(b.submit(client_key=key,instrument=BrokerInstrument('SEC-AAA','AAA','b-AAA'),side=Side.BUY,quantity=D(1)))
    b.fill(key)
    with journal.writer_lock(c,recovery_only=True):
        result=asyncio.run(R.reconcile(broker=b,conn=c,binding=None,deployment=dep))
    assert result.runtime_state is RuntimeState.RECONCILING,result
    assert not result.transport_ready
    assert journal.load_commands(c,dep)==()
    assert result.foreign_positions==('SEC-AAA',)
    print({'policy':'STRICT_V1','prefix_only_adoption':'REFUSED','local_commands':0,'runtime':result.runtime_state.value})
else:
    with c.cursor() as cur: cur.execute('UPDATE sentinel_account_binding SET takeover_epoch=2 WHERE id=1')
    c.commit()
    try: alpaca.strict_advance(c,b.now)
    except alpaca.RestoreGradeIncreaseDeferred as exc:
        assert 'restore-grade' in str(exc)
        print({'policy':'STRICT_V1','epoch':2,'restore_horizon':'FENCED'})
    else: raise AssertionError('restored namespace must be fenced')
c.close()
'''
@pytest.mark.parametrize('mode',['prefix','restore'])
def test_fresh_process_strict_policy(conn,mode):
    env=dict(os.environ,SENTINEL_RECOVERED_ORDER_AUTHORITY='STRICT_V1')
    done=subprocess.run([sys.executable,'-c',SCRIPT,conn.info.dsn,mode],env=env,
        text=True,capture_output=True,timeout=40)
    print(done.stdout)
    assert done.returncode==0,done.stdout+'\n'+done.stderr

__all__ = ['conn', 'pg']
