"""One browser-independent, broker-free owner of separate display proofs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore, Event, Lock, Thread

from sentinel.panel import authority_reader as financial
from sentinel.panel.observer_codec import pack

POLL_SECONDS = 15
MONITOR_DEADLINE_SECONDS = 60


def shadow_evidence(database_url, include_paper=False):
    # Exposure and unpriced annotations read the current plan. Actual broker
    # observations, orders, control and cycle progress do not affect this proof.
    return financial._evidence(database_url, False)


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
    if financial._key(database_url, True, financial._evidence(database_url, True)) != expected_key:
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
    if financial._key(database_url, True, financial._evidence(database_url, True)) != expected_key:
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
        paper = self.reader_factory(observer=observe_paper,
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


monitor = Monitor()
