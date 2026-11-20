"""The reviewed 24-hour rolling-input preparation child used by every host entry."""
CODE = r'''
import hashlib
import json, os

SUCCESS_MARKER = 'SENTINEL_GO_PREPARATION='
RECOVERY_MARKER = 'SENTINEL_GO_PREPARATION_RECOVERY='
FAILURE_MARKER = 'SENTINEL_GO_PREPARATION_FAILURE='
IDENTITY_REASON_CODES = {
    'NO_PERMANENT_ID': 'SOURCE_IDENTITY_NO_PERMANENT_ID',
    'IDENTITY_INTERVAL_GAP': 'SOURCE_IDENTITY_INTERVAL_GAP',
    'TICKER_REUSE_UNRESOLVED': 'SOURCE_IDENTITY_TICKER_REUSE_UNRESOLVED',
    'AMBIGUOUS_IDENTITY': 'SOURCE_IDENTITY_AMBIGUOUS',
}


def failure_detail(exc):
    raw = str(exc).strip()
    if not raw:
        return {}
    digest = hashlib.sha256(raw.encode('utf-8', errors='replace')).hexdigest()
    lowered = raw.lower()
    prohibited = ('http://', 'https://', 'api_key', 'api-key', 'password',
                  'authorization', 'postgres://', 'postgresql://', 'apca-api-')
    value = {'detail_sha256': digest}
    if any(item in lowered for item in prohibited) or '\n' in raw or '\r' in raw:
        return value
    from sentinel.source_diagnostic import coverage_diagnostic
    source = coverage_diagnostic(raw)
    if source is not None:
        value['source_coverage'] = source
    if len(raw) > 420:
        raw = raw[:365] + ' ... [sha256:%s]' % digest[:16]
    value['detail'] = raw
    return value


def reason_code(phase, exc):
    name = type(exc).__name__
    if name == 'BackupHorizonExceeded':
        return 'BACKUP_RUNTIME_HORIZON_EXCEEDED'
    if name == 'JobDeadlineExceeded':
        return 'PREPARATION_DEADLINE_EXHAUSTED'
    if name == 'AcquisitionResourceExceeded':
        return 'SOURCE_RESOURCE_LIMIT'
    lowered = str(exc).lower()
    if name == 'SeedIdentityCollision':
        return 'SOURCE_IDENTITY_COLLISION'
    if name in {'VendorPublicationUnstable', 'SourceRevision'}:
        return 'SOURCE_PUBLICATION_UNSTABLE'
    if name == 'SeedHistoryIncomplete':
        return 'SOURCE_SEED_COVERAGE_INCOMPLETE'
    if name == 'PartCorrupt':
        return 'ACQUISITION_PART_CORRUPT'
    if name == 'SourceRecoveryExhausted':
        return 'SOURCE_RECOVERY_EXHAUSTED'
    if name == 'OperationalAcquisitionRefused':
        return 'OPERATIONAL_ACQUISITION_BOUND_EXCEEDED'
    if name == 'ExportPending':
        return 'SOURCE_EXPORT_PENDING'
    if name == 'MutationCursorUnavailable':
        return 'LOCAL_CURSOR_MISSING'
    if name == 'HistoricalIdentityMutation':
        return 'SOURCE_IDENTITY_HISTORY_MUTATION'
    if name == 'SepMutationIdentityRefused':
        identity_reason = str(getattr(exc, 'reason_code', '') or '')
        return IDENTITY_REASON_CODES.get(
            identity_reason, 'SOURCE_IDENTITY_UNRESOLVED')
    if name == 'SourceAuthorityRefused':
        if 'source cursor' in lowered:
            return 'LOCAL_CURSOR_CORRUPT'
        if 'no positive raw close' in lowered:
            return 'SOURCE_RAW_CLOSE_INVALID'
        if 'lastupdated' in lowered or 'invalid date' in lowered:
            return 'SOURCE_CDC_INVALID'
        return 'SOURCE_AUTHORITY_REFUSED'
    return {
        'RUNTIME_IMPORT': 'PREPARATION_RUNTIME_IMPORT_FAILURE',
        'DATABASE_CONNECT': 'PREPARATION_DATABASE_CONNECT_FAILURE',
        'BACKUP_DURABILITY': 'PREPARATION_BACKUP_DURABILITY_REFUSED',
        'SCHEMA_MIGRATION': 'PREPARATION_SCHEMA_MIGRATION_FAILED',
        'SOURCE_FINAL_FRONTIER': 'PREPARATION_SOURCE_FINAL_FRONTIER_FAILED',
        'DAILY_CATCHUP': 'PREPARATION_DAILY_CATCHUP_FAILED',
        'PUBLICATION_CHECK': 'PREPARATION_PUBLICATION_CHECK_FAILED',
    }.get(str(phase), 'PREPARATION_RUNTIME_FAILURE')


def emit_failure(phase, exc):
    value = {
        'phase': str(phase),
        'error_type': type(exc).__name__,
        'reason_code': reason_code(phase, exc),
        'schema_migration_attempted': schema_attempted,
        'bounded_market_data_daily_attempted': daily_attempted,
    }
    if type(exc).__name__ == 'SepMutationIdentityRefused':
        identity_reason = str(getattr(exc, 'reason_code', '') or '')
        if identity_reason:
            value['identity_reason'] = identity_reason
    value.update(failure_detail(exc))
    if type(exc).__name__ == 'BackupHorizonExceeded' and exc.resume_job_id:
        value['resume_job_id'] = exc.resume_job_id
    print(FAILURE_MARKER + json.dumps(value, sort_keys=True), flush=True)


c = None
discard_connection = False
schema_attempted = False
daily_attempted = False
phase = 'RUNTIME_IMPORT'
try:
    from datetime import datetime, timezone
    from sentinel import backup_guard, schema
    from sentinel.feed import calendar, operational_snapshot, rolling_go_inputs, publication, store, progress, writer_schedule
    from sentinel.shadow_runtime import publication_not_before

    phase = 'DATABASE_CONNECT'
    progress.emit('database_connect', 'started')
    c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
    phase = 'BACKUP_DURABILITY'
    progress.emit('backup_durability', 'started')
    backup_guard.require_writes_permitted(
        c, operation='NAS financial preparation')
    phase = 'SCHEMA_MIGRATION'
    progress.emit('schema_migration', 'started', reason='BEHAVIORAL_SCHEMA')
    schema_attempted = True
    schema.ensure_schema(c)
    progress.emit('schema_validation', 'started', reason='FEED_SCHEMA')
    store.require_feed_schema(c)
    progress.emit('schema_migration', 'completed')

    phase = 'SOURCE_FINAL_FRONTIER'
    now = datetime.now(timezone.utc)
    target = operational_snapshot.source_final_session(now)
    execution_session = calendar.next_session(target)
    execution_open, _execution_close = calendar.session_window(execution_session)
    source_final = now >= publication_not_before(target)
    following_open_future = now < execution_open.astimezone(timezone.utc)

    phase = 'DAILY_CATCHUP'
    progress.emit('daily_catchup', 'started', date_to=target)
    daily_attempted = True
    from sentinel import retained_go
    recovered = retained_go.prepare(c, target_session=target,
        absolute_deadline=rolling_go_inputs.deadline_from_host(
            os.environ.get('SENTINEL_GO_PREPARATION_DEADLINE')),
        resume_job_id=os.environ.get('SENTINEL_GO_RESUME_JOB_ID'))
    print(RECOVERY_MARKER + json.dumps({
        'mode': recovered['status'],
        'input_contract': recovered['schema'],
    }, sort_keys=True), flush=True)

    phase = 'PUBLICATION_CHECK'
    progress.emit('publication_check', 'started', date_to=target)
    after = rolling_go_inputs.current(c)
    visible = after.window_end if after is not None else None
    current = (
        after is not None and after.window_end is not None
        and after.window_end >= target and visible == target
        and publication.chain_gaps(c) == [])
    print(SUCCESS_MARKER + json.dumps({
        'schema_migrated': True,
        'source_not_before_satisfied': source_final,
        'following_open_future': following_open_future,
        'bounded_market_data_daily': daily_attempted,
        'publication_current': current,
    }, sort_keys=True), flush=True)
except BaseException as exc:
    if c is not None:
        discard_connection = writer_schedule.connection_discarded(exc)
        if discard_connection:
            raise
        try:
            c.rollback()
        except BaseException:
            pass
    emit_failure(phase, exc)
    raise
finally:
    if c is not None and not discard_connection:
        c.close()
'''.strip()
