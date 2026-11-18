"""Single independently owned broker-free verifier, in the common image."""
from __future__ import annotations

# A disposable heartbeat probe must not initialize the financial verifier.
import sys
if __name__ == '__main__' and sys.argv[1:] == ['--health']:
    from sentinel.panel.verification_health import health
    raise SystemExit(health())

from datetime import datetime, timedelta, timezone
import json
import os
import signal
from threading import BoundedSemaphore, Event
import time
import uuid

from psycopg.errors import LockNotAvailable, QueryCanceled, SerializationFailure

from sentinel.panel import authority_reader as financial, model, observer_codec, observer_failure, read_projection
from sentinel.panel import operational_schema as schema
from sentinel.panel.verification_monitor import paper_unknown
from sentinel.panel.verification_health import VERIFIER_HEARTBEAT

HEARTBEAT = VERIFIER_HEARTBEAT
OWNER_LOCK = (1_397_050_964, 1_448_748_626)
OWNER_SECONDS = 610
OWNER_POLL_SECONDS = 15
CLOSE_RESERVATION_LEAD_SECONDS = 90 + OWNER_POLL_SECONDS
RETRY_SECONDS = 20
RETRY_POLL_SECONDS = .5


def _queued_subject(database_url, include_paper, owner_id):
    """Fresh exact subject and owner after resource grant; no proof or renewal."""
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL lock_timeout='300ms'")
        row = conn.execute(f'SELECT owner_id::text,expires_at>clock_timestamp() '
            f'FROM {schema.OWNER} WHERE id=1').fetchone()
        if row != (owner_id, True):
            raise ValueError('financial verifier owner unavailable at resource grant')
        return read_projection.subject(conn, database_url, 'PAPER' if include_paper else 'SHADOW')
    finally:
        conn.rollback(); conn.close()


def _observe_shadow(database_url):
    from sentinel.feed import calendar
    from sentinel.panel import sources

    def clock():
        return datetime.now(timezone.utc)

    started = clock()
    # Only a positive result for the earlier session ever needs the second read.
    # The Reader owns the original worker deadline across both observations.
    repeated = False
    while True:
        rows, details, history, errors = sources._dual_authority_rows(database_url,
            now=started, include_paper=False, observation_clock=clock,
            propagate_corpus_lock=True, propagate_read_unavailability=True,
            project_execution_context=False)
        finished = clock()
        if finished < started:
            raise ValueError('financial observer clock regressed')
        if details or history:
            raise ValueError('unexpected shadow observation shape')
        proof = next((row.operational_fact for row in rows if row.key == 'shadow_verification'
                      and row.status == model.OK), None)
        if proof is None or str(proof.session) == calendar.latest_closed_session(finished):
            return rows, errors, finished
        if repeated or str(proof.session) != calendar.latest_closed_session(started):
            raise ValueError('verified shadow session does not match the current close')
        started = finished
        repeated = True


def _observe_once(database_url, include_paper, expected_key):
    if read_projection.subject_for(database_url, include_paper) != expected_key:
        raise observer_failure.ObservationSuperseded(
            'BEFORE_OBSERVATION', 'verification subject changed before observation')
    if not include_paper:
        rows, errors, observed = _observe_shadow(database_url)
    else:
        from sentinel.panel import sources
        from sentinel import informational_paper_mirror
        from sentinel.feed import readers, store
        conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=sources.STATEMENT_TIMEOUT_MS)
        try:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = [sources._dual_paper_row(conn, informational_paper_mirror=informational_paper_mirror,
                                            publication=readers, feed_store=store)]
            errors = []
        finally:
            conn.rollback(); conn.close()
        observed = datetime.now(timezone.utc)
    result = observer_codec.pack(rows, errors, observed_at=observed)
    if read_projection.subject_for(database_url, include_paper) != expected_key:
        raise observer_failure.ObservationSuperseded(
            'AFTER_OBSERVATION', 'verification subject changed during observation')
    return result


def observe(database_url, include_paper, expected_key):
    from sentinel.feed.publication import CorpusLockUnavailable
    from sentinel.panel.shadow_source_wait import observe_preparation
    if include_paper:
        preparation = observe_preparation(database_url, include_paper, expected_key)
        if preparation is not None:
            return preparation
    try:
        return financial.retry_observation_read(lambda: _observe_once(database_url, include_paper, expected_key))
    except CorpusLockUnavailable:
        from sentinel.panel import publication_wait
        result=publication_wait.observe(database_url,include_paper,expected_key)
        if result is None:
            raise
        return result


def diagnosed_observe(database_url, include_paper, expected_key, *, history_memo=None):
    if history_memo is None:
        return observer_failure.capture(observe, database_url, include_paper, expected_key)
    from sentinel.panel import mirror_history
    token = mirror_history.current_memo.set(history_memo)
    try:
        return observer_failure.capture(observe, database_url, include_paper, expected_key)
    finally:
        mirror_history.current_memo.reset(token)


def snapshot(reader, result, *, scope, now):
    """Preserve original completed or pending clocks, including negative results."""
    with reader.lock:
        key = reader.configuration
        if key is None:
            return None
        if reader.completed is not None:
            rows, errors, observed = reader.completed
            expiry = observed+timedelta(seconds=financial.FRESH_SECONDS)
            if len(rows) == 1 and model.activation_fee_paper_pending(rows[0]):
                expiry = min(expiry, rows[0].valid_until)
        else:
            rows, _, _, errors = result
            retained = reader.negative_result if scope == 'PAPER' else None
            if (retained is not None and len(rows) == 1 and not errors
                    and rows[0].key == retained[0].key and rows[0].status == retained[0].status
                    and rows[0].as_of == retained[0].as_of):
                # The original receipt and attempt retain their own subject and clocks.
                # Rebinding the row would make a dated failure a new observation.
                return None
            current_check = (reader.pending is not None and reader.pending_key == key
                             and any(row.recovery is not None
                                     and row.recovery.phase == 'FINANCIAL_VERIFICATION'
                                     for row in rows))
            observed = (reader.pending_at if current_check
                        else reader.last_result_at or reader.pending_at)
            if observed is None:
                return None
            deadlines = [row.valid_until for row in rows if row.valid_until is not None]
            expiry = min([observed+timedelta(seconds=financial.FRESH_SECONDS), *deadlines])
        if not observed <= now <= expiry:
            return None
        return read_projection.make(scope,key,rows,errors,observed_at=observed,valid_until=expiry)


def _restore_readers(conn, readers, database_url, *, now):
    """Resume current completed display evidence, never another owner's job."""
    previous = {}
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        schema.require_schema(conn)
        try:
            facts = read_projection._subject_facts(conn)
        except (ValueError,TypeError,KeyError,OverflowError):
            return previous
        for scope, reader in readers.items():
            try:
                key = read_projection._subject(conn,database_url,scope,facts=facts)
                row = conn.execute(f'SELECT subject_sha256,observed_at,valid_until,envelope,signature FROM {schema.RECEIPTS} WHERE scope=%s',
                                   (scope,)).fetchone()
                if (row is None or row[0] != key or row[1].isoformat() != row[3].get('observed_at')
                        or row[2].isoformat() != row[3].get('valid_until')):
                    continue
                rows, _, _, errors = read_projection.decode(row[3],row[4],
                    current_subject=key,scope=scope,now=now)
                if (row[2] != row[1]+timedelta(seconds=financial.FRESH_SECONDS)
                        or any(item.recovery is not None
                               and item.recovery.phase == 'FINANCIAL_VERIFICATION' for item in rows)):
                    continue
                reader.answer = (key,observer_codec.pack(rows,errors,observed_at=row[1]),None,now)
                previous[scope] = (row[3],row[4])
            except (ValueError,TypeError,KeyError,OverflowError,AttributeError):
                # Absent or malformed display evidence starts ordinary work.
                # No current subject, owner or database failure is repaired.
                continue
    finally:
        conn.rollback()
    return previous


def _drain_readers(readers):
    # Reader already owns finite queue/work/subprocess-reap deadlines. Joining
    # those existing jobs creates no new admission or fresh time allowance.
    for reader in readers.values():
        with reader.lock:
            pending=reader.pending
        if pending is not None:
            pending.join()


def _release_owner(conn, readers):
    _drain_readers(readers)
    conn.rollback()
    conn.close()


def _owner_deadline(started, row):
    expires, database_now = row
    remaining = min(OWNER_SECONDS, (expires-database_now).total_seconds())
    deadline = started+remaining
    if not time.monotonic() < deadline:
        raise ValueError('verifier ownership expired')
    return deadline


def _renew_owner(conn, owner_id, deadline):
    started = time.monotonic()
    if not started < deadline:
        raise ValueError('verifier ownership expired')
    row = conn.execute(
        f'UPDATE {schema.OWNER} SET expires_at=clock_timestamp()+INTERVAL \'610 seconds\' '
        'WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp() '
        'RETURNING expires_at,clock_timestamp()', (owner_id,)).fetchone()
    if row is None:
        raise ValueError('verifier ownership lost')
    if not time.monotonic() < deadline:
        conn.rollback()
        raise ValueError('verifier ownership expired during renewal')
    renewed = _owner_deadline(started, row)
    conn.commit()
    if not time.monotonic() < deadline:
        raise ValueError('verifier ownership expired during commit')
    return renewed


def _require_iteration_time(deadline):
    if not time.monotonic() < deadline:
        raise TimeoutError('verifier retry or ownership deadline expired')


def _opening_scan_reserve(conn, now):
    """Read the current bound cycle's short opening resource reservation."""
    cycle = conn.execute(
        "SELECT c.state,c.execution_open_at,c.execute_at,c.execution_close_at,c.next_wake_at,"
        "c.diagnostic->>'retry_phase' FROM sentinel_automation_cycles c"
        " JOIN sentinel_automation_control a ON a.id=1 AND a.generation=c.control_generation"
        " JOIN sentinel_automation_lease l ON l.id=1 AND l.control_generation=a.generation"
        " AND l.expires_at>clock_timestamp()"
        " JOIN sentinel_account_binding b ON b.id=1 AND b.deployment_id=c.deployment_id"
        " AND b.broker=c.broker AND b.broker_account_id=c.broker_account_id"
        " AND b.takeover_epoch=c.takeover_epoch"
        " WHERE a.enabled AND NOT a.kill_switch_engaged AND b.broker='alpaca'"
        " AND b.ownership_state='SENTINEL_OWNED' AND a.authority_verdict='PASS'"
        " AND c.effective_session=(%s AT TIME ZONE 'America/New_York')::date"
        " ORDER BY c.created_at DESC,c.cycle_id DESC LIMIT 1", (now,)).fetchone()
    if cycle is None:
        return None
    state, opened, execute, closed, wake, retry = cycle
    cutoff = min(closed, opened + timedelta(minutes=10))
    if not opened <= execute < cutoff or not execute - timedelta(seconds=90) <= now < cutoff:
        return None
    if (state == 'WAITING_OPEN' and now <= execute + timedelta(seconds=15)
            or state in {'EXECUTING', 'RECONCILING'}) or (
            state == 'RETRY_WAIT' and retry == 'RECOVER' and wake is not None
            and wake <= now + timedelta(seconds=30)):
        return cutoff
    return None


def _closing_scan_reserve(conn, now):
    """Defer optional scans for the exact closing boundary or a live callback."""
    from sentinel.automation.callback_observation import ENABLED, active_instance
    row = conn.execute(f"""
        WITH tick AS MATERIALIZED (
            SELECT %s::timestamptz AS at, clock_timestamp() AS database_now
        ), market AS (
            SELECT at, database_now, (at AT TIME ZONE 'America/New_York')::date AS session
            FROM tick
        )
        SELECT CASE WHEN c.effective_session=market.session THEN 'SETTLED'
                    WHEN c.state='RETRY_WAIT' AND c.diagnostic->>'retry_phase'='REFRESH'
                        THEN 'SOURCE_JOB' ELSE 'CALLBACK' END,
               CASE WHEN c.effective_session=market.session
                        THEN LEAST(c.execution_close_at+INTERVAL '60 seconds',l.expires_at)
                    WHEN c.state='RETRY_WAIT' AND c.diagnostic->>'retry_phase'='REFRESH'
                        THEN LEAST(c.next_wake_at,c.execution_open_at,l.expires_at)
                    ELSE LEAST(s.callback_deadline_at,c.execution_open_at,l.expires_at) END,
               c.decision_session,c.prepare_at
        FROM sentinel_automation_cycles c
        JOIN sentinel_automation_control a ON a.id=1
        JOIN sentinel_automation_lease l ON l.id=1 AND l.control_generation=a.generation
        LEFT JOIN sentinel_automation_service_instances s ON s.instance_id=l.holder_id
        JOIN sentinel_account_binding b ON b.id=1 AND b.deployment_id=c.deployment_id
          AND b.broker=c.broker AND b.broker_account_id=c.broker_account_id
          AND b.takeover_epoch=c.takeover_epoch
          AND (a.deployment_id,a.broker,a.broker_account_id,a.takeover_epoch)
              =(b.deployment_id,b.broker,b.broker_account_id,b.takeover_epoch)
        CROSS JOIN market
        WHERE {ENABLED}
          AND l.expires_at>market.database_now AND l.expires_at>market.at
          AND b.broker='alpaca' AND b.ownership_state='SENTINEL_OWNED'
          AND (
              (c.effective_session=market.session AND c.state='SUCCEEDED'
               AND market.at>=c.execution_close_at-make_interval(secs=>%s)
               AND market.at<c.execution_close_at+INTERVAL '60 seconds'
               AND ((a.generation=c.control_generation AND a.certificate_sha256=c.certificate_sha256
                     AND a.config_sha256=c.config_sha256)
                    OR (c.control_generation<a.generation AND NOT c.historical_state_only
                        AND c.failure_code IS NULL AND c.last_clean_reconciliation_id IS NOT NULL
                        AND c.completed_at BETWEEN c.execute_at AND market.at
                        AND EXISTS (SELECT 1 FROM sentinel_automation_events current_release
                            WHERE current_release.generation=a.generation AND current_release.action='KILL_RELEASED'
                              AND current_release.at>=a.enabled_at
                              AND current_release.at BETWEEN c.completed_at AND market.at
                              AND current_release.detail @> jsonb_build_object(
                                  'deployment_id',a.deployment_id,'broker',a.broker,
                                  'broker_account_id',a.broker_account_id,'takeover_epoch',a.takeover_epoch,
                                  'config_sha256',a.config_sha256,'certificate_sha256',a.certificate_sha256))
                        AND EXISTS (SELECT 1 FROM sentinel_execution_plans p
                            WHERE p.plan_id=c.plan_id AND p.decision_session=c.decision_session
                              AND p.effective_session=c.effective_session
                              AND (p.deployment_id,p.broker,p.broker_account_id,p.takeover_epoch)
                                  =(c.deployment_id,c.broker,c.broker_account_id,c.takeover_epoch))
                        AND EXISTS (SELECT 1 FROM sentinel_automation_events e
                            WHERE e.generation=c.control_generation AND e.action='KILL_RELEASED'
                              AND e.at<=c.completed_at AND e.detail @> jsonb_build_object(
                                  'deployment_id',c.deployment_id,'broker',c.broker,
                                  'broker_account_id',c.broker_account_id,'takeover_epoch',c.takeover_epoch,
                                  'config_sha256',c.config_sha256,'certificate_sha256',c.certificate_sha256)))))
              OR
              (a.generation=c.control_generation AND a.certificate_sha256=c.certificate_sha256
               AND a.config_sha256=c.config_sha256 AND c.decision_session=market.session
               AND market.at>=c.prepare_at AND market.at<c.execution_open_at
               AND ((c.state='RETRY_WAIT' AND c.plan_id IS NULL AND c.last_fence_token=l.fence_token
                     AND c.failure_code IN ('ClosingDataPending','RefreshPublicationPinUnavailable')
                     AND c.diagnostic->>'retry_phase'='REFRESH' AND c.next_wake_at>market.at)
                    OR ((c.state IN ('DISCOVERED','REFRESHING_DATA','PREPARING')
                         OR (c.state='RETRY_WAIT' AND c.plan_id IS NULL
                             AND c.failure_code='PreflightPublicationPinUnavailable'
                             AND c.diagnostic->>'retry_phase'='PREFLIGHT_RECOVER'
                             AND c.next_wake_at<=s.callback_started_at))
                        AND ({active_instance('market.database_now')})
                        AND s.callback_started_at<=market.at AND s.callback_deadline_at>market.at)))
          )
        ORDER BY (c.state='RETRY_WAIT' AND c.diagnostic->>'retry_phase'='REFRESH'),
                 c.created_at DESC,c.cycle_id DESC LIMIT 1
        """, (now, CLOSE_RESERVATION_LEAD_SECONDS)).fetchone()
    if row is None:
        return None
    kind, deadline, session, prepare_at = row
    if kind == 'SOURCE_JOB':
        return _source_job_reserve(conn, now, session, prepare_at, deadline)
    return deadline


def _source_job_reserve(conn, now, session, prepare_at, deadline):
    """Yield optional work only to the current, registered successor's live job."""
    from sentinel.feed import calendar, rolling_jobs
    rows = conn.execute("""
        SELECT j.request,j.request_sha256,j.created_at,LEAST(j.lease_until,j.deadline)
        FROM sentinel_snapshot_jobs j
        JOIN sentinel_operational_snapshot_jobs o USING(job_id)
        JOIN sentinel_snapshot_workers w ON w.job_id=j.job_id AND w.owner=j.owner
        WHERE j.owner IS NOT NULL AND j.fence>0
          AND j.state IN ('ACQUIRING','STAGING','VALIDATING','READY')
          AND j.publication_version IS NULL AND j.created_at BETWEEN %s AND %s
          AND j.lease_until>GREATEST(%s,clock_timestamp()) AND j.lease_until<=j.deadline
          AND j.request#>>'{window,sessions,-1}'=%s
          AND j.request->>'expected_publication_version'=(SELECT max(version)::text
                FROM sentinel_corpus_publications)
        LIMIT 2""", (prepare_at, now, now, str(session))).fetchall()
    if len(rows) != 1:
        return None
    raw, sha, created, job_deadline = rows[0]
    try:
        request = rolling_jobs.PreparationRequest.model_validate(raw)
        if (request.request_sha256 == sha and request.window.end == session
                and calendar.session_window(session.isoformat())[1] <= created):
            return min(deadline, job_deadline)
    except (TypeError, ValueError):
        pass
    return None


def _renew_completed_paper_subject(conn, reader, database_url, owner_id, previous, deadline,
                                   *, on_publication=None):
    """Rebind the completed fact while preserving its original observation and expiry."""
    from sentinel import receipt_authentication
    with reader.lock:
        if (reader.completed is None or reader.failure is not None
                or reader.identity_failure is not None
                or reader.pending is not None or reader.answer is not None):
            return False
        rows, errors, observed = reader.completed
        now = datetime.now(timezone.utc)
        if (errors or not timedelta(0) <= now-observed < timedelta(seconds=financial.REFRESH_SECONDS)
                or not read_projection.reusable_paper_outcome(rows, now=now)):
            return False
        prior = previous.get('PAPER')
        if (prior is None or not prior[0].get('valuation_basis')
                or prior[0]['subject_sha256'] != reader.configuration):
            return False
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            advanced = read_projection.rebase_completed_paper(conn, database_url, prior, now=now)
            if advanced is None:
                return False
            value, _ = advanced
            if value['subject_sha256'] == reader.configuration:
                return True
            _require_iteration_time(deadline)
            signature = receipt_authentication.sign(value)
            read_projection.publish(conn, owner_id=owner_id, value=value, signature=signature)
            _require_iteration_time(deadline)
        if on_publication is not None:
            on_publication()
        _require_iteration_time(deadline)
        previous['PAPER'] = value, signature
        reader.configuration = value['subject_sha256']
        return True


def _financial_publication(conn, database_url, scope, value, previous, *, now):
    """Prepare one current subject publication in the owner's coherent snapshot."""
    from sentinel import receipt_authentication
    from sentinel.panel import display_dependencies
    document = value[0]
    if read_projection.subject(conn, database_url, scope) != document['subject_sha256']:
        return None
    if scope != 'PAPER' or document['errors']:
        return value
    rows = [read_projection._decode_row(row) for row in document['rows']]
    if (previous is not None and rows[0].recovery is not None
            and rows[0].key == 'paper_reconciliation'
            and rows[0].recovery.phase == 'FINANCIAL_VERIFICATION'):
        retained = read_projection.rebase_completed_paper(
            conn, database_url, previous, now=now)
        if retained is not None and retained[0]['subject_sha256'] == document['subject_sha256']:
            return retained[0], receipt_authentication.sign(retained[0])
    if not read_projection.reusable_paper_outcome(rows, now=now):
        return value
    basis = display_dependencies.capture(conn, database_url)
    if (basis['native']['PAPER'] != document['subject_sha256']
            or basis['account_anchor'] is None):
        return value
    return read_projection.make(scope, document['subject_sha256'], rows, [],
        observed_at=datetime.fromisoformat(document['observed_at']),
        valid_until=datetime.fromisoformat(document['valid_until']), valuation_basis=basis)


def _refresh_readers(conn, readers, database_url, owner_id, previous, stopped, deadline,
                     *, on_publication=None):
    from sentinel.panel import attempt_store
    for scope, reader in readers.items():
        if stopped.is_set():
            break
        _require_iteration_time(deadline)
        if scope == 'PAPER' and _renew_completed_paper_subject(
                conn, reader, database_url, owner_id, previous, deadline,
                on_publication=on_publication):
            continue
        reserve = None
        if reader.completed is not None:
            from sentinel import local_paper
            if local_paper.enabled():
                with conn.transaction(force_rollback=True):
                    now = datetime.now(timezone.utc)
                    reserve = _opening_scan_reserve(conn, now) if scope == 'SHADOW' else None
                    reserve = reserve or _closing_scan_reserve(conn, now)
        options = {} if reserve is None else {'defer_refresh_until': reserve}
        result = reader.read(database_url, include_paper=scope == 'PAPER', **options)
        value = snapshot(reader, result, scope=scope, now=datetime.now(timezone.utc))
        financial_changed = False
        current = previous.get(scope)
        if value is not None and (current is None or {
                k:v for k,v in current[0].items() if k != 'valuation_basis'} != value[0]):
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            value = _financial_publication(conn, database_url, scope, value, current,
                now=datetime.now(timezone.utc))
            if value is not None and current != value:
                _require_iteration_time(deadline)
                read_projection.publish(conn, owner_id=owner_id, value=value[0], signature=value[1])
                financial_changed = True
            elif value is None:
                conn.rollback()
        retained_reader = getattr(reader, 'pending_failed_attempt', None)
        retained = retained_reader() if retained_reader is not None else None
        attempt = reader.attempt_state()
        diagnostic_key = attempt_store.scope_key(scope)
        diagnostic_changed = False
        if retained is not None:
            _require_iteration_time(deadline)
            diagnostic_changed = attempt_store.publish_owned(conn, owner_id=owner_id,
                scope=scope, attempt=retained, now=datetime.now(timezone.utc))
        if attempt is not None and (retained is not None or previous.get(diagnostic_key) != attempt):
            _require_iteration_time(deadline)
            diagnostic_changed = attempt_store.publish_owned(conn, owner_id=owner_id,
                scope=scope, attempt=attempt, now=datetime.now(timezone.utc)) or diagnostic_changed
        if financial_changed or diagnostic_changed or retained is not None:
            _require_iteration_time(deadline)
            conn.commit()
            if on_publication is not None:
                on_publication()
            if retained is not None:
                reader.ack_failed_attempt(retained['attempt_id'])
            _require_iteration_time(deadline)
            if financial_changed:
                previous[scope] = value
            if attempt is not None:
                previous[diagnostic_key] = attempt
        else:
            # An identical authenticated history can survive a verifier restart;
            # discard read-only state without refreshing its clocks.
            conn.rollback()
            if attempt is not None:
                previous[diagnostic_key] = attempt


def _run_owned_loop(conn, readers, database_url, owner_id, previous, stopped, deadline,
                    on_first_refresh=None, wakeup=None, on_owner_deadline=None,
                    on_publication=None):
    retry_until = None
    projection_started = False
    while not stopped.is_set():
        # Clear before observing answers. A completion before clear is consumed
        # by this refresh; one during/after refresh remains set for the wait.
        if wakeup is not None:
            wakeup.clear()
        started = time.monotonic()
        _require_iteration_time(min(deadline, retry_until) if retry_until is not None else deadline)
        try:
            deadline = _renew_owner(conn, owner_id, deadline)
            if on_owner_deadline is not None:
                on_owner_deadline(deadline)
            iteration_deadline = min(deadline, retry_until) if retry_until is not None else deadline
            options = {} if on_publication is None else {'on_publication': on_publication}
            _refresh_readers(conn, readers, database_url, owner_id, previous, stopped,
                iteration_deadline, **options)
            _require_iteration_time(iteration_deadline)
            if on_first_refresh is not None and not projection_started:
                on_first_refresh()
                projection_started = True
        except (QueryCanceled, LockNotAvailable, SerializationFailure):
            conn.rollback()
            # The session lock belongs to this connection. Reconnecting here
            # would silently discard exclusive ownership of admitted work.
            if conn.closed or conn.broken:
                raise
            if retry_until is None:
                retry_until = min(deadline, started+RETRY_SECONDS)
            remaining = retry_until-time.monotonic()
            if remaining <= 0:
                raise
            stopped.wait(min(RETRY_POLL_SECONDS, remaining))
            continue
        retry_until = None
        if not stopped.is_set():
            HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(), encoding='ascii')
            (stopped if wakeup is None else wakeup).wait(OWNER_POLL_SECONDS)


def run(*, stopped=None):
    from sentinel.feed import store
    database_url = os.environ.get('SENTINEL_DATABASE_URL','')
    if not database_url or os.environ.get('ALPACA_API_KEY') or os.environ.get('ALPACA_SECRET_KEY'):
        raise ValueError('verifier requires database and no broker credentials')
    stopped = stopped or Event()
    wakeup = Event()
    def stop(_signum, _frame):
        stopped.set()
        wakeup.set()
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,stop)
    conn = store.connect(database_url,connect_timeout=3,statement_timeout_ms=3000)
    owner_id = str(uuid.uuid4())
    readers = {}
    publisher = None
    owner = {'active':False, 'deadline':0.0}
    try:
        schema.require_schema(conn)
        if not conn.execute('SELECT pg_try_advisory_lock(%s,%s)',OWNER_LOCK).fetchone()[0]:
            raise ValueError('another verifier owns operational projections')
        started = time.monotonic()
        claimed = conn.execute(f'INSERT INTO {schema.OWNER} VALUES (1,%s,clock_timestamp()+INTERVAL \'610 seconds\') '
            'ON CONFLICT (id) DO UPDATE SET owner_id=EXCLUDED.owner_id,expires_at=EXCLUDED.expires_at '
            'RETURNING expires_at,clock_timestamp()', (owner_id,)).fetchone()
        conn.commit()
        deadline = _owner_deadline(started, claimed)
        owner.update(active=True, deadline=deadline)
        def work_allowed():
            return (owner['active'] and not stopped.is_set() and not conn.closed and not conn.broken
                    and time.monotonic() < owner['deadline'])
        slot = BoundedSemaphore(1)
        from functools import partial
        from sentinel.panel.mirror_history import ClassificationMemo
        try:
            paper_observer = partial(diagnosed_observe, history_memo=ClassificationMemo())
        except (OSError, MemoryError):
            paper_observer = diagnosed_observe
        readers = {scope:financial.Reader(evidence_reader=read_projection.subject_for,
            observer=paper_observer if scope == 'PAPER' else diagnosed_observe,
            expected_keys=read_projection.PAPER_KEYS if scope == 'PAPER' else read_projection.SHADOW_KEYS,
            unknown_factory=paper_unknown if scope == 'PAPER' else None,execution_slot=slot,
            retain_failed_attempt=True,
            completion=wakeup, work_allowed=work_allowed,
            queued_evidence_reader=lambda url,paper: _queued_subject(url,paper,owner_id),
            scope_label='paper alignment verification' if scope == 'PAPER' else 'retained portfolio verification')
            for scope in ('SHADOW','PAPER')}
        previous = _restore_readers(conn,readers,database_url,now=datetime.now(timezone.utc))
        from sentinel.panel.projection_service import Publisher
        publisher = Publisher(database_url, owner_id, stopped=stopped, wake_on_publication=True)
        # Establish actual queued/running/completed financial receipts before an
        # operational collector can classify a cold verifier's initial state.
        _run_owned_loop(conn, readers, database_url, owner_id, previous, stopped, deadline,
                        on_first_refresh=publisher.start, wakeup=wakeup,
                        on_owner_deadline=lambda value: owner.update(deadline=value),
                        on_publication=publisher.request_refresh)
    finally:
        owner['active'] = False
        stopped.set()
        wakeup.set()
        try:
            if publisher is not None:
                publisher.close()
        finally:
            _release_owner(conn,readers)
            HEARTBEAT.unlink(missing_ok=True)
    return 0


def health():
    from sentinel.panel.projection_service import HEARTBEAT as operational_heartbeat
    from sentinel.panel.verification_health import health as heartbeat_health
    return heartbeat_health(verifier_path=HEARTBEAT, operational_path=operational_heartbeat,
                            now=datetime.now(timezone.utc))


if __name__ == '__main__':
    import sys
    raise SystemExit(health() if sys.argv[1:] == ['--health'] else run())
