"""Original callback bounds must belong to the live current PostgreSQL fence."""
import pytest
from sentinel.automation import store
from sentinel.automation.model import AutomationConfig
from sentinel.panel import sources
from tests.sentinel.test_automation_store import conn, pg, enable, cycle_spec


@pytest.mark.parametrize('change', ['expired', 'heartbeat', 'lease', 'fence', 'generation', 'certificate', 'state', 'kill'])
def test_only_exact_live_callback_lends_stale_observation_budget(conn, change):
    cfg = AutomationConfig()
    control = enable(conn, cfg)
    permit = store.acquire_lease(conn, holder_id='callback-owner', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=permit, spec=cycle_spec(control, cfg))
    conn.execute("UPDATE sentinel_automation_cycles SET state='EXECUTING',updated_at=clock_timestamp() WHERE cycle_id=%s", (cycle.cycle_id,))
    conn.commit()
    store.register_instance(conn, instance_id=permit.holder_id, state='EXECUTE_CALLBACK',
                             next_wake_at=None, callback_deadline_seconds=900)
    store.record_authority_verdict(conn, verdict='PASS', detail='fixture authenticated authority',
                                  holder_id=permit.holder_id, fence_token=permit.fence_token,
                                  control_generation=permit.control_generation)
    original = sources._broker_callback(conn, cycle.cycle_id, 'EXECUTING')
    assert original is not None and original['started_at'] < original['deadline']
    assert sources._broker_callback(conn, cycle.cycle_id, 'EXECUTING') == original
    if change == 'expired':
        # Keep start/order/owner evidence coherent so only the expiry guard
        # rejects this formerly live invocation.
        conn.execute("UPDATE sentinel_automation_cycles SET updated_at=clock_timestamp()-INTERVAL '61 seconds'")
        conn.execute("UPDATE sentinel_automation_service_instances SET callback_started_at=clock_timestamp()-INTERVAL '60 seconds'")
    mutations = {
        'expired': "UPDATE sentinel_automation_service_instances SET callback_deadline_at=clock_timestamp()-INTERVAL '1 second'",
        'heartbeat': "UPDATE sentinel_automation_service_instances SET heartbeat_at=clock_timestamp()-INTERVAL '31 seconds'",
        'lease': "UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-INTERVAL '1 second'",
        'fence': "UPDATE sentinel_automation_cycles SET last_fence_token=last_fence_token+1",
        'generation': "UPDATE sentinel_automation_control SET generation=generation+1",
        'certificate': "UPDATE sentinel_automation_control SET certificate_sha256=repeat('b',64)",
        'state': "UPDATE sentinel_automation_service_instances SET state='IDLE'",
        'kill': "UPDATE sentinel_automation_control SET kill_switch_engaged=TRUE",
    }
    conn.execute(mutations[change]); conn.commit()
    assert sources._broker_callback(conn, cycle.cycle_id, 'EXECUTING') is None
