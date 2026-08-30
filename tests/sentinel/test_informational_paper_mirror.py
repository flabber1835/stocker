from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import informational_paper_mirror as mirror, paper
import sentinel.paper.reconciliation_evidence as paper_reconciliation_evidence
from sentinel.execution.contract import (
    BrokerInstrument, BrokerObservation, BrokerOrder, Side)
from sentinel.execution.reconcile import CorporateActionEvent, CorpusActionLookup
from sentinel.execution.states import CommandState, RuntimeState


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith(
                "SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s"):
            row = self.conn.rows.get(params[0])
            self.rows = [] if row is None else [row]
            return
        if "WHERE cursor_name LIKE %s" in normalized:
            pattern = params[0]
            prefix, suffix = pattern.split("%", 1)
            matched = [(key, value) for key, value in self.conn.rows.items()
                       if key.startswith(prefix) and key.endswith(suffix)]
            matched.sort(key=lambda item: (item[1][0], item[0]))
            self.rows = [value for _key, value in matched]
            return
        if normalized.startswith("INSERT INTO sentinel_processed_sessions"):
            cursor_name, session, state = params
            import json
            self.conn.rows.setdefault(
                cursor_name, (date.fromisoformat(str(session)), json.loads(state)))
            self.rows = []
            return
        raise AssertionError(normalized)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def __init__(self):
        self.rows = {}
        self.commits = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


class _Plan:
    plan_id = "sentinel-plan"
    decision_session = date(2026, 8, 20)
    effective_session = date(2026, 8, 21)

    def fingerprint(self):
        return "a" * 64


def _pending(conn):
    return mirror.record_pending(
        conn, plan=_Plan(), active_security_ids=("SEC-A",),
        active_symbols={"SEC-A": "AAA"},
        sizing_authority_sha256="b" * 64,
        shadow_record_sha256="c" * 64,
        publication_version=7)


def test_pending_is_immutable_and_requires_every_symbol():
    conn = _Conn()
    first = _pending(conn)
    assert first["status"] == mirror.PENDING
    assert _pending(conn) == first
    assert len(conn.rows) == 1

    with pytest.raises(
            mirror.InformationalPaperMirrorRefused,
            match="active symbols"):
        mirror.record_pending(
            _Conn(), plan=_Plan(), active_security_ids=("SEC-A",),
            active_symbols={}, sizing_authority_sha256="b" * 64,
            shadow_record_sha256="c" * 64, publication_version=7)


def test_every_new_publication_rechecks_old_session_and_latches_correction(
        monkeypatch):
    conn = _Conn()
    _pending(conn)
    monkeypatch.setattr(mirror.journal, "load_plan", lambda *_args, **_kwargs: _Plan())
    current = {"lookup": CorpusActionLookup(
        start=_Plan.decision_session, events={})}
    monkeypatch.setattr(
        mirror, "corpus_action_lookup",
        lambda *_args, **_kwargs: current["lookup"])

    result = mirror.revalidate_all(
        conn, checked_through=_Plan.effective_session,
        publication_version=8)
    assert result["status"] == mirror.NO_UNIT_CHANGE
    assert mirror.require_transport_permitted(
        conn, current_frontier=_Plan.effective_session,
        current_publication_version=8)["status"] == mirror.NO_UNIT_CHANGE

    # A later publication adds an unsupported row whose permanent id is not
    # resolved but whose canonical target symbol intersects the old plan.
    event = CorporateActionEvent(
        security_id=None, ticker="AAA", session=_Plan.effective_session,
        action="merger", value=None, contraticker="BBB",
        source_row_id="late-correction", reason="unsupported")
    current["lookup"] = CorpusActionLookup(
        start=_Plan.decision_session, events={},
        unresolved_events=(event,))
    with pytest.raises(
            mirror.InformationalPaperMirrorMismatch,
            match="blocks future PAPER"):
        mirror.revalidate_all(
            conn, checked_through=_Plan.effective_session,
            publication_version=9)

    # Removing the row in yet another publication cannot un-disprove the
    # historical PAPER transport; the mismatch is a durable operational latch.
    current["lookup"] = CorpusActionLookup(
        start=_Plan.decision_session, events={})
    with pytest.raises(
            mirror.InformationalPaperMirrorMismatch,
            match="blocks future PAPER"):
        mirror.revalidate_all(
            conn, checked_through=_Plan.effective_session,
            publication_version=10)
    with pytest.raises(mirror.InformationalPaperMirrorMismatch):
        mirror.require_transport_permitted(
            conn, current_frontier=_Plan.effective_session,
            current_publication_version=10)


def test_scalar_split_is_material_even_without_unsupported_event(monkeypatch):
    conn = _Conn()
    _pending(conn)
    monkeypatch.setattr(mirror.journal, "load_plan", lambda *_args, **_kwargs: _Plan())
    monkeypatch.setattr(
        mirror, "corpus_action_lookup",
        lambda *_args, **_kwargs: CorpusActionLookup(
            start=_Plan.decision_session,
            events={"SEC-A": ((_Plan.effective_session, Decimal(2)),)}))

    with pytest.raises(mirror.InformationalPaperMirrorMismatch):
        mirror.revalidate_all(
            conn, checked_through=_Plan.effective_session,
            publication_version=8)


def test_due_session_requires_exact_current_publication_check():
    conn = _Conn()
    _pending(conn)
    with pytest.raises(
            mirror.InformationalPaperMirrorPending,
            match="current source-final publication"):
        mirror.require_transport_permitted(
            conn, current_frontier=_Plan.effective_session,
            current_publication_version=8)


def test_current_plan_status_is_bound_to_exact_cycle_plan(monkeypatch):
    conn = _Conn()
    _pending(conn)
    monkeypatch.setattr(mirror.journal, "load_plan", lambda *_args: _Plan())
    monkeypatch.setattr(
        mirror, "corpus_action_lookup",
        lambda *_args, **_kwargs: CorpusActionLookup(
            start=_Plan.decision_session, events={}))
    mirror.revalidate_all(
        conn, checked_through=_Plan.effective_session,
        publication_version=8)

    status = mirror.require_current_plan_status(
        conn, plan_id=_Plan.plan_id, plan_fingerprint="a" * 64,
        current_frontier=_Plan.effective_session,
        current_publication_version=8)
    assert status["status"] == mirror.NO_UNIT_CHANGE

    with pytest.raises(
            mirror.InformationalPaperMirrorRefused,
            match="no informational mirror stamp"):
        mirror.require_current_plan_status(
            conn, plan_id="different-plan", plan_fingerprint="a" * 64,
            current_frontier=_Plan.effective_session,
            current_publication_version=8)
    with pytest.raises(
            mirror.InformationalPaperMirrorRefused,
            match="different mirror intent"):
        mirror.require_current_plan_status(
            conn, plan_id=_Plan.plan_id, plan_fingerprint="d" * 64,
            current_frontier=_Plan.effective_session,
            current_publication_version=8)


def test_integrity_refusal_is_not_typed_as_ordinary_pending():
    conn = _Conn()
    with pytest.raises(mirror.InformationalPaperMirrorRefused) as raised:
        mirror.require_pending_for_plan(
            conn, plan=_Plan(), sizing_authority_sha256="b" * 64,
            shadow_record_sha256="c" * 64)
    assert not isinstance(
        raised.value, mirror.InformationalPaperMirrorPending)


def _reconciling_order(*, replaced: bool):
    order = BrokerOrder(
        broker_order_id="order-1", client_key="sntl-0123456789abcdef0123",
        instrument=BrokerInstrument("SEC-A", "AAA", "asset-a"),
        side=Side.BUY, state=CommandState.ACKNOWLEDGED,
        quantity=Decimal(1), external_replacement=replaced)
    observation = BrokerObservation(
        observed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        orders=(order,))
    return SimpleNamespace(
        runtime_state=RuntimeState.RECONCILING, clean=True,
        observation=observation, detail="working order")


def test_external_replacement_is_permanent_before_generic_amber_retry():
    with pytest.raises(
            paper.PaperActivationRefused,
            match="all broker mutations are blocked"):
        paper_reconciliation_evidence._dual_mutation_observation_or_refuse(  # noqa: SLF001
            _reconciling_order(replaced=True))

    with pytest.raises(paper.PaperRetryableRefused):
        paper_reconciliation_evidence._dual_mutation_observation_or_refuse(  # noqa: SLF001
            _reconciling_order(replaced=False))
