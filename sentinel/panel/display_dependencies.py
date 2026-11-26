"""Bounded display cause witnesses; never financial verification authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import re
import uuid

from sentinel.panel import model, read_projection, review_store

SCHEMA = 'sentinel.dashboard-display-dependencies/2'
_LEGACY = 'sentinel.dashboard-display-dependencies/1'
_DIGEST = re.compile('[a-f0-9]{64}')
_VERSION = re.compile(r'\d+')
_TID = re.compile(r'\(\d+,\d+\)')


def _version(value):
    return (isinstance(value, list) and len(value) == 3
            and isinstance(value[0], str) and isinstance(value[1], str)
            and isinstance(value[2], str) and _VERSION.fullmatch(value[1])
            and _TID.fullmatch(value[2]))


def validate_basis(value):
    """Closed producer metadata; an empty basis retains legacy conservative reads."""
    if value == {}:
        return
    fields = {'schema', 'native', 'receipts', 'paper_revision', 'account_table', 'account_anchor'}
    if isinstance(value, dict) and value.get('schema') == SCHEMA:
        fields.update(('observation_anchor', 'automation_lease'))
    if (not isinstance(value, dict) or set(value) != fields
            or value['schema'] not in (SCHEMA, _LEGACY)
            or not isinstance(value['native'], dict) or set(value['native']) != {'SHADOW', 'PAPER'}
            or not all(isinstance(v, str) and _DIGEST.fullmatch(v) for v in value['native'].values())
            or not isinstance(value['receipts'], dict) or set(value['receipts']) != {'SHADOW', 'PAPER'}):
        raise ValueError('display dependency basis malformed')
    for token in value['receipts'].values():
        if token is not None and (not _version(token) or not _DIGEST.fullmatch(token[0])):
            raise ValueError('display receipt token malformed')
    revision = value['paper_revision']
    if (not isinstance(revision, list) or len(revision) != 3
            or not isinstance(revision[0], str) or str(uuid.UUID(revision[0])) != revision[0]
            or type(revision[1]) is not int or revision[1] < 0
            or not isinstance(revision[2], str) or not _VERSION.fullmatch(revision[2])):
        raise ValueError('display revision malformed')
    table = value['account_table']
    if (not isinstance(table, list) or len(table) != 2
            or not all(isinstance(v, str) and _VERSION.fullmatch(v) for v in table)):
        raise ValueError('display account table malformed')
    anchor = value['account_anchor']
    if anchor is not None and (not _version(anchor) or not _VERSION.fullmatch(anchor[0])):
        raise ValueError('display account anchor malformed')
    observation = value.get('observation_anchor')
    if observation is not None and (not isinstance(observation, list) or len(observation) != 5
            or not _version(observation[:3]) or not _VERSION.fullmatch(observation[0])
            or not all(isinstance(v, str) and _VERSION.fullmatch(v) for v in observation[3:])):
        raise ValueError('display observation anchor malformed')
    lease = value.get('automation_lease')
    if lease is not None and (not isinstance(lease, list) or len(lease) != 4
            or not isinstance(lease[0], str) or not lease[0]
            or any(type(v) is not int or v < 1 for v in lease[1:3])
            or not isinstance(lease[3], str) or datetime.fromisoformat(lease[3]).utcoffset() != timedelta(0)):
        raise ValueError('display automation lease malformed')


def automation_lease(conn):
    """Active native automation term in the caller's snapshot, independent of the verifier."""
    row = conn.execute('SELECT l.holder_id,l.fence_token,l.control_generation,l.expires_at '
        'FROM sentinel_automation_lease l JOIN sentinel_automation_control c ON c.id=l.id '
        'WHERE l.id=1 AND c.enabled AND NOT c.kill_switch_engaged AND l.control_generation=c.generation '
        'AND l.holder_id IS NOT NULL AND l.expires_at>clock_timestamp()').fetchone()
    return [*row[:3],row[3].isoformat()] if row else None


def dashboard_subject(scope, native, receipt, lease, *, legacy=False):
    values = [native, receipt]
    if scope == 'PAPER' and not legacy:
        values.append(lease[:3] if lease else None)
    return hashlib.sha256(review_store.canonical(values)).hexdigest()


def combined_subjects(basis):
    validate_basis(basis)
    return {scope: dashboard_subject(scope, basis['native'][scope], basis['receipts'][scope],
        basis.get('automation_lease'), legacy=basis['schema'] == _LEGACY)
        for scope in ('SHADOW', 'PAPER')}


def capture(conn, database_url, *, facts=None, dashboard=True):
    """Constant-size indexed coordinates, owned by the caller's coherent snapshot."""
    read_projection.schema.require_schema(conn)
    facts = read_projection._subject_facts(conn) if facts is None else facts
    revisions = {r[0]: list(r[1:]) for r in conn.execute(
        'SELECT scope,incarnation::text,revision,xmin::text '
        'FROM sentinel_operational_read_revisions ORDER BY scope').fetchall()}
    native = {scope: read_projection._subject_for_revision(conn, database_url, scope,
        revisions[scope], facts=facts) for scope in ('SHADOW', 'PAPER')}
    receipts = {r[0]: list(r[1:]) for r in conn.execute(
        "SELECT scope,signature,xmin::text,ctid::text FROM sentinel_operational_verification_receipts "
        "WHERE scope IN ('SHADOW','PAPER') ORDER BY scope").fetchall()}
    coordinates = ("SELECT 'sentinel_broker_account_evidence'::regclass::oid::text,"
                   "pg_relation_filenode('sentinel_broker_account_evidence')::text")
    if dashboard:
        coordinates += (", (SELECT ARRAY[o.seq::text,o.xmin::text,o.ctid::text,o.tableoid::text,"
                        "pg_relation_filenode(o.tableoid)::text] FROM sentinel_observations o ORDER BY o.seq DESC LIMIT 1)")
    table = conn.execute(coordinates).fetchone()
    anchor = conn.execute('SELECT a.seq::text,a.xmin::text,a.ctid::text '
        'FROM sentinel_broker_account_evidence a ORDER BY a.observed_at DESC,a.seq DESC LIMIT 1').fetchone()
    maximum = conn.execute('SELECT a.seq::text FROM sentinel_broker_account_evidence a ORDER BY a.seq DESC LIMIT 1').fetchone()
    basis = dict(schema=_LEGACY, native=native,
        receipts={scope: receipts.get(scope) for scope in ('SHADOW', 'PAPER')},
        paper_revision=revisions['PAPER'], account_table=list(table[:2]),
        account_anchor=list(anchor) if anchor is not None and maximum == (anchor[0],) else None)
    if dashboard:
        basis.update(schema=SCHEMA, observation_anchor=table[2], automation_lease=automation_lease(conn))
    validate_basis(basis)
    return basis


def valuation_basis(basis):
    """Keep dashboard liveness and broker delivery coordinates out of financial receipts."""
    return {**{key: value for key, value in basis.items() if key not in {'observation_anchor','automation_lease'}},
            'schema': _LEGACY}


def valuation_only_advance(conn, database_url, before, after, *, facts=None,
                           completed_now=None):
    """Prove one necessarily-bumping valuation append exhausts the guarded +1."""
    validate_basis(before); validate_basis(after)
    if not before or not after:
        return False
    prior, current = before['paper_revision'], after['paper_revision']
    anchor, latest = before['account_anchor'], after['account_anchor']
    if (anchor is None or latest is None or before['account_table'] != after['account_table']
            or prior[0] != current[0] or current[1] != prior[1] + 1
            or int(latest[0]) <= int(anchor[0]) or latest[1] != current[2]):
        return False
    if read_projection._subject_for_revision(conn, database_url, 'PAPER', prior,
            facts=facts) != before['native']['PAPER']:
        return False
    appended = conn.execute('SELECT a.seq::text,a.xmin::text,a.ctid::text '
        'FROM sentinel_broker_account_evidence a WHERE a.seq>%s ORDER BY a.seq LIMIT 2',
        (int(anchor[0]),)).fetchall()
    if appended != [tuple(latest)]:
        return False
    # The old anchor must still be exactly the signed physical row. The second
    # predicate is the installed trigger's skip predicate, evaluated by PostgreSQL.
    proof = conn.execute("SELECT old.xmin::text,old.ctid::text,new.xmin::text,new.ctid::text,"
        "NOT (new.observed_at>=old.observed_at "
        "AND new.observed_at-old.observed_at<=interval '10 minutes' "
        "AND (new.observed_at AT TIME ZONE 'America/New_York')::date="
        "(old.observed_at AT TIME ZONE 'America/New_York')::date "
        "AND (to_jsonb(new)-'seq'-'observed_at') IS NOT DISTINCT FROM "
        "(to_jsonb(old)-'seq'-'observed_at')),"
        "(to_jsonb(new)-'seq'-'observed_at'-'equity') IS NOT DISTINCT FROM "
        "(to_jsonb(old)-'seq'-'observed_at'-'equity'),"
        "new.observed_at>=old.observed_at,new.observed_at,"
        "new.observed_at-old.observed_at<=interval '10 minutes' "
        "AND (new.observed_at AT TIME ZONE 'America/New_York')::date="
        "(old.observed_at AT TIME ZONE 'America/New_York')::date,"
        "CASE WHEN old.equity NOT IN ('NaN'::numeric,'Infinity'::numeric) "
        "AND new.equity NOT IN ('NaN'::numeric,'Infinity'::numeric) "
        "THEN old.equity>0 AND new.equity>0 ELSE false END "
        "FROM sentinel_broker_account_evidence old,sentinel_broker_account_evidence new "
        "WHERE old.seq=%s AND new.seq=%s", (int(anchor[0]), int(latest[0]))).fetchone()
    if completed_now is not None and (proof is None or proof[8:] != (True, True)
                                      or proof[7] > completed_now):
        return False
    return (proof is not None and tuple(proof[:2]) == tuple(anchor[1:])
            and tuple(proof[2:4]) == tuple(latest[1:])
            and proof[4:7] == (True, True, True))


def completed_account_row(conn, panel, *, now):
    """Overlay the current valuation when an independently proved run completed."""
    history, prior = panel.row('paper_reconciliation'), panel.row('alpaca_account')
    if (history is None or history.paper_alignment != 'COMPLETED_WITH_HISTORY'
            or history.effective_status(now) != model.WARN
            or prior is None or prior.status != model.OK or prior.recovery is not None):
        return None
    from sentinel.panel import sources, overview_data
    try:
        account = sources._latest_account_evidence(conn)
        bound = sources._bound_account_id(conn)
        broker = sources._selected_trading_endpoint().broker_namespace
        row = model.alpaca_account_row(available=account is not None,
                                      expected_account_id=bound, expected_broker=broker, **(account or {}))
        if (row.effective_status(now) != model.OK or row.as_of is None or row.as_of > now
                or prior.as_of is None or row.as_of < prior.as_of):
            return None
        # This overlay refreshes only native valuation. Preserve the separate
        # posting observation and its original reconciliation time.
        overview = overview_data.account_overview(account, expected_account_id=bound,
            expected_broker=broker,
            cash_posting=prior.paper_account.cash_posting if prior.paper_account else None)
        return replace(row, paper_account=overview) if overview is not None else None
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError):
        return None


def native_reuse(conn, database_url, before, after, *, facts=None):
    """Independent display permission; strict financial subjects remain untouched."""
    validate_basis(before); validate_basis(after)
    if not same_automation_term(before, after):
        return False
    if before['native']['SHADOW'] != after['native']['SHADOW']:
        return False
    return (before['native']['PAPER'] == after['native']['PAPER']
            or valuation_only_advance(conn, database_url, before, after, facts=facts))


def same_automation_term(before, after):
    return ('automation_lease' in before and 'automation_lease' in after and
            (before['automation_lease'] or [])[:3] == (after['automation_lease'] or [])[:3])


def close_cycle_advance(conn, database_url, before, after, panel, *, facts, now):
    """Account for both PAPER revisions of one planless close-cycle transition."""
    from sentinel.feed import calendar

    prior, current = before['paper_revision'], after['paper_revision']
    term = after.get('automation_lease')
    if (not panel.local_paper_mode or not term or not same_automation_term(before, after)
            or before['native']['SHADOW'] != after['native']['SHADOW']
            or before['account_table'] != after['account_table']
            or before['account_anchor'] != after['account_anchor']
            or before['observation_anchor'] != after['observation_anchor']
            or prior[0] != current[0] or current[1] != prior[1] + 2
            or read_projection._subject_for_revision(conn, database_url, 'PAPER', prior, facts=facts)
                != before['native']['PAPER']):
        return False
    cycle, plan = panel.row('automation_cycle'), panel.row('paper_plan')
    stage = cycle.operational_fact if cycle is not None else None
    stages = ('DISCOVERED', 'REFRESHING_DATA', 'RETRY_WAIT', 'PREPARING')
    generated = panel.observation_generated_at
    if (stage is None or stage.kind != 'AUTOMATION_CYCLE' or stage.state not in stages
            or cycle.status != model.WARN or cycle.as_of is None or generated is None
            or plan is None or plan.status != model.PENDING or plan.paper_plan is not None):
        return False
    session = calendar.latest_closed_session(now)
    closed = calendar.session_window(session)[1]
    opened = calendar.session_window(calendar.next_session(session))[0]
    if not closed <= cycle.as_of <= generated < now < opened:
        return False
    # The projected cycle update and its event insert necessarily bump once
    # each. Their common transaction must exhaust the whole guarded advance.
    row = conn.execute("""
        WITH event AS (
            SELECT cycle_id,from_state,to_state,control_generation,fence_token,at,xmin
            FROM sentinel_automation_cycle_events ORDER BY seq DESC LIMIT 1
        )
        SELECT 1 FROM event e JOIN sentinel_automation_cycles c USING(cycle_id)
        WHERE c.xmin::text=%s AND e.xmin=c.xmin AND e.from_state=%s
          AND e.to_state=c.state AND e.to_state<>e.from_state AND e.to_state=ANY(%s)
          AND c.control_generation=e.control_generation AND e.control_generation=%s
          AND c.last_fence_token=e.fence_token AND e.fence_token=%s
          AND c.decision_session=%s AND c.execution_open_at=%s
          AND c.plan_id IS NULL AND NOT c.historical_state_only
          AND %s<c.updated_at AND c.updated_at<=e.at AND e.at<=%s
          AND (c.state<>'RETRY_WAIT' OR c.failure_code IN (
              'PreflightPublicationPinUnavailable','ClosingDataPending'))
        """, (current[2], stage.state, list(stages), term[2], term[1], session, opened,
              generated, now)).fetchone()
    return row == (1,)


def clean_observation_advance(conn, database_url, before, after, *, facts, now):
    """A clean broker observation accounts for the entire native revision advance."""
    from sentinel.panel.sources import _ACTIVE_COMMAND_STATES

    old, new = before.get('observation_anchor'), after.get('observation_anchor')
    prior, current = before['paper_revision'], after['paper_revision']
    if (not same_automation_term(before, after) or old is None or new is None
            or old[3:] != new[3:] or int(new[0]) <= int(old[0])
            or before['native']['SHADOW'] != after['native']['SHADOW']
            or before['account_anchor'] is None or before['account_anchor'] != after['account_anchor']
            or prior[0] != current[0] or current[1] - prior[1] not in (2, 3) or new[1] != current[2]
            or read_projection._subject_for_revision(conn, database_url, 'PAPER', prior, facts=facts)
                != before['native']['PAPER']):
        return False
    # The immutable three-row change suffix names the append transaction.
    # The observation and its cursor necessarily bump PAPER independently.
    # A different final tuple xid proves an additional update. A payload edit
    # would displace the insert from this exact suffix. Runtime finalization
    # skips that audit trigger and still bumps PAPER once.
    latest = conn.execute("""
        WITH changes AS (
            SELECT source,evidence_key,operation,xmin,seq
            FROM sentinel_execution_evidence_changes
            WHERE domain='OBSERVATION' ORDER BY seq DESC LIMIT 3
        )
        SELECT n.seq::text,n.xmin::text,n.ctid::text FROM sentinel_observations n
          JOIN sentinel_observations o ON o.seq=%s AND o.xmin::text=%s AND o.ctid::text=%s
          JOIN sentinel_observation_provenance p ON p.observation_seq=n.seq
          JOIN sentinel_observation_provenance previous ON previous.observation_seq=o.seq
          JOIN sentinel_account_binding b ON b.id=1 AND b.ownership_state='SENTINEL_OWNED'
            AND (b.broker,b.broker_account_id)=(p.broker,p.broker_account_id)
          JOIN sentinel_processed_sessions w ON w.cursor_name='broker-observation:v4:'||n.seq
            AND w.xmin=p.xmin AND w.state->>'canonical_payload_sha256'=p.canonical_payload_sha256
        WHERE n.seq=%s AND (previous.broker,previous.broker_account_id)=(p.broker,p.broker_account_id)
          AND 2+(n.xmin<>p.xmin)::int=%s
          AND ARRAY(SELECT source FROM changes WHERE operation='INSERT' AND xmin=p.xmin
                    AND evidence_key=CASE WHEN source='sentinel_processed_sessions' THEN w.cursor_name
                                          ELSE n.seq::text END ORDER BY seq)=
              ARRAY['sentinel_observations','sentinel_observation_provenance','sentinel_processed_sessions']
          AND p.observed_at=n.observed_at AND previous.observed_at=o.observed_at
          AND o.observed_at<=n.observed_at AND n.observed_at<=%s
          AND o.completeness='COMPLETE' AND n.completeness='COMPLETE'
          AND o.runtime_state='RUNNING' AND n.runtime_state='RUNNING'
          AND o.orders='[]'::jsonb AND n.orders=o.orders AND n.positions=o.positions
          AND (o.terminal_recovery_through IS NULL OR n.terminal_recovery_through>=o.terminal_recovery_through)
          AND p.positions->'positions'=previous.positions->'positions'
          AND p.positions->'exact_evidence'='[]'::jsonb
          AND NOT EXISTS (SELECT 1 FROM sentinel_commands WHERE state=ANY(%s))
          AND NOT EXISTS (SELECT 1 FROM sentinel_observations x WHERE x.seq>o.seq AND x.seq<n.seq)
        """, (int(old[0]), *old[1:3], int(new[0]), current[1]-prior[1], now,
              list(_ACTIVE_COMMAND_STATES))).fetchall()
    return latest == [tuple(new[:3])]


def current_account_negative(conn, panel, *, now):
    """Consume a recorded negative only; no provider or reservation is invented."""
    from sentinel.panel import sources, overview_data
    try:
        account = sources._latest_account_evidence(conn)
        bound = sources._bound_account_id(conn)
        broker = sources._selected_trading_endpoint().broker_namespace
        row = model.alpaca_account_row(available=account is not None,
            expected_account_id=bound, expected_broker=broker, **(account or {}))
        overview = overview_data.account_overview(account, expected_account_id=bound,
            expected_broker=broker)
        effective = row.effective_status(now)
        if row.status == model.OK and overview is None:
            raise ValueError('current account overview unavailable')
        if effective not in {model.FAIL, model.UNKNOWN}:
            return None
        # A cash hold can be legitimate. Without its existing exact proof, a
        # buying-power deficit alone stays partial rather than becoming a false
        # failure. Other typed negatives still dominate immediately.
        if account is not None:
            cash, power = account.get('cash'), account.get('buying_power')
            if (cash is not None and power is not None and cash.is_finite() and power.is_finite()
                    and 0 <= power < cash and cash-power > Decimal('1')):
                without_hold = model.alpaca_account_row(available=True,
                    expected_account_id=bound, expected_broker=broker,
                    **{**account, 'buying_power':cash})
                if without_hold.effective_status(now) == model.OK and overview is not None:
                    return None
        return replace(row, status=effective) if effective != row.status else row
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError):
        return model.Row('alpaca_account', 'Alpaca Account', 'CURRENT EVIDENCE UNREADABLE',
            model.UNKNOWN, 'Recorded account evidence could not be validated.',
            as_of=now, required_current=True)


def overlay(panel, replacements):
    existing = {row.key for row in panel.rows}
    return replace(panel, rows=[*[replacements.get(row.key, row) for row in panel.rows],
        *[row for key,row in replacements.items() if key not in existing]])
