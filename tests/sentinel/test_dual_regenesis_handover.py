from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import dual_reconciliation
from sentinel.execution.states import CommandState


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        text = str(statement)
        if "pg_try_advisory_lock" in text:
            self.conn.lock_attempts += 1
            self.row = (True,)
            return
        if "pg_advisory_unlock" in text:
            self.conn.unlocks += 1
            self.row = (True,)
            return
        if "SELECT clock_timestamp()" in text:
            self.row = (self.conn.now,)
            return
        if "FROM sentinel_observations o" in text:
            row = self.conn.observation_row
            if params:
                wanted = int(params[0])
                self.row = row if row is not None and int(row[0]) == wanted else None
            else:
                self.row = row
            return
        if ("SELECT session,state FROM sentinel_processed_sessions" in text
                and "WHERE cursor_name=%s" in text):
            self.row = self.conn.receipt
            return
        if "INSERT INTO sentinel_processed_sessions" in text:
            assert params is not None and len(params) == 3
            self.conn.receipt = (params[1], json.loads(params[2]))
            self.row = None
            return
        raise AssertionError(text)

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, now, *, observation_row=None):
        self.now = now
        self.observation_row = observation_row
        self.receipt = None
        self.commits = 0
        self.rollbacks = 0
        self.lock_attempts = 0
        self.unlocks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _segment(marker="b" * 64, index=2):
    return SimpleNamespace(index=index, marker_sha256=marker)


def _binding(*, account="paper-1", epoch=3, deployment="deploy-1"):
    return SimpleNamespace(identity=SimpleNamespace(
        deployment_id=deployment, broker="alpaca",
        broker_account_id=account, takeover_epoch=epoch))


def _plan():
    return SimpleNamespace(
        plan_id="sentinel-plan", decision_session=date(2026, 8, 26),
        effective_session=date(2026, 8, 27), target_exposure=Decimal("1"),
        data_version=7, shadow_snapshot_hash="s" * 64,
        deployment_id="deploy-1", broker="alpaca",
        broker_account_id="paper-1", takeover_epoch=3,
        fingerprint=lambda: "f" * 64)


def _authority(now, *, observed_at=None):
    observed = observed_at or (now - timedelta(seconds=2))
    return {
        "plan_id": "sentinel-plan",
        "plan_fingerprint": "f" * 64,
        "decision_session": "2026-08-26",
        "authority_sha256": "a" * 64,
        "broker_observation": {
            "observed_at": observed.isoformat(),
            "started_at": (observed - timedelta(seconds=1)).isoformat(),
            "terminal_recovery_through": observed.isoformat(),
            "completeness": "COMPLETE",
            "account_identity": {"broker": "alpaca", "account_id": "paper-1"},
            "positions": [],
            "orders": [],
        },
    }


def _durable_order(state=CommandState.ACKNOWLEDGED.value):
    return {
        "id": "order-1", "key": "sntl-key", "security_id": "perm-1",
        "symbol": "ABC", "broker_instrument_id": "asset-1", "side": "BUY",
        "state": state, "qty": "10", "filled": "0",
        "filled_average_price": None,
        "submitted_at": "2026-08-26T23:49:00+00:00",
        "external_replacement": False, "replaced_by": None, "replaces": None,
    }


def _observation_row(
        now, *, observed_at=None, account="paper-1", seq=17,
        position=False, orders=None, runtime_state="RUNNING",
        completeness="COMPLETE", terminal_through=None):
    observed = observed_at or (now - timedelta(seconds=1))
    terminal = terminal_through if terminal_through is not None else observed
    positions = {"perm-1": "10"} if position else {}
    provenance_positions = ([{
        "security_id": "perm-1", "symbol": "ABC",
        "broker_instrument_id": "asset-1", "quantity": "10",
    }] if position else [])
    return (
        seq, observed, terminal, completeness, positions, list(orders or []),
        runtime_state, "alpaca", account, observed, {
            "started_at": (observed - timedelta(seconds=1)).isoformat(),
            "positions": provenance_positions,
        },
    )


def _record(conn, *, binding=None, plan=None):
    return dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=plan or _plan(), binding=binding or _binding(),
        sizing_authority_sha256="a" * 64)


def _install_authority_and_no_commands(monkeypatch, authority):
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: authority)
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())


def test_first_regenesis_adoption_records_two_bound_authorities(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now))
    _install_authority_and_no_commands(monkeypatch, _authority(now))

    receipt = _record(conn)

    assert receipt["schema"] == dual_reconciliation.REGENESIS_HANDOVER_SCHEMA
    assert receipt["segment_marker_sha256"] == "b" * 64
    assert receipt["adopted_plan_id"] == "sentinel-plan"
    assert receipt["sizing_authority_sha256"] == "a" * 64
    assert receipt["broker_observation_seq"] == 17
    assert len(receipt["broker_observation_sha256"]) == 64
    assert len(receipt["handover_sha256"]) == 64
    assert conn.receipt is not None
    assert conn.lock_attempts == 1
    assert conn.unlocks == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_first_regenesis_adoption_refuses_old_strategy_positions(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now, position=True))
    _install_authority_and_no_commands(monkeypatch, _authority(now))

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="broker account is not flat"):
        _record(conn)
    assert conn.receipt is None


def test_first_regenesis_adoption_refuses_working_broker_order(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(
        now, observation_row=_observation_row(
            now, orders=[_durable_order()]))
    _install_authority_and_no_commands(monkeypatch, _authority(now))

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="working order"):
        _record(conn)


def test_first_regenesis_adoption_requires_finalized_clean_reconciliation(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(
        now, observation_row=_observation_row(
            now, runtime_state="RECONCILING"))
    _install_authority_and_no_commands(monkeypatch, _authority(now))

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="RUNNING/COMPLETE"):
        _record(conn)


def test_first_regenesis_adoption_refuses_inflight_local_command(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now))
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now))
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: (SimpleNamespace(client_key="sntl-live"),))

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="durable Sentinel command"):
        _record(conn)


def test_stale_handover_can_refresh_broker_safety_without_rewriting_plan(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    # The immutable plan was sized earlier and remains unchanged.
    authority = _authority(now, observed_at=now - timedelta(minutes=20))
    stale = now - timedelta(
        seconds=dual_reconciliation.REGENESIS_HANDOVER_MAX_AGE_SECONDS + 1)
    conn = _Conn(now, observation_row=_observation_row(now, observed_at=stale))
    _install_authority_and_no_commands(monkeypatch, authority)

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="too old"):
        _record(conn)
    assert conn.receipt is None

    # A same-session preparation retry records a new clean reconciliation row;
    # the frozen sizing authority is not replaced, but handover safety is fresh.
    conn.observation_row = _observation_row(now, observed_at=now - timedelta(seconds=1))
    receipt = _record(conn)
    assert receipt["sizing_authority_sha256"] == "a" * 64
    assert receipt["broker_observed_at"] == (
        now - timedelta(seconds=1)).isoformat()


def test_latest_flat_reconciliation_must_not_predate_sizing_observation(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(
        now, observation_row=_observation_row(
            now, observed_at=now - timedelta(seconds=3)))
    _install_authority_and_no_commands(
        monkeypatch, _authority(now, observed_at=now - timedelta(seconds=1)))

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="predates"):
        _record(conn)


def test_existing_handover_allows_later_nonflat_days_without_reset(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now))
    _install_authority_and_no_commands(monkeypatch, _authority(now))
    first = _record(conn)

    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: pytest.fail(
            "an established segment handover must not demand a flat account again"))
    # Current account reality may now be invested; the receipt references and
    # revalidates the immutable original flat reconciliation row by sequence/hash.
    second = _record(
        conn, plan=SimpleNamespace(
            **{**_plan().__dict__, "plan_id": "later-plan",
               "fingerprint": lambda: "e" * 64}))

    assert second == first
    assert conn.commits == 1


def test_existing_handover_survives_takeover_epoch_for_same_broker_account(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now))
    _install_authority_and_no_commands(monkeypatch, _authority(now))
    first = _record(conn, binding=_binding(epoch=3))

    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: pytest.fail(
            "a takeover epoch must not erase an established economic handover"))
    later = _record(
        conn, binding=_binding(epoch=4),
        plan=SimpleNamespace(
            **{**_plan().__dict__, "plan_id": "later-plan",
               "fingerprint": lambda: "e" * 64}))

    assert later == first
    assert first["takeover_epoch"] == 3


def test_existing_handover_refuses_different_broker_account(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now))
    _install_authority_and_no_commands(monkeypatch, _authority(now))
    _record(conn)

    with pytest.raises(
            dual_reconciliation.DualReconciliationRefused,
            match="another broker account"):
        _record(
            conn, binding=_binding(account="paper-2", epoch=4),
            plan=SimpleNamespace(
                **{**_plan().__dict__, "plan_id": "later-plan",
                   "fingerprint": lambda: "e" * 64}))


def test_handover_refuses_referenced_broker_evidence_mutation(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now, observation_row=_observation_row(now))
    _install_authority_and_no_commands(monkeypatch, _authority(now))
    _record(conn)

    # A terminal order still satisfies flat/no-live-order semantics, so the
    # content hash—not merely semantic rechecking—must catch this rewrite.
    conn.observation_row = _observation_row(
        now, orders=[_durable_order(CommandState.FILLED.value)])
    with pytest.raises(
            dual_reconciliation.DualReconciliationRefused,
            match="evidence changed"):
        dual_reconciliation._load_regenesis_handover(
            conn, segment=_segment(), observation_id="primary")


def test_current_post_gap_plan_without_handover_is_not_execution_authority(monkeypatch):
    marker = "d" * 64
    state = SimpleNamespace(last_processed_session="2026-08-26")
    result = SimpleNamespace(
        session="2026-08-26", shadow_verdict="SHADOW_GO",
        verification="VERIFIED", state=state)
    monkeypatch.setattr(
        dual_reconciliation.shadow_runtime, "verified_shadow_status",
        lambda *_args, **_kwargs: result)
    monkeypatch.setattr(
        dual_reconciliation.shadow_segments, "active_segment",
        lambda *_args, **_kwargs: _segment(marker=marker))
    monkeypatch.setattr(
        dual_reconciliation, "_load_regenesis_handover",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        dual_reconciliation.journal, "latest_plan",
        lambda _conn: SimpleNamespace(decision_session=date(2026, 8, 26)))
    monkeypatch.setenv(dual_reconciliation.REGENESIS_APPROVAL_ENV, marker)

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="no durable flat broker handover"):
        dual_reconciliation.verified_shadow_intent(
            object(), decision_session="2026-08-26",
            observation_id="primary", starting_cash="100000")
