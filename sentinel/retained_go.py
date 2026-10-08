"""GO preparation dispatch that preserves an authenticated existing book."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import time

from sentinel import rolling_checkpoint as origin, rolling_runtime, runtime_admission
from sentinel.feed import rolling_go_inputs as inputs
from sentinel.feed.rolling_contract import digest

MANIFEST_ENV = 'SENTINEL_RETAINED_SOURCE_MANIFEST'


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise origin.RollingColdStartRefused('RETAINED_MANIFEST_DUPLICATE_KEY')
        value[key] = item
    return value


def load_manifest(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4*1024*1024:
        raise origin.RollingColdStartRefused('RETAINED_MANIFEST_TOO_LARGE')
    return json.loads(raw, object_pairs_hook=_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite manifest')))


@contextmanager
def reviewed_process(context, *, data_publication_sha256, deadline):
    """Private broker-free child settings, derived from actual image facts only."""
    from sentinel import shadow_budget
    runtime = context['runtime']
    values = {'SENTINEL_SHADOW_OBSERVATION_ENABLED': '1',
        'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256': runtime['validated_source_identity_sha256'],
        'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256': runtime['validated_shadow_config_sha256'],
        'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256': data_publication_sha256,
        shadow_budget.DEADLINE_ENV: deadline.isoformat()}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def _with_backup_wait(conn, operation, *, deadline):
    """Keep retryable backup availability inside this GO's original cutoff."""
    from sentinel import backup_runtime_authority, shadow_budget
    from sentinel.feed import progress
    while True:
        shadow_budget.require_remaining(deadline)
        try:
            return operation()
        except backup_runtime_authority.BackupRuntimeUnavailable:
            conn.rollback()
            shadow_budget.require_remaining(deadline)
            remaining = max(0.0, (deadline-shadow_budget.now()).total_seconds())
            progress.emit('backup_durability', 'working', reason='BACKUP_AUTHORITY_WAIT',
                          remaining_seconds=math.ceil(remaining))
            time.sleep(min(10.0, remaining))


def _advance_with_backup_wait(conn, *, target_session, context, deadline):
    return _with_backup_wait(conn, lambda: rolling_runtime.service_advance(
        conn, through=target_session, observation_id=context['observation_id'],
        starting_cash=context['starting_cash'], acquisition_deadline=deadline), deadline=deadline)


def prepare(conn, *, target_session, absolute_deadline, resume_job_id=None):
    checkpoint = origin.read(conn)
    conn.rollback()
    if checkpoint is None:
        # Unknown/foreign lineage still fails in the original fresh-state guard.
        return inputs.prepare(conn, target_session=target_session,
            absolute_deadline=absolute_deadline, resume_job_id=resume_job_id)
    from sentinel import shadow_budget
    context = runtime_admission.current_context(observation_id=os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary'),
        starting_cash=os.environ.get('SENTINEL_SHADOW_STARTING_CASH', '50000'))
    runtime_admission._require_context(checkpoint, context)
    if runtime_admission.process_binding(checkpoint.runtime_identity) != runtime_admission.process_binding(context['runtime']):
        path = os.environ.get(MANIFEST_ENV)
        if not path:
            raise origin.RollingColdStartRefused('RETAINED_SOURCE_MANIFEST_REQUIRED')
        manifest = load_manifest(path)
        _with_backup_wait(conn, lambda: runtime_admission.admit(conn, context=context,
            manifest=manifest), deadline=absolute_deadline)
    with reviewed_process(context, data_publication_sha256=checkpoint.runtime_identity['validated_data_publication_sha256'],
            deadline=absolute_deadline):
        while True:
            shadow_budget.require_remaining(absolute_deadline)
            current, _, _, attested, _ = rolling_runtime._closure(conn, dict(context))
            conn.rollback()
            if current.session > target_session:
                raise origin.RollingColdStartRefused('RETAINED_GO_FRONTIER_AHEAD')
            if current.session == target_session:
                if attested is None:
                    # Recover the durable candidate's receipt without replaying
                    # its transition, including after an acknowledgement loss.
                    _advance_with_backup_wait(conn, target_session=target_session,
                        context=context, deadline=absolute_deadline)
                    continue
                with inputs.pinned(conn) as pub:
                    rolling_runtime._current(conn, current, pub)
                conn.rollback()
                break
            result = _advance_with_backup_wait(conn, target_session=target_session,
                context=context, deadline=absolute_deadline)
            if result.session <= current.session:
                raise origin.RollingColdStartRefused('RETAINED_GO_CONTINUATION_NO_PROGRESS')
    return {'status': 'RETAINED_STATE_VERIFIED', 'schema': inputs.SCHEMA}
