"""Read-only allocation diagnostic, not a service-cap acceptance run."""
import json
from pathlib import Path

from audit.economic_399.full_status import probe
from sentinel import shadow_observation
from sentinel.core.session import SessionState


def main():
    dsn = json.loads(Path('/evidence/database.json').read_text())['dsn']
    with probe.store.connect(dsn) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        store = shadow_observation.PostgresShadowObservationStore(
            conn, observation_id=probe.OBS, stream_state=True)
        probe.emit('start', **probe.memory())
        genesis = store.genesis()
        probe.emit('decoded_genesis', **probe.memory())
        state = SessionState.from_dict(genesis['initial_state'])
        probe.emit('canonical_state', **probe.memory())
        probe.emit('state_hash', state_sha256=state.state_hash, **probe.memory())
        value = state.to_dict()
        probe.emit('canonical_mapping', **probe.memory())
        assert value == genesis['initial_state']
        assert conn.execute('SHOW transaction_read_only').fetchone() == ('on',)
        probe.emit('unchanged_value', **probe.memory())


if __name__ == '__main__':
    main()
