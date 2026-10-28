"""Retained pre-projection monitor fixtures; never imported by production."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore, Event, Lock, Thread

from sentinel.panel import authority_reader as financial
from sentinel.panel.observer_codec import pack
import hashlib, json
from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES

def evidence(database_url, include_paper):
    """Small read-only invalidation key; no heartbeat can renew a proof."""
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        # Specific broker-owned records are never inputs to the immutable book.
        # Every other retained cursor, including unknown namespaces, stays bound.
        facts = [conn.execute(
            "SELECT cursor_name,session,xmin::text,ctid::text FROM sentinel_processed_sessions "
            "WHERE %s OR (cursor_name <> ALL(%s) AND NOT (cursor_name LIKE ANY(%s))) "
            "ORDER BY cursor_name",
            (include_paper, list(PAPER_CURSOR_NAMES),
             [prefix+'%' for prefix in PAPER_CURSOR_PREFIXES])).fetchall()]
        facts.extend(conn.execute(query).fetchall() for query in (
            "SELECT version,xmin::text,ctid::text FROM sentinel_corpus_publications "
            "ORDER BY version DESC LIMIT 1",
            "SELECT md5(to_jsonb(r)::text) FROM sentinel_rollout_state r WHERE id=1",
            "SELECT plan_id,md5(to_jsonb(p)::text) FROM sentinel_execution_plans p "
            "WHERE superseded_by IS NULL ORDER BY plan_id",
        ))
        if include_paper:
            facts.extend(conn.execute(query).fetchall() for query in (
                "SELECT enabled,generation,kill_switch_engaged,certificate_sha256 "
                "FROM sentinel_automation_control WHERE id=1",
                "SELECT md5(to_jsonb(b)::text) FROM sentinel_account_binding b WHERE id=1",
                "SELECT cycle_id,state,plan_id,plan_fingerprint,last_clean_reconciliation_id "
                "FROM sentinel_automation_cycles ORDER BY decision_session DESC,created_at DESC LIMIT 1",
                "SELECT seq FROM sentinel_observations ORDER BY seq DESC LIMIT 1",
                "SELECT state,count(*),max(updated_at) FROM sentinel_commands GROUP BY state ORDER BY state",
                "SELECT md5(to_jsonb(a)::text),md5(c.claims::text),l.status "
                "FROM sentinel_execution_authority_state a LEFT JOIN sentinel_signed_execution_certificates c "
                "ON c.certificate_sha256=a.active_certificate_sha256 LEFT JOIN sentinel_execution_certificate_lifecycle l "
                "ON l.certificate_sha256=a.active_certificate_sha256 WHERE a.id=1",
                "SELECT certificate_sha256 FROM sentinel_execution_certificate_revocations ORDER BY certificate_sha256",
                "SELECT key_id FROM sentinel_execution_key_revocations ORDER BY key_id",
            ))
        return hashlib.sha256(json.dumps(facts, default=str, sort_keys=True).encode()).hexdigest()
    finally:
        conn.rollback()
        conn.close()


POLL_SECONDS = 15
MONITOR_DEADLINE_SECONDS = 60


def shadow_evidence(database_url, include_paper=False):
    # Exposure and unpriced annotations read the current plan. Actual broker
    # observations, orders, control and cycle progress do not affect this proof.
    return evidence(database_url, False)


def _observe_shadow_once(database_url, include_paper, expected_key):
    from sentinel.panel.sources import _dual_authority_rows
    assert include_paper is False
    if financial._key(database_url, False, shadow_evidence(database_url)) != expected_key:
        raise ValueError('shadow evidence changed before observation')
    rows, details, history, errors = _dual_authority_rows(database_url,
        now=datetime.now(timezone.utc), include_paper=False, propagate_corpus_lock=True)
    if details or history:
        raise ValueError('unexpected shadow observer shape')
    value = pack(rows, errors, observed_at=datetime.now(timezone.utc))
    if financial._key(database_url, False, shadow_evidence(database_url)) != expected_key:
        raise ValueError('shadow evidence changed during observation')
    return value


def observe_shadow(database_url, include_paper, expected_key):
    return financial.retry_corpus_lock(lambda: _observe_shadow_once(
        database_url, include_paper, expected_key))


def _observe_paper_once(database_url, include_paper, expected_key):
    from sentinel import informational_paper_mirror
    from sentinel.feed import readers, store
    from sentinel.panel import sources
    assert include_paper is True
    if financial._key(database_url, True, evidence(database_url, True)) != expected_key:
        raise ValueError('paper evidence changed before observation')
    conn = store.connect(database_url, connect_timeout=3,
                         statement_timeout_ms=sources.STATEMENT_TIMEOUT_MS)
    try:
        conn.execute('BEGIN TRANSACTION READ ONLY')
        row = sources._dual_paper_row(conn, informational_paper_mirror=informational_paper_mirror,
                                      publication=readers, feed_store=store)
        value = pack([row], [], observed_at=datetime.now(timezone.utc))
    finally:
        conn.rollback(); conn.close()
    if financial._key(database_url, True, evidence(database_url, True)) != expected_key:
        raise ValueError('paper evidence changed during observation')
    return value


def observe_paper(database_url, include_paper, expected_key):
    return financial.retry_corpus_lock(lambda: _observe_paper_once(
        database_url, include_paper, expected_key))


def paper_unknown(include_paper, detail, retained=None, *, checking_until=None):
    rows, details, history, errors = financial._unknown(True, detail, retained,
                                                      checking_until=checking_until)
    return [row for row in rows if row.key == 'paper_reconciliation'], details, history, errors


class Monitor:
    def __init__(self, *, reader_factory=financial.Reader, interval=POLL_SECONDS):
        self.reader_factory = reader_factory
        self.interval = interval
        self.lock = Lock()
        self.slot = BoundedSemaphore(1)
        self.configuration = None
        self.thread = None
        self.stop_event = None
        self.shadow = self.paper = None
        self.next_check = None
        self.check_started = None
        self.failure = None

    def start(self, database_url, *, include_paper=True):
        configuration = (database_url, include_paper)
        with self.lock:
            if self.configuration == configuration and self.thread is not None and self.thread.is_alive():
                return
        self.stop()
        shadow = self.reader_factory(evidence_reader=shadow_evidence, observer=observe_shadow,
            execution_slot=self.slot, scope_label='retained portfolio verification')
        paper = self.reader_factory(evidence_reader=evidence, observer=observe_paper,
            expected_keys=frozenset({'paper_reconciliation'}), unknown_factory=paper_unknown,
            execution_slot=self.slot, scope_label='paper alignment verification') if include_paper else None
        stop = Event()
        with self.lock:
            self.configuration = configuration
            self.shadow, self.paper = shadow, paper
            self.failure = None
            self.check_started = datetime.now(timezone.utc)
            self.next_check = self.check_started+timedelta(seconds=MONITOR_DEADLINE_SECONDS)
            self.stop_event = stop
            self.thread = Thread(target=self._run, args=(database_url, shadow, paper, stop),
                                 daemon=True, name='sentinel-panel-verification-monitor')
            self.thread.start()

    def _run(self, database_url, shadow, paper, stop):
        while not stop.is_set():
            with self.lock:
                self.check_started = datetime.now(timezone.utc)
                self.next_check = self.check_started+timedelta(seconds=MONITOR_DEADLINE_SECONDS)
            try:
                shadow.read(database_url, include_paper=False)
                if paper is not None:
                    paper.read(database_url, include_paper=True)
                with self.lock:
                    self.failure = None
            except Exception as exc:
                with self.lock:
                    self.failure = type(exc).__name__
            stop.wait(self.interval)

    def read(self, database_url, *, include_paper=True):
        with self.lock:
            if self.configuration != (database_url, include_paper):
                return None
            shadow, paper, deadline, failure = self.shadow, self.paper, self.next_check, self.failure
            started = self.check_started
            alive = self.thread is not None and self.thread.is_alive()
        if not alive or failure is not None:
            return financial._unknown(include_paper,
                'background verification monitor unavailable: '+(failure or 'STOPPED'))
        left = shadow.read(database_url, include_paper=False, allow_start=False,
                           awaiting_until=deadline, awaiting_since=started)
        if paper is None:
            return left
        right = paper.read(database_url, include_paper=True, allow_start=False,
                           awaiting_until=deadline, awaiting_since=started)
        rows = {row.key: row for row in [*left[0], *right[0]]}
        order = ('shadow_verification', 'shadow_nav', 'shadow_return', 'paper_reconciliation',
                 'exposure', 'book', 'terminals')
        return [rows[key] for key in order], {}, [], [*left[3], *right[3]]

    def stop(self):
        with self.lock:
            stop, thread = self.stop_event, self.thread
            self.configuration = None
        if stop is not None:
            stop.set()
        if thread is not None:
            thread.join(timeout=2)
