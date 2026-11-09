"""Bounded display cause witnesses; never financial verification authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import re
import uuid

from sentinel.panel import model, read_projection, review_store

SCHEMA = 'sentinel.dashboard-display-dependencies/1'
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
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'native', 'receipts', 'paper_revision', 'account_table', 'account_anchor'}
            or value['schema'] != SCHEMA
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


def combined_subjects(basis):
    validate_basis(basis)
    return {scope: hashlib.sha256(review_store.canonical([
        basis['native'][scope], basis['receipts'][scope]])).hexdigest()
        for scope in ('SHADOW', 'PAPER')}


def capture(conn, database_url, *, facts=None):
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
    table = conn.execute("SELECT 'sentinel_broker_account_evidence'::regclass::oid::text,"
        "pg_relation_filenode('sentinel_broker_account_evidence')::text").fetchone()
    anchor = conn.execute('SELECT seq::text,xmin::text,ctid::text '
        'FROM sentinel_broker_account_evidence ORDER BY observed_at DESC,seq DESC LIMIT 1').fetchone()
    maximum = conn.execute('SELECT seq::text FROM sentinel_broker_account_evidence ORDER BY seq DESC LIMIT 1').fetchone()
    basis = dict(schema=SCHEMA, native=native,
        receipts={scope: receipts.get(scope) for scope in ('SHADOW', 'PAPER')},
        paper_revision=revisions['PAPER'], account_table=list(table),
        account_anchor=list(anchor) if anchor is not None and maximum == (anchor[0],) else None)
    validate_basis(basis)
    return basis


def valuation_only_advance(conn, database_url, before, after, *, facts=None):
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
    appended = conn.execute('SELECT seq::text,xmin::text,ctid::text '
        'FROM sentinel_broker_account_evidence WHERE seq>%s ORDER BY seq LIMIT 2',
        (int(anchor[0]),)).fetchall()
    if appended != [tuple(latest)]:
        return False
    # The old anchor must still be exactly the signed physical row. The second
    # predicate is the installed trigger's skip predicate, evaluated by PostgreSQL.
    proof = conn.execute("SELECT old.xmin::text,old.ctid::text,"
        "NOT (new.observed_at>=old.observed_at "
        "AND new.observed_at-old.observed_at<=interval '10 minutes' "
        "AND (new.observed_at AT TIME ZONE 'America/New_York')::date="
        "(old.observed_at AT TIME ZONE 'America/New_York')::date "
        "AND (to_jsonb(new)-'seq'-'observed_at') IS NOT DISTINCT FROM "
        "(to_jsonb(old)-'seq'-'observed_at')),"
        "(to_jsonb(new)-'seq'-'observed_at'-'equity') IS NOT DISTINCT FROM "
        "(to_jsonb(old)-'seq'-'observed_at'-'equity'),"
        "new.observed_at>=old.observed_at "
        "FROM sentinel_broker_account_evidence old,sentinel_broker_account_evidence new "
        "WHERE old.seq=%s AND new.seq=%s", (int(anchor[0]), int(latest[0]))).fetchone()
    return (proof is not None and tuple(proof[:2]) == tuple(anchor[1:])
            and proof[2:] == (True, True, True))


def native_reuse(conn, database_url, before, after, *, facts=None):
    """Independent display permission; strict financial subjects remain untouched."""
    validate_basis(before); validate_basis(after)
    if not before or not after:
        return False
    if before['native']['SHADOW'] != after['native']['SHADOW']:
        return False
    return (before['native']['PAPER'] == after['native']['PAPER']
            or valuation_only_advance(conn, database_url, before, after, facts=facts))


def current_account_negative(conn, panel, *, now):
    """Consume a recorded negative only; no provider or reservation is invented."""
    from sentinel.panel import sources, overview_data
    try:
        account = sources._latest_account_evidence(conn)
        bound = sources._bound_account_id(conn)
        row = model.alpaca_account_row(available=account is not None,
            expected_account_id=bound, **(account or {}))
        overview = overview_data.account_overview(account, expected_account_id=bound)
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
                    expected_account_id=bound, **{**account, 'buying_power':cash})
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
