"""Durable operator review inside the existing page-build owner; no worker."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sentinel.panel import review_store as store
from sentinel.panel.review_model import OperatorReview

TOKEN_SCHEMA = 'sentinel.operator-review-view/1'
TOKEN_SECONDS = 30


def condition_evidence(panel, keys):
    """Diagnostic metadata only; never persist raw prose or change a verdict."""
    from sentinel.panel.presentation import _row_boundary
    result = {}
    for key in sorted(set(keys))[:32]:
        row = panel.row(key)
        if row is None:
            result[key] = {'code': 'BACKEND_SOURCE_UNAVAILABLE' if key == 'backend_sources'
                           else 'CURRENT_FACT_MISSING'}
            continue
        code = 'ROW_CONDITION'
        if row.is_future(panel.now):
            code = 'ROW_CLOCK_FUTURE'
        elif row.is_stale(panel.now):
            code = 'ROW_PROOF_EXPIRED'
        elif key == 'feed':
            if row.feed_readiness == 'AWAITING_VERDICT':
                code = 'FEED_BOUND_VERDICT_PENDING'
            elif 'CorpusLockUnavailable:' in row.detail:
                code = 'FEED_PUBLICATION_PIN_REFUSED'
            elif row.detail == 'could not read the feed — frontier timed out':
                code = 'FEED_FRONTIER_READ_TIMEOUT'
            elif row.value == 'UNREADABLE':
                code = 'FEED_READ_UNAVAILABLE'
            elif row.detail.startswith('contract NOT READY '):
                code = 'FEED_CONTRACT_FAILED'
            else:
                code = 'FEED_UNCLASSIFIED'
        boundary = _row_boundary(row)
        phase = row.recovery.phase if row.recovery is not None else None
        result[key] = {'code': code, 'raw_status': row.status,
            'effective_status': row.effective_status(panel.now),
            'sampled_at': panel.now.isoformat(),
            'as_of': row.as_of.isoformat() if row.as_of is not None else None,
            'original_valid_until': boundary.isoformat() if boundary is not None else None,
            'recovery_phase': phase if phase is not None and re.fullmatch('[A-Z0-9_]{1,64}', phase) else None,
            'value_sha256': hashlib.sha256(row.value.encode('utf-8')).hexdigest(),
            'detail_sha256': hashlib.sha256(row.detail.encode('utf-8')).hexdigest()}
    if len(set(keys)) > 32:
        result['_limit'] = {'code': 'DIAGNOSTIC_LIMIT', 'condition_count': len(set(keys))}
    return result


def failure_detail(error):
    """Actionable refusal copy without exposing driver/connection contents."""
    from sentinel.operational_catalog import OperationalCatalogRefused
    from psycopg import Error as DatabaseError
    if isinstance(error, OperationalCatalogRefused):
        return 'Dashboard review schema is missing or changed; qualified installation is required.'
    if isinstance(error, store.ReviewRefused):
        # These are only the finite static refusal messages in this boundary.
        return 'Review history refused: '+str(error)[:200]+'.'
    if isinstance(error, DatabaseError):
        return 'Dashboard review database is unavailable or exceeded its finite read/write budget.'
    return 'Dashboard review data could not be read or decoded.'


def view_subject(panel):
    from sentinel.panel.presentation import health_facts
    return hashlib.sha256(store.canonical({
        'facts': health_facts(panel),
        'rows': [(row.key, row.value if row.key == 'runtime_identity' else None,
                  row.source_publication_version, str(row.source_session),
                  row.paper_alignment,
                  row.paper_plan.plan_id if row.paper_plan else None,
                  row.trading_run.intent.plan_id if row.trading_run else None)
                 for row in panel.rows],
    })).hexdigest()


def _token(value):
    envelope = dict(view=value, signature=store.signature(value, purpose=TOKEN_SCHEMA))
    return base64.urlsafe_b64encode(store.canonical(envelope)).decode('ascii')


def decode_token(raw, now):
    store.require(isinstance(raw, str) and 0 < len(raw) <= 8192, 'operator review token missing')
    try:
        envelope = json.loads(base64.b64decode(raw, altchars=b'-_', validate=True))
        store.require(set(envelope) == {'view', 'signature'}, 'operator review token malformed')
        value = envelope['view']
        store.require(isinstance(value, dict) and set(value) == {
            'schema', 'scope', 'head', 'subject', 'issued_at', 'expires_at'},
            'operator review view malformed')
        store.authenticate(value, envelope['signature'], purpose=TOKEN_SCHEMA)
        issued = datetime.fromisoformat(value['issued_at'])
        expires = datetime.fromisoformat(value['expires_at'])
        store.require(value['schema'] == TOKEN_SCHEMA and issued.utcoffset() == timedelta(0)
                      and expires.utcoffset() == timedelta(0)
                      and expires - issued == timedelta(seconds=TOKEN_SECONDS)
                      and issued - timedelta(seconds=5) <= now < expires,
                      'operator review token expired or future')
        return value
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise store.ReviewRefused('operator review token invalid') from exc


def _notices(conn):
    from sentinel.notification_policy import CANCELLED_TEST_SQL
    rows = conn.execute('SELECT alert_id FROM sentinel_alert_outbox a '
        "WHERE severity='CRITICAL' AND ack_state='UNACKNOWLEDGED' "
        f"AND state<>'CANCELLED' AND NOT {CANCELLED_TEST_SQL} ORDER BY alert_id LIMIT 1001").fetchall()
    store.require(len(rows) <= 1000, 'operator review notification inventory exceeds bound')
    return [row[0] for row in rows]


def _result(conn, key, state, now, *, subject):
    active, warnings = state['active'], state['warnings']
    status = ('FAILED' if active else 'REVIEW' if warnings or state['head'] != state['reviewed_head']
              else 'CLEAN')
    reviewed = datetime.fromisoformat(state['reviewed_at']) if state['reviewed_at'] else None
    token = (_token(dict(schema=TOKEN_SCHEMA, scope=key, head=state['head'], subject=subject,
                        issued_at=now.isoformat(), expires_at=(now+timedelta(seconds=TOKEN_SECONDS)).isoformat()))
             if status == 'REVIEW' and not active and not warnings else None)
    return OperatorReview(scope=key, head=state['head'], reviewed_head=state['reviewed_head'],
        status=status, observed_at=now, reviewed_at=reviewed, active=active, warnings=warnings,
        events=store.recent(conn, key), token=token)


def record_verification_failure_owned(conn, *, scope, attempt):
    """Record a native historical incident; current active facts stay separate."""
    from sentinel.panel import observer_failure, review_schema
    store.require(scope in {'SHADOW', 'PAPER'}, 'verification review scope invalid')
    raw = (attempt.model_dump(mode='json', by_alias=True)
           if isinstance(attempt, observer_failure.Attempt) else attempt)
    current = observer_failure.Attempt.model_validate_json(store.canonical(raw))
    if current.outcome != 'FAILED':
        return False
    store.require(current.diagnostic is not None and current.diagnostic.outcome == 'FAILED',
                  'verification failure diagnostic missing')
    if not review_schema.require_schema(conn, allow_absent=True):
        return False
    key, now = store.scope(conn), store.database_now(conn)
    state = store.load_locked(conn, key, now)
    event_key = 'verification-failure:'+scope+':'+current.attempt_id
    if store.has_event(conn, key, event_key):
        return False
    store.append(conn, key, state, kind='REVIEW', event_key=event_key,
        details={'component': 'verifier', 'reason': 'Verification attempt failed',
                 'conditions': ['shadow_verification' if scope == 'SHADOW' else 'paper_reconciliation'],
                 'verification_scope': scope,
                 'attempt': current.model_dump(mode='json', by_alias=True)}, now=now)
    if not state['view_sha256']:
        state['view_sha256'] = hashlib.sha256(store.canonical(
            {'schema': 'sentinel.unobserved-operational-view/1',
             'scope': key, 'attempt_id': current.attempt_id})).hexdigest()
    store.save(conn, key, state, now)
    return True


class Recorder:
    """One process incarnation, retaining a failed observation until DB recovery.

    A lost process cannot silently lose the latch: its successor always appends
    an unreviewed incarnation event. This class starts no thread or monitor.
    """

    def __init__(self, *, component='dashboard', instance=None):
        if component not in {'dashboard', 'verifier'}:
            raise ValueError('unknown operational review component')
        self.component = component
        self.instance = instance or str(uuid.uuid4())
        self.lock = threading.Lock()
        self.pending_failure = False

    def read_failed(self):
        with self.lock:
            self.pending_failure = True

    def observe(self, panel, database_url):
        """Compatibility API; production collection uses observe_owned atomically."""
        try:
            with store.transaction(database_url) as conn:
                result = self.observe_owned(conn, panel, database_url)
            self.committed()
            return result
        except Exception as error:
            self.read_failed()
            return OperatorReview(scope='0'*64, head=0, reviewed_head=0, status='UNAVAILABLE',
                observed_at=panel.now, detail=failure_detail(error))

    def committed(self):
        """Clear the process latch only after the caller commits its transaction."""
        with self.lock:
            self.pending_failure = False

    def observe_owned(self, conn, panel, database_url):
        """Caller owns fencing, transaction and commit; never open another session."""
        from sentinel.panel.presentation import health_facts
        facts = health_facts(panel)
        required = {'runtime_identity', 'automation', 'automation_leader', 'authority',
                    'feed', 'broker', 'alpaca_account', 'backup_restore',
                    'automation_alerts', 'alert_dispatcher'}
        missing = required - {row.key for row in panel.rows}
        facts['active'] = sorted(set(facts['active']) | {'missing:'+key for key in missing})
        with self.lock:
            pending = self.pending_failure
        key, now = store.scope(conn), store.database_now(conn)
        state = store.load_locked(conn, key, now)
        incarnation = conn.execute('SELECT pg_postmaster_start_time()').fetchone()[0].isoformat()
        configuration = hashlib.sha256(store.canonical({
            'database': database_url,
            'commit': os.environ.get('SENTINEL_GIT_COMMIT', ''),
            'image': os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', ''),
        })).hexdigest()
        started = self.component+':'+self.instance+':'+configuration[:24]
        if not store.has_event(conn, key, started):
            store.append(conn, key, state, kind='STARTED', event_key=started,
                details={'component':self.component, 'reason':'Deployment or restart',
                         'commit':os.environ.get('SENTINEL_GIT_COMMIT', '')}, now=now)
        if state['database_incarnation'] and state['database_incarnation'] != incarnation:
            store.append(conn, key, state, kind='STARTED',
                event_key='database:'+incarnation,
                details={'component':'database', 'reason':'Database restart'}, now=now)
        state['database_incarnation'] = incarnation
        if pending:
            store.append(conn, key, state, kind='FAILED', event_key='deferred:'+str(state['head']+1),
                details={'conditions':['dashboard_read_unavailable'], 'recovered_before_recording':True}, now=now)
            store.append(conn, key, state, kind='RECOVERED', event_key='recovered:'+str(state['head']+1),
                details={'conditions':['dashboard_read_unavailable']}, now=now)
        if facts['active'] != state['active']:
            kind = 'FAILED' if facts['active'] else 'RECOVERED'
            store.append(conn, key, state, kind=kind, event_key='condition:'+str(state['head']+1),
                details={'conditions':facts['active'], 'previous':state['active'],
                         'evidence':condition_evidence(panel, facts['active']+state['active'])}, now=now)
        if facts['warnings'] != state['warnings']:
            kind = 'REVIEW' if facts['warnings'] else 'RECOVERED'
            store.append(conn, key, state, kind=kind, event_key='warning:'+str(state['head']+1),
                details={'conditions':facts['warnings'], 'previous':state['warnings'],
                         'evidence':condition_evidence(panel, facts['warnings']+state['warnings'])}, now=now)
        notices = _notices(conn)
        unseen = sorted(set(notices) - set(state['incidents']))
        if unseen:
            store.append(conn, key, state, kind='REVIEW', event_key='notices:'+str(state['head']+1),
                         details={'alert_ids':unseen}, now=now)
        state.update(active=facts['active'], warnings=facts['warnings'], incidents=notices,
                     view_sha256=view_subject(panel))
        store.save(conn, key, state, now)
        result = _result(conn, key, state, now, subject=state['view_sha256'])
        return result

    def acknowledge(self, panel, database_url, raw_token, *, actor, snapshot_guard=None):
        from sentinel.panel.presentation import health_facts
        facts = health_facts(panel)
        store.require(not facts['active'] and not facts['warnings'],
                      'resolve active conditions before acknowledging recovery')
        store.require(isinstance(actor, str) and 0 < len(actor) <= 120, 'operator identity missing')
        with store.transaction(database_url) as conn:
            if snapshot_guard is not None:
                snapshot_guard(conn, panel)
            key, now = store.scope(conn), store.database_now(conn)
            view = decode_token(raw_token, now)
            store.require(view['scope'] == key and view['subject'] == view_subject(panel),
                          'operator review scope or current state changed')
            state = store.load_locked(conn, key, now)
            # Freeze only notification metadata for this short explicit action,
            # so an unseen notification cannot cross the reviewed baseline.
            conn.execute('LOCK TABLE sentinel_alert_outbox IN SHARE ROW EXCLUSIVE MODE')
            token_key = 'ack:'+hashlib.sha256(raw_token.encode('ascii')).hexdigest()
            if store.has_event(conn, key, token_key):
                store.require(not state['active'] and not state['warnings']
                              and state['head'] == state['reviewed_head'],
                              'a new incident arrived after acknowledgement')
                return _result(conn, key, state, now, subject=view['subject'])
            store.require(type(view['head']) is int and view['head'] == state['head']
                          and not state['active'] and not state['warnings']
                          and state['view_sha256'] == view['subject']
                          and _notices(conn) == state['incidents'],
                          'operator review changed; refresh and review the current state')
            for alert_id in state['incidents']:
                conn.execute("UPDATE sentinel_alert_outbox SET ack_state='ACKNOWLEDGED',"
                    'acknowledged_by=%s,acknowledged_at=%s,acknowledgement=%s,updated_at=%s '
                    "WHERE alert_id=%s AND ack_state='UNACKNOWLEDGED'",
                    (actor, now, 'Reviewed healthy dashboard state; historical payloads and verdicts unchanged.',
                     now, alert_id))
            store.append(conn, key, state, kind='ACKNOWLEDGED', event_key=token_key,
                details={'actor':actor, 'reviewed_head':view['head'], 'alert_ids':state['incidents']}, now=now)
            state.update(reviewed_head=state['head'], reviewed_at=now.isoformat(), incidents=[])
            store.save(conn, key, state, now)
            if snapshot_guard is not None:
                snapshot_guard(conn, panel)
            return _result(conn, key, state, now, subject=view['subject'])


recorder = Recorder()
