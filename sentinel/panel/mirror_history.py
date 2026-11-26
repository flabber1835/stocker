"""Read-only explanation of the latest checks on historically flagged plans."""
from __future__ import annotations

from contextvars import ContextVar
from datetime import date
import hmac
import os

import psycopg

from sentinel import informational_paper_mirror as mirror, mirror_projection
from sentinel.execution import cash_corrections
from sentinel.feed import calendar
from sentinel.feed.rolling_contract import digest


MAX_PLANS = 8
_MEMO_PURPOSE = 'sentinel.panel-mirror-dividend-count/1'
current_memo = ContextVar('paper_mirror_history_memo', default=None)


class ClassificationMemo:
    """The verifier serializes observers. A torn write fails authentication."""
    def __init__(self):
        from multiprocessing import get_context
        self.slot = get_context('spawn').RawArray('B', 65)

    @staticmethod
    def _signature(subject, count):
        from sentinel.receipt_authentication import sign
        return bytes.fromhex(sign({'purpose': _MEMO_PURPOSE, 'subject': subject, 'count': count}))

    def read(self, subject, maximum):
        raw = bytes(self.slot)
        count = raw[32]
        if raw[:32].hex() != subject or count > maximum:
            return None
        return count if hmac.compare_digest(raw[33:], self._signature(subject, count)) else None

    def store(self, subject, count):
        self.slot[:] = bytes.fromhex(subject) + bytes([count]) + self._signature(subject, count)


def _cash_only(row, record, corrections, proved):
    """Require the exact material commitment and exclude hidden same-identity events."""
    if record is None or calendar.next_session(row['decision_session']) != row['effective_session']:
        return False
    ids, symbols = set(row['security_ids']), set(row['symbols'])

    def relevant(event):
        return event.get('security_id') in ids or event.get('ticker') in symbols

    if any(relevant(event) for kind in ('scalar', 'unsupported', 'unresolved') for event in record[kind]):
        return False
    material = {}
    for marker in corrections:
        if marker['session'] != row['effective_session'] or not relevant(marker):
            continue
        sid = marker['security_id']
        if not sid or sid in material or digest(marker) not in proved:
            return False
        material[sid] = 'UNSUPPORTED:historycorrection:' + marker['source_row_id']
    return bool(material) and digest(material) == row['material_sha256']


def _classify(conn, publication, matching):
    dates = sorted({date.fromisoformat(row['effective_session']) for row in matching})
    originals = {str(day): payload for day, payload in conn.execute(
        'SELECT session,payload FROM sentinel_action_history WHERE session=ANY(%s)', (dates,))}
    current = conn.execute('SELECT payload FROM sentinel_action_coverage WHERE publication_version=%s',
                           (publication.version,)).fetchone()
    if current is None or not originals:
        return None
    # load validates the held coverage, old records, origin links and receipt chain.
    # Supplying the selected sessions avoids re-reading the full history for each plan.
    corrections = current[0]['corrections']
    selected = {(e['session'], e['security_id'], e['ticker']) for e in corrections for row in matching
                if e['session'] == row['effective_session']
                and (e['security_id'] in row['security_ids'] or e['ticker'] in row['symbols'])}
    view = cash_corrections.load(conn, publication, covered=current[0], records=originals, selected_markers=selected,
        start=min(date.fromisoformat(row['decision_session']) for row in matching), end=dates[-1])
    proved = {item.proof.marker_sha256 for item in view.additions}
    return sum(_cash_only(row, originals.get(row['effective_session']), corrections, proved) for row in matching)


def _history_row_versions(conn, plan_ids):
    db = conn.execute("SELECT current_setting('transaction_isolation'),"
        "current_setting('transaction_read_only'),current_setting('session_replication_role'),"
        "pg_postmaster_start_time()::text,"
        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)::bigint").fetchone()
    if db[:3] != ('repeatable read', 'on', 'origin'):
        return None
    pending = [mirror._pending_cursor(plan_id) for plan_id in plan_ids]
    rows = conn.execute('''
        SELECT p.plan_id,d.tableoid::text,d.xmin::text,d.ctid::text,
               s.tableoid::text,s.xmin::text,s.ctid::text
        FROM unnest(%s::text[],%s::text[]) AS p(plan_id,cursor_name)
        JOIN sentinel_paper_mirror_dependencies d USING(plan_id)
        JOIN sentinel_processed_sessions s USING(cursor_name)
        ORDER BY p.plan_id
        ''', (plan_ids, pending)).fetchall()
    # The authenticated history context already binds the database, physical
    # relation inventory, DDL epoch and exact tracked evidence sequence.
    return (db, rows) if len(rows) == len(plan_ids) else None


def _counts(conn, publication, summary):
    count = summary['historical_mismatch_count']
    flagged = conn.execute(
        "SELECT d.plan_id, EXISTS(SELECT 1 FROM sentinel_commands c WHERE c.plan_id=d.plan_id)"
        " FROM sentinel_paper_mirror_dependencies d WHERE d.payload->>'historical_mismatch'='true'"
        " ORDER BY d.plan_id LIMIT %s", (count + 1,)).fetchall()
    if len(flagged) != count:
        return None
    plan_ids = [plan_id for plan_id, _ in flagged]
    with_commands = sum(has_commands for _, has_commands in flagged)
    memo = current_memo.get()
    context = summary.get('indexed_history_context') if memo is not None else None
    subject = None
    shared = None
    if context:
        shared = [_MEMO_PURPOSE, context, publication.version, publication.evidence,
                  os.environ.get('SENTINEL_GIT_COMMIT'), os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST')]
        versions = _history_row_versions(conn, plan_ids)
        if versions is not None:
            subject = digest([shared, 'row-versions', versions])
            qualified = memo.read(subject, count)
            if qualified is not None:
                return qualified, with_commands
    plans = [mirror_projection._row(conn, plan_id) for plan_id in plan_ids]
    if any(row is None or not row['historical_mismatch'] for row in plans):
        return None
    matching = [row for row in plans if row['checked_publication'] == publication.version
                and row['status'] == mirror.MISMATCH]
    if not matching:
        return None
    if shared is not None and subject is None:
        subject = digest([shared, 'full-rows', plans])
        qualified = memo.read(subject, len(matching))
        if qualified is not None:
            return qualified, with_commands
    qualified = _classify(conn, publication, matching)
    if qualified is None:
        return None
    if subject is not None:
        memo.store(subject, qualified)
    return qualified, with_commands


def detail(conn, publication, summary):
    count = summary['historical_mismatch_count']
    generic = f'{count} historical informational mirror mismatch(es) remain recorded for earlier plans. '
    if (count > MAX_PLANS or summary.get('indexed_history_publication') is None
            or summary['indexed_history_publication'] != publication.version):
        return generic
    try:
        # An optional read can time out. Roll back its savepoint without abandoning
        # the verifier's repeatable-read snapshot or losing the financial verdict.
        with conn.transaction():
            result = _counts(conn, publication, summary)
    except (psycopg.Error, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError):
        return generic
    if result is None:
        return generic
    qualified, with_commands = result
    history = (f'{count} historical plans have retained mirror warnings. '
               f'Late dividend data explains the latest check on {qualified} of {count} plans. '
               if qualified else generic)
    if qualified < count:
        history += f'Checks without a dividend-only explanation total {count - qualified}. '
    return history + f'The command journal contains entries for {with_commands} of {count} plans. '
