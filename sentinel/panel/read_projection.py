"""Authenticated finite read receipts, independent of HTTP and producer liveness."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os

from sentinel import receipt_authentication
from sentinel.panel import authority_reader as financial, model, observer_codec
from sentinel.panel import operational_schema as schema

SCHEMA = 'sentinel.operational-verification/1'
SCOPES = frozenset({'SHADOW', 'PAPER'})
SHADOW_KEYS = frozenset({'shadow_verification','shadow_nav','shadow_return','exposure','book','terminals'})
PAPER_KEYS = frozenset({'paper_reconciliation'})
# Only facts read by independent financial verification belong here. Public
# browser/VAPID settings, poll rates and role-specific process options do not.
SUBJECT_ENV = frozenset({
    'SENTINEL_GIT_COMMIT','SENTINEL_RUNTIME_IMAGE_DIGEST','SENTINEL_IMAGE_SOURCE_REVISION',
    'SENTINEL_TEST_IMAGE_DIGEST','SENTINEL_REVIEWED_DEPLOYMENT_MODE',
    'SENTINEL_SHADOW_OBSERVATION_ID','SENTINEL_SHADOW_STARTING_CASH',
    'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256','SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256',
    'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256','SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256',
    'SENTINEL_LOCAL_PAPER_MODE','SENTINEL_LOCAL_PAPER_ACCOUNT_ID',
    'SENTINEL_AUTHORIZED_RUNTIME','SENTINEL_RUNTIME_BACKUP_AUTHORITY',
    'SENTINEL_RECOVERED_ORDER_AUTHORITY','SENTINEL_PAPER_BUY_POLICY',
    'SENTINEL_PAPER_BUY_CAP_BPS','SENTINEL_PAPER_DEBUG_WINDOW',
    'SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY',
})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def subject(conn, database_url, scope):
    """Constant-size current key, only after the exact invalidation contract."""
    schema.require_schema(conn)
    return _subject(conn,database_url,scope)


def _subject_facts(conn):
    """Common facts reused only inside this caller's coherent read snapshot."""
    from sentinel import operational_ddl_epoch, operational_schema
    physical=conn.execute('SELECT system_identifier::text,current_database() FROM pg_control_system()').fetchone()
    installation=operational_schema.installation(conn,required=False)
    return (physical,installation,operational_ddl_epoch.current(conn),
            {key: os.environ.get(key, '') for key in sorted(SUBJECT_ENV)})


def _subject(conn, database_url, scope, *, facts=None):
    if scope not in SCOPES:
        raise ValueError('unknown operational verification scope')
    row = conn.execute(f'SELECT incarnation::text,revision,xmin::text FROM {schema.REVISION} WHERE scope=%s',
                       (scope,)).fetchone()
    if row is None:
        raise ValueError('verification invalidation state unavailable')
    return _subject_for_revision(conn,database_url,scope,row,facts=facts)


def _subject_for_revision(conn, database_url, scope, row, *, facts=None):
    """Bind a supplied revision to this transaction's current physical facts."""
    if scope not in SCOPES:
        raise ValueError('unknown operational verification scope')
    if row is None:
        raise ValueError('verification invalidation state unavailable')
    physical,installation,epoch,environment = facts if facts is not None else _subject_facts(conn)
    if scope == 'SHADOW':
        # Plan/rollout are projected fresh by the consumer. Include every
        # non-PAPER cursor, including unknown namespaces, without decoding state.
        return _digest([SCHEMA, 'SHADOW_CONTENT_AND_FRESH_EXECUTION_V1', database_url,
            row[0], list(physical), _shadow_inventory(conn),
            installation['installation_id'] if installation is not None else None,
            epoch, environment])
    if scope == 'PAPER':
        # This compatibility scope contains account evidence. URL changes must
        # invalidate it without invalidating broker-independent SHADOW facts.
        from sentinel.trading_environment import TradingEndpoint
        raw_url = os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
        try:
            selected_url = TradingEndpoint.parse(raw_url).base_url
        except ValueError:
            selected_url = 'INVALID'
        environment = {**environment, 'ALPACA_BASE_URL': selected_url}
    return _digest([SCHEMA, database_url, scope, list(row),list(physical),
                    installation['installation_id'] if installation is not None else None,
                    epoch,environment])


def _shadow_inventory(conn):
    from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES
    relation = conn.execute("SELECT 'sentinel_processed_sessions'::regclass::oid::text,"
        "pg_relation_filenode('sentinel_processed_sessions')::text,"
        "'sentinel_corpus_publications'::regclass::oid::text,"
        "pg_relation_filenode('sentinel_corpus_publications')::text,"
        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)::bigint").fetchone()
    cursors = conn.execute('SELECT cursor_name,session::text,tableoid::text,xmin::text,ctid::text '
        'FROM sentinel_processed_sessions WHERE cursor_name<>ALL(%s) AND NOT (cursor_name LIKE ANY(%s)) '
        'ORDER BY cursor_name LIMIT 10001',
        (list(PAPER_CURSOR_NAMES), [prefix+'%' for prefix in PAPER_CURSOR_PREFIXES])).fetchall()
    publications = conn.execute('SELECT version,tableoid::text,xmin::text,ctid::text '
        'FROM sentinel_corpus_publications ORDER BY version LIMIT 10001').fetchall()
    if len(cursors) > 10000 or len(publications) > 10000:
        raise ValueError('shadow content inventory exceeds bound')
    return [relation, cursors, publications]


def subject_for(database_url, include_paper):
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return subject(conn, database_url, 'PAPER' if include_paper else 'SHADOW')
    finally:
        conn.rollback(); conn.close()


def _json_row(row):
    raw = observer_codec.pack([row], [], observed_at=datetime.now(timezone.utc))['rows'][0]
    for key in ('as_of', 'valid_until'):
        if raw.get(key) is not None:
            raw[key] = raw[key].isoformat()
    if raw.get('freshness') is not None:
        raw['freshness'] = raw['freshness'].total_seconds()
    if raw.get('recovery') is not None:
        for key in ('next_attempt_at','deadline'):
            if raw['recovery'].get(key) is not None:
                raw['recovery'][key] = raw['recovery'][key].isoformat()
    return raw


def _decode_row(value):
    raw = dict(value)
    for key in ('as_of','valid_until'):
        if raw.get(key) is not None:
            raw[key] = datetime.fromisoformat(raw[key])
    if raw.get('freshness') is not None:
        if type(raw['freshness']) not in {int,float} or not 0 <= raw['freshness'] <= financial.FRESH_SECONDS:
            raise ValueError('verification row freshness malformed')
        raw['freshness'] = timedelta(seconds=raw['freshness'])
    if raw.get('recovery') is not None:
        raw['recovery'] = dict(raw['recovery'])
        for key in ('next_attempt_at','deadline'):
            if raw['recovery'].get(key) is not None:
                raw['recovery'][key] = datetime.fromisoformat(raw['recovery'][key])
    return observer_codec.row_from_observation(raw)


def make(scope, current_subject, rows, errors, *, observed_at, valid_until=None):
    expiry = valid_until or observed_at+timedelta(seconds=financial.FRESH_SECONDS)
    value = {'schema':SCHEMA,'scope':scope,'subject_sha256':current_subject,
             'observed_at':observed_at.isoformat(),'valid_until':expiry.isoformat(),
             'rows':[_json_row(row) for row in rows],'errors':list(errors)}
    if len(json.dumps(value, allow_nan=False).encode()) > observer_codec.MAX_BYTES:
        raise ValueError('verification receipt exceeds bound')
    signature = receipt_authentication.sign(value)
    # Same shape and original-clock checks apply before publishing and reading.
    decode(value, signature, current_subject=current_subject, scope=scope, now=observed_at)
    return value, signature


def decode(value, signature, *, current_subject, scope, now):
    if (not isinstance(value,dict) or set(value) != {
            'schema','scope','subject_sha256','observed_at','valid_until','rows','errors'}
            or value['schema'] != SCHEMA or value['scope'] != scope or scope not in SCOPES
            or value['subject_sha256'] != current_subject or not isinstance(signature,str)
            or len(json.dumps(value, allow_nan=False).encode()) > observer_codec.MAX_BYTES
            or not hmac.compare_digest(signature, receipt_authentication.sign(value))):
        raise ValueError('verification receipt identity or authentication refused')
    observed = datetime.fromisoformat(value['observed_at'])
    expiry = datetime.fromisoformat(value['valid_until'])
    if (observed.utcoffset() != timedelta(0) or expiry.utcoffset() != timedelta(0)
            or not observed <= now <= expiry
            or not timedelta(0) < expiry-observed <= timedelta(seconds=financial.FRESH_SECONDS)):
        raise ValueError('verification receipt expired or malformed')
    envelope = {'rows':value['rows'],'errors':value['errors'],'observed_at':observed}
    observer_codec.validate_envelope(envelope, PAPER_KEYS if scope == 'PAPER' else SHADOW_KEYS)
    rows = [_decode_row(row) for row in value['rows']]
    if any(row.is_future(observed) for row in rows):
        raise ValueError('verification receipt fact is future dated')
    return rows, {}, [], list(value['errors'])


def publish(conn, *, owner_id, value, signature):
    """Only the still-live finite owner can replace a scoped result."""
    row = conn.execute(f'UPDATE {schema.OWNER} SET expires_at=clock_timestamp()+INTERVAL \'610 seconds\' '
        'WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp() RETURNING owner_id', (owner_id,)).fetchone()
    if row is None:
        raise ValueError('verification producer ownership expired')
    conn.execute(f'INSERT INTO {schema.RECEIPTS} '
        '(scope,subject_sha256,observed_at,valid_until,envelope,signature) VALUES (%s,%s,%s,%s,%s::jsonb,%s) '
        'ON CONFLICT (scope) DO UPDATE SET subject_sha256=EXCLUDED.subject_sha256,observed_at=EXCLUDED.observed_at,'
        'valid_until=EXCLUDED.valid_until,envelope=EXCLUDED.envelope,signature=EXCLUDED.signature',
        (value['scope'],value['subject_sha256'],value['observed_at'],value['valid_until'],json.dumps(value),signature))


def changed_subject_wait(conn, row, *, scope, now):
    """A changed input is checking, never a renewal of its old financial proof."""
    rows, _, _, errors = decode(row[3],row[4],current_subject=row[0],scope=scope,now=now)
    failed_paper = (scope == 'PAPER' and not errors and len(rows) == 1
                    and rows[0].key == 'paper_reconciliation'
                    and rows[0].status == model.FAIL)
    if not failed_paper and (errors or any(item.status in {model.FAIL,model.UNKNOWN}
                    or item.paper_alignment=='PRIOR_CYCLE_FAILED' for item in rows)):
        return None
    owner = conn.execute(f'SELECT expires_at FROM {schema.OWNER} WHERE id=1').fetchone()
    if owner is None:
        return None
    heartbeat = owner[0]-timedelta(seconds=610)
    if not now-timedelta(seconds=45) <= heartbeat <= now+timedelta(seconds=5):
        return None
    if failed_paper:
        failed = replace(rows[0], value='LAST CHECK FAILED · RECHECKING',
            status=model.FAIL,
            detail=('LAST KNOWN FAILURE · '+rows[0].detail
                    +'; inputs changed; waiting for the current bounded check'),
            as_of=rows[0].as_of or row[1], required_current=True,
            valid_until=min(row[2],rows[0].valid_until or row[2]), recovery=None,
            shadow_book=None,paper_plan=None,paper_account=None,order_outcomes=[],
            trading_run=None,paper_alignment=None)
        return [failed], {}, [], []
    result = financial._unknown(scope=='PAPER',
        'account or verification inputs changed; waiting for the current bounded check',
        rows,checking_until=row[2])
    selected = PAPER_KEYS if scope=='PAPER' else SHADOW_KEYS
    checking = [item for item in result[0] if item.key in selected]
    if scope == 'SHADOW':
        from sentinel.panel.shadow_source_wait import attestation_source
        prior = next(item for item in rows if item.key == 'shadow_verification')
        source = attestation_source(prior, now=now)
        if source is not None:
            boundary = min(prior.valid_until, row[2])
            # Carry only the original bounded progress metadata. The old
            # receipt cannot supply current financial values for this subject.
            checking = [replace(item, as_of=prior.as_of, valid_until=boundary,
                source_publication_version=source[0], source_session=source[1],
                recovery=replace(item.recovery, deadline=boundary))
                if item.key == 'shadow_verification' else item for item in checking]
    return checking, {}, [], result[3]


def _selected_scopes(include_paper, only_scope):
    if (only_scope is not None and (not isinstance(only_scope, str) or only_scope not in SCOPES
                                   or only_scope == 'PAPER' and not include_paper)):
        raise ValueError('unknown or contradictory verification receipt scope')
    return ((only_scope,) if only_scope is not None else
            ('SHADOW', 'PAPER') if include_paper else ('SHADOW',))


def read(database_url, *, include_paper=True, now=None, only_scope=None):
    """Consume bounded receipts in one owned read-only transaction."""
    _selected_scopes(include_paper,only_scope)
    from sentinel.feed import store
    instant = now or datetime.now(timezone.utc)
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return read_owned(conn,database_url,include_paper=include_paper,
                          now=instant,only_scope=only_scope)
    finally:
        conn.rollback(); conn.close()


def read_owned(conn, database_url, *, include_paper=True, now=None, only_scope=None, facts=None):
    """Read through the caller's snapshot without owning its transaction.

    Optional facts are invocation-local `_subject_facts` from this same
    transaction. No connection, observer, commit, rollback or isolation change.
    """
    scopes=_selected_scopes(include_paper,only_scope)
    instant = now or datetime.now(timezone.utc)
    schema.require_schema(conn)
    facts_error = None
    if facts is None:
        try:
            facts=_subject_facts(conn)
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            facts_error=exc
    results = []
    for scope in scopes:
        key = row = None
        try:
            if facts_error is not None:
                raise facts_error
            key = _subject(conn, database_url, scope, facts=facts)
            row = conn.execute(f'SELECT subject_sha256,observed_at,valid_until,envelope,signature FROM {schema.RECEIPTS} WHERE scope=%s', (scope,)).fetchone()
            if (row is None or row[1].isoformat() != row[3].get('observed_at')
                    or row[2].isoformat() != row[3].get('valid_until')):
                raise ValueError('current verification receipt unavailable')
            if row[0] != key:
                waiting = changed_subject_wait(conn,row,scope=scope,now=instant)
                if waiting is not None:
                    results.append(waiting)
                    continue
                raise ValueError('current verification receipt unavailable')
            result = decode(row[3], row[4], current_subject=key, scope=scope, now=instant)
            if scope == 'SHADOW':
                from sentinel.panel.shadow_execution_projection import project
                result = (project(conn, result[0], observed_at=row[1], valid_until=row[2], now=instant),
                          result[1], result[2], result[3])
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            retained = None
            if row is not None and row[0] == key:
                try:
                    retained = decode(row[3],row[4],current_subject=key,scope=scope,
                        now=datetime.fromisoformat(row[3]['observed_at']))[0]
                except (ValueError,TypeError,KeyError,OverflowError):
                    pass
            result = financial._unknown(scope == 'PAPER', 'durable '+scope.lower()+' verification unavailable: '+type(exc).__name__,retained)
            result = ([r for r in result[0] if (r.key == 'paper_reconciliation') == (scope == 'PAPER')], {}, [], result[3])
        results.append(result)
    rows = {row.key:row for result in results for row in result[0]}
    order = ('shadow_verification','shadow_nav','shadow_return','paper_reconciliation','exposure','book','terminals')
    return [rows[key] for key in order if key in rows], {}, [], [error for result in results for error in result[3]]
