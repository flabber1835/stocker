from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import (
    automation_recovery,
    dual_plan_authority,
    shadow_recovery,
    shadow_segments,
    shadow_supervisor,
)
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerInstrument,
    BrokerObservation,
    BrokerPosition,
    Completeness,
)


# Reuse the repository's real-PostgreSQL integration harness. Sentinel's test
# package deliberately is not a Python package, so make only tests/support
# importable instead of adding an __init__.py that could shadow sentinel itself.
_SUPPORT = Path(__file__).resolve().parents[1] / "support"
if str(_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_SUPPORT))
from postgres import _EphemeralPostgres  # noqa: E402


OBSERVATION_ID = "outage-regenesis-integration"
PREDECESSOR_SESSION = "2026-08-17"
RECOVERY_SESSION = "2026-08-20"
NOW = datetime(2026, 8, 20, 20, 15, tzinfo=timezone.utc)
IDENTITY = BrokerAccountIdentity(broker="alpaca", account_id="paper-integration")
INSTRUMENT = BrokerInstrument(
    security_id="perm-existing", symbol="OLD", broker_id="asset-existing")


@pytest.fixture
def real_postgres_dsn():
    postgres = _EphemeralPostgres()
    postgres.start()
    try:
        yield postgres.sync_dsn
    finally:
        postgres.stop()


def _install_cursor_table(dsn: str) -> None:
    conn = psycopg.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE sentinel_processed_sessions ("
                "cursor_name TEXT PRIMARY KEY,"
                "session TEXT NOT NULL,"
                "state JSONB NOT NULL)"
            )
        conn.commit()
    finally:
        conn.close()


def _seed_nonempty_certified_predecessor_and_rollover(dsn: str):
    conn = psycopg.connect(dsn)
    try:
        store = shadow_segments._LegacyStore(
            conn, observation_id=OBSERVATION_ID)
        store.append_genesis({
            "observation_id": OBSERVATION_ID,
            "first_session": PREDECESSOR_SESSION,
            "genesis_sha256": "1" * 64,
        })
        # The predecessor is deliberately nonempty and carries a runtime
        # authority, so rollover anchors to certified strategy history rather
        # than to a genesis-only placeholder.
        store.append({
            "observation_id": OBSERVATION_ID,
            "session": PREDECESSOR_SESSION,
            "shadow_verdict": "SHADOW_GO",
            "verification": "VERIFIED",
            "record_sha256": "2" * 64,
        })
        store.append_authority({
            "observation_id": OBSERVATION_ID,
            "session": PREDECESSOR_SESSION,
            "authority_sha256": "3" * 64,
        })
        conn.commit()

        staged = shadow_segments.rollover(
            conn,
            logical_observation_id=OBSERVATION_ID,
            first_session=RECOVERY_SESSION,
            reason=shadow_segments.SEGMENT_REASON_MULTI_SESSION_GAP,
            new_data_publication_sha256="4" * 64,
            validated_source_identity_sha256="5" * 64,
        )
        assert staged.index == 1
        assert staged.predecessor_session == PREDECESSOR_SESSION
        assert staged.predecessor_anchor_kind == "RUNTIME_AUTHORITY"

        # Match production atomicity: the staged marker becomes durable only
        # with the new segment's fresh genesis commit.
        new_store = shadow_segments.SegmentedPostgresShadowObservationStore(
            conn, observation_id=OBSERVATION_ID)
        assert new_store.segment.index == 1
        new_store.append_genesis({
            "observation_id": OBSERVATION_ID,
            "first_session": RECOVERY_SESSION,
            "genesis_sha256": "6" * 64,
        })
        return staged
    finally:
        conn.rollback()
        conn.close()


def _nonflat_predecessor_book() -> BrokerObservation:
    return BrokerObservation(
        observed_at=NOW,
        started_at=NOW,
        terminal_recovery_through=NOW,
        completeness=Completeness.COMPLETE,
        account_identity=IDENTITY,
        positions=(BrokerPosition(
            instrument=INSTRUMENT, quantity=Decimal("10")),),
        orders=(),
    )


def test_real_segment_rollover_cannot_adopt_nonflat_predecessor_book(
        real_postgres_dsn, monkeypatch):
    """Production composition fences strategy re-genesis before plan adoption."""
    _install_cursor_table(real_postgres_dsn)
    staged = _seed_nonempty_certified_predecessor_and_rollover(
        real_postgres_dsn)

    # Prove the segment boundary is truly durable and visible from a fresh
    # database session, as it will be to the independent PAPER process.
    conn = psycopg.connect(real_postgres_dsn)
    try:
        active = shadow_segments.active_segment(conn, OBSERVATION_ID)
        assert active.index == 1
        assert active.marker_sha256 == staged.marker_sha256
        assert active.reason == shadow_segments.SEGMENT_REASON_MULTI_SESSION_GAP
    finally:
        conn.close()

    runtime = object.__new__(automation_recovery.ProductionAutomation)
    runtime._dual_run_enabled = True
    runtime._shadow_observation_id = OBSERVATION_ID
    runtime._shadow_starting_cash = "100000"
    runtime.connect = lambda: psycopg.connect(real_postgres_dsn)
    runtime._require_backup_for_new_mutation = lambda _operation: None

    adopted = []

    async def production_prepare_seam(_self, _context):
        # This is the exact task-local scope used around immutable plan sizing
        # before adopt_current_plan(). A non-flat Alpaca observation must fail
        # here; the simulated adoption marker below must remain unreachable.
        assert dual_plan_authority.regenesis_flat_sizing_required() is True
        dual_plan_authority._require_flat_regenesis_observation(
            _nonflat_predecessor_book())
        adopted.append(True)

    monkeypatch.setattr(
        automation_recovery.base.ProductionAutomation,
        "prepare",
        production_prepare_seam,
    )

    with pytest.raises(
            automation_recovery.TransientInfrastructureFailure,
            match="flat, settled predecessor account"):
        asyncio.run(runtime.prepare(object()))

    assert adopted == []
    assert dual_plan_authority.regenesis_flat_sizing_required() is False


def test_docker_health_is_non_green_during_multi_session_gap(
        tmp_path, monkeypatch):
    """Compose's exact --health path must fail while causal recovery is pending."""
    heartbeat = tmp_path / "shadow-heartbeat"
    heartbeat.touch()
    monkeypatch.setattr(shadow_supervisor, "HEARTBEAT_FILE", heartbeat)
    monkeypatch.setattr(
        shadow_supervisor, "LATCH_FILE", tmp_path / "shadow-critical.json")

    config = SimpleNamespace(database_url="unused", observation_id="primary")
    monkeypatch.setattr(
        shadow_recovery.base,
        "preflight",
        lambda *_args, **_kwargs: {
            "status": "ATTESTED_STRUCTURAL",
            "latest_session": "2026-08-17",
        },
    )
    monkeypatch.setattr(
        shadow_recovery.calendar,
        "latest_closed_session",
        lambda _now: "2026-08-20",
    )
    monkeypatch.setattr(
        shadow_recovery.calendar,
        "next_session",
        lambda session: {
            "2026-08-17": "2026-08-18",
            "2026-08-20": "2026-08-21",
        }[str(session)],
    )

    # shadow_supervisor imported the production function object directly; its
    # module globals above are the same patched shadow_recovery dependencies.
    assert shadow_supervisor._health(30.0, config=config) == 1
