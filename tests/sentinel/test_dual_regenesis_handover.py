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
    def __init__(self, now):
        self.now = now
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


def _authority(now, *, positions=None, orders=None):
    return {
        "plan_id": "sentinel-plan",
        "plan_fingerprint": "f" * 64,
        "decision_session": "2026-08-26",
        "authority_sha256": "a" * 64,
        "broker_observation": {
            "observed_at": (now - timedelta(seconds=2)).isoformat(),
            "started_at": (now - timedelta(seconds=3)).isoformat(),
            "terminal_recovery_through": now.isoformat(),
            "completeness": "COMPLETE",
            "account_identity": {"broker": "alpaca", "account_id": "paper-1"},
            "positions": list(positions or []),
            "orders": list(orders or []),
        },
    }


def _position():
    return {
        "instrument": {
            "security_id": "perm-1", "symbol": "ABC", "broker_id": "asset-1"},
        "quantity": "10",
    }


def _order(state=CommandState.ACKNOWLEDGED.value, *, replaced=False):
    return {
        "broker_order_id": "order-1", "client_key": "sntl-key",
        "instrument": {
            "security_id": "perm-1", "symbol": "ABC", "broker_id": "asset-1"},
        "side": "BUY", "state": state, "quantity": "10",
        "filled_quantity": "0", "filled_average_price": None,
        "submitted_at": "2026-08-26T12:00:00+00:00",
        "external_replacement": replaced,
    }


def test_first_regenesis_adoption_records_exact_flat_handover(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now)
    authority = _authority(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: authority)
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())

    receipt = dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=_plan(), binding=_binding())

    assert receipt["segment_marker_sha256"] == "b" * 64
    assert receipt["adopted_plan_id"] == "sentinel-plan"
    assert receipt["sizing_authority_sha256"] == "a" * 64
    assert len(receipt["handover_sha256"]) == 64
    assert conn.receipt is not None
    assert conn.lock_attempts == 1
    assert conn.unlocks == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_first_regenesis_adoption_refuses_old_strategy_positions(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now, positions=[_position()]))
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="broker account is not flat"):
        dual_reconciliation._record_or_require_regenesis_handover(
            conn, segment=_segment(), observation_id="primary",
            plan=_plan(), binding=_binding())
    assert conn.receipt is None


def test_first_regenesis_adoption_refuses_working_or_replaced_order(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())

    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now, orders=[_order()]))
    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="working order"):
        dual_reconciliation._record_or_require_regenesis_handover(
            conn, segment=_segment(), observation_id="primary",
            plan=_plan(), binding=_binding())

    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(
            now, orders=[_order(CommandState.CANCELLED.value, replaced=True)]))
    with pytest.raises(
            dual_reconciliation.DualReconciliationRefused,
            match="externally replaced"):
        dual_reconciliation._record_or_require_regenesis_handover(
            conn, segment=_segment(), observation_id="primary",
            plan=_plan(), binding=_binding())


def test_first_regenesis_adoption_refuses_inflight_local_command(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now))
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: (SimpleNamespace(client_key="sntl-live"),))

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="durable Sentinel command"):
        dual_reconciliation._record_or_require_regenesis_handover(
            conn, segment=_segment(), observation_id="primary",
            plan=_plan(), binding=_binding())


def test_regenesis_handover_cannot_be_minted_from_stale_broker_read(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    authority = _authority(now)
    authority["broker_observation"]["observed_at"] = (
        now - timedelta(
            seconds=dual_reconciliation.REGENESIS_HANDOVER_MAX_AGE_SECONDS + 1)
    ).isoformat()
    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: authority)
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())

    with pytest.raises(
            dual_reconciliation.DualReconciliationPending,
            match="too old"):
        dual_reconciliation._record_or_require_regenesis_handover(
            conn, segment=_segment(), observation_id="primary",
            plan=_plan(), binding=_binding())


def test_existing_handover_allows_later_nonflat_days_without_reset(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now))
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())
    first = dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=_plan(), binding=_binding())

    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: pytest.fail(
            "an established segment handover must not demand a flat account again"))
    second = dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=SimpleNamespace(
            **{**_plan().__dict__, "plan_id": "later-plan",
               "fingerprint": lambda: "e" * 64}),
        binding=_binding())

    assert second == first
    assert conn.commits == 1


def test_existing_handover_survives_takeover_epoch_for_same_broker_account(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now))
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())
    first = dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=_plan(), binding=_binding(epoch=3))

    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: pytest.fail(
            "a takeover epoch must not erase an established economic handover"))
    later = dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=SimpleNamespace(
            **{**_plan().__dict__, "plan_id": "later-plan",
               "fingerprint": lambda: "e" * 64}),
        binding=_binding(epoch=4))

    assert later == first
    assert first["takeover_epoch"] == 3


def test_existing_handover_refuses_different_broker_account(monkeypatch):
    now = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
    conn = _Conn(now)
    monkeypatch.setattr(
        dual_reconciliation.dual_plan_authority, "load_authority",
        lambda *_args, **_kwargs: _authority(now))
    monkeypatch.setattr(
        dual_reconciliation.journal, "in_flight_commands",
        lambda *_args, **_kwargs: ())
    dual_reconciliation._record_or_require_regenesis_handover(
        conn, segment=_segment(), observation_id="primary",
        plan=_plan(), binding=_binding())

    with pytest.raises(
            dual_reconciliation.DualReconciliationRefused,
            match="another broker account"):
        dual_reconciliation._record_or_require_regenesis_handover(
            conn, segment=_segment(), observation_id="primary",
            plan=SimpleNamespace(
                **{**_plan().__dict__, "plan_id": "later-plan",
                   "fingerprint": lambda: "e" * 64}),
            binding=_binding(account="paper-2", epoch=4))


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
