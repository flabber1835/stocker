from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import backup_runtime_authority as authority
from sentinel import paper
from sentinel.feed import ingest_authority_impl as ingest_authority
from sentinel.feed import store as feed_store
from sentinel.execution import authority_gate, executor, journal
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import (
    GuardedExecutionBroker, ManualExecutionGrant, PreTransportAuthorityRefused)
from sentinel.execution.simulator import SimulatedBroker
from lab import Database, Media, wal_name


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    return Database(Media(tmp_path / "media"))


def test_same_size_wal_corruption_is_an_integrity_refusal_and_repairs(world):
    assert authority.require(world, operation="review regression")["wal_integrity"] == \
        "sha256-sidecar-v1"
    path = world.media.namespace / wal_name(4)
    size = path.stat().st_size
    with path.open("r+b") as stream:
        stream.seek(4096)
        stream.write(b"post-publication-bit-rot")
    assert path.stat().st_size == size
    with pytest.raises(authority.BackupRuntimeRefused, match="SHA-256"):
        authority.require(world, operation="review regression")
    world.media.segment(4)
    assert authority.require(world, operation="review regression")["wal_segments"] == 4


def test_missing_wal_checksum_is_a_retryable_restore_horizon_fence(world):
    sidecar = world.media.namespace / f"{wal_name(4)}.sha256"
    sidecar.unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable, match="sidecar"):
        authority.require(world, operation="review regression")
    world.media.segment(4)
    authority.require(world, operation="review regression")


def test_production_mutation_surfaces_are_wired_to_full_chain_authority():
    root = Path(__file__).resolve().parents[2]
    paper_source = (root / "sentinel" / "paper" / "__init__.py").read_text()
    ingest = (root / "sentinel" / "feed" / "ingest_authority_impl.py").read_text()
    compose = (root / "docker-compose.sentinel-backup.yml").read_text()

    assert '_backup_runtime_authority.require(conn, operation=operation)' in paper_source
    assert 'operation="paper plan preparation"' in paper_source
    assert 'operation="paper order execution"' in paper_source
    assert 'operation="automated paper order execution"' in paper_source
    assert 'operation="canonical daily feed mutation"' in ingest
    assert 'operation="canonical seed/reseed feed mutation"' in ingest
    assert "SENTINEL_RUNTIME_BACKUP_AUTHORITY: REQUIRED_V1" in compose


@pytest.mark.parametrize("surface", [
    "prepare_paper_plan",
    "execute_paper_plan",
    "execute_automated_paper_plan",
])
def test_paper_mutation_surfaces_fence_before_entering_inner_gateway(
        monkeypatch, surface):
    observed = []

    def unavailable(conn, *, operation):
        observed.append((conn, operation))
        raise authority.BackupRuntimeUnavailable("simulated missing middle WAL")

    monkeypatch.setattr(paper._backup_runtime_authority, "require", unavailable)
    conn = object()
    with pytest.raises(paper.PaperRetryableRefused, match="missing middle WAL"):
        asyncio.run(getattr(paper, surface)(conn=conn))
    assert observed and observed[0][0] is conn


def test_feed_mutation_fences_before_reclaim_or_publication_recovery(monkeypatch):
    calls = []

    def unavailable(conn, *, operation):
        calls.append(("authority", operation))
        raise authority.BackupRuntimeUnavailable("simulated backup-media loss")

    def mutation(*_args, **_kwargs):
        calls.append(("mutation", None))
        raise AssertionError("feed mutation crossed failed restore-horizon gate")

    monkeypatch.setattr(ingest_authority.backup_runtime_authority,
                        "require", unavailable)
    monkeypatch.setattr(ingest_authority._impl.feed_store,
                        "reclaim_orphans", mutation)
    monkeypatch.setattr(ingest_authority.recovery,
                        "resume_pending_publication", mutation)
    with pytest.raises(ConnectionError, match="backup-media loss"):
        ingest_authority._recover_before_run(object())
    assert calls == [("authority", "canonical daily feed mutation")]


def test_read_only_recovery_surface_remains_outside_backup_mutation_gate():
    root = Path(__file__).resolve().parents[2]
    paper_source = (root / "sentinel" / "paper" / "__init__.py").read_text()
    assert "from .recovery import recover_automated_paper_cycle" in paper_source
    assert "async def recover_automated_paper_cycle" not in paper_source


def test_retained_wal_is_never_granted_new_integrity_authority_by_initialization():
    root = Path(__file__).resolve().parents[2]
    backup_lib = (root / "scripts" / "sentinel-backup-lib.sh").read_text()
    archive = (root / "scripts" / "sentinel-archive-wal.sh").read_text()

    assert "sha256sum" not in backup_lib
    assert "publish_checksum" in archive
    assert 'checksum_target="$target.sha256"' in archive


@pytest.mark.parametrize("boundary", [feed_store.corpus_write_lock, journal.writer_lock])
@pytest.mark.parametrize("fault", ["middle-gap", "same-size-corruption", "missing-checksum"])
def test_common_writer_boundaries_fence_real_media_faults_and_release(world, boundary, fault):
    mutations = []
    with boundary(world):
        mutations.append("healthy")
    path = world.media.namespace / wal_name(4)
    if fault == "middle-gap":
        path.unlink()
    elif fault == "missing-checksum":
        path.with_name(path.name + ".sha256").unlink()
    else:
        with path.open("r+b") as stream:
            stream.seek(1024)
            stream.write(b"BIT-ROT")
    refusal = (authority.BackupRuntimeRefused if fault == "same-size-corruption"
               else authority.BackupRuntimeUnavailable)
    with pytest.raises(refusal):
        with boundary(world):
            mutations.append("unsafe")
    assert mutations == ["healthy"]
    assert world.locks == {}
    assert world.rollbacks == 1
    world.media.segment(4)
    with boundary(world):
        mutations.append("repaired")
    assert mutations == ["healthy", "repaired"]
    assert world.locks == {}


def test_recovery_scope_preserves_serialization_and_cannot_authorize_nested_mutation(world):
    (world.media.namespace / wal_name(4)).unlink()
    with journal.writer_lock(world, recovery_only=True):
        assert world.locks == {journal.WRITER_LOCK_KEY: 1}
        with pytest.raises(authority.BackupRuntimeUnavailable):
            with journal.writer_lock(world):
                pytest.fail("recovery scope authorized a new mutation")
        assert world.locks == {journal.WRITER_LOCK_KEY: 1}
    assert world.locks == {}


def test_direct_executor_cannot_bypass_the_full_chain_lock(world, monkeypatch):
    (world.media.namespace / wal_name(4)).unlink()
    # Only plan-object arithmetic is outside this boundary; broker/journal
    # interaction must still be fenced by the production executor's own lock.
    monkeypatch.setattr(executor, "_assert_executable", lambda _plan: None)
    with pytest.raises(authority.BackupRuntimeUnavailable, match="missing/truncated"):
        asyncio.run(executor.execute_session(
            conn=world, broker=object(), deployment=object(), plan=object(),
            instruments={}, today=date(2026, 9, 10)))
    assert world.locks == {}


def test_exact_order_observation_recovery_still_runs_during_backup_loss(world, monkeypatch):
    (world.media.namespace / wal_name(4)).unlink()
    broker = SimulatedBroker()
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: ())
    assert asyncio.run(executor.resolve_outstanding(
        conn=world, broker=broker, deployment=object())) == ()
    assert world.locks == {}


@pytest.mark.parametrize("operation", ["submit", "cancel"])
def test_fresh_broker_mutation_gate_rechecks_media_after_preparation(
        world, monkeypatch, operation):
    monkeypatch.setattr(authority_gate, "load_rollout_state",
                        lambda _conn: SimpleNamespace(mode="CONTROLLER"))
    monkeypatch.setattr(authority_gate.publication, "require_current",
                        lambda _conn: SimpleNamespace(version=1))
    guard = authority_gate.build_fresh_execution_guard(
        connection_factory=lambda: world,
        paper_base_url="https://paper-api.alpaca.markets",
        runtime_identity=lambda: {}, strategy_identity=lambda: {},
        validate_grant=lambda *_args: None,
        authority_check=lambda *_args, **_kwargs: SimpleNamespace(
            certificate_sha256="a" * 64))
    broker = SimulatedBroker()
    wrapped = GuardedExecutionBroker(
        inner=broker, guard=guard,
        grant=ManualExecutionGrant(
            confirm_paper_account="SIM-ACCOUNT", confirm_plan_id="backup-test",
            confirm_effective_session=date(2026, 9, 10),
            confirm_submit_paper_orders=True))
    authority.require(world, operation="prepared while healthy")
    (world.media.namespace / wal_name(4)).unlink()
    # Fresh reads remain reachable on the same guarded broker during the fault.
    asyncio.run(wrapped.observe())
    sends = []

    async def transport(*_args, **_kwargs):
        sends.append(operation)
        return object()

    monkeypatch.setattr(broker, operation, transport)

    def call():
        if operation == "cancel":
            return wrapped.cancel("existing-order")
        return wrapped.submit(
            client_key="backup-test", instrument=BrokerInstrument(
                security_id="SEC-A", symbol="A", broker_id="asset-a"),
            side=Side.BUY, quantity=Decimal(1))

    with pytest.raises(PreTransportAuthorityRefused, match="missing/truncated"):
        asyncio.run(call())
    assert sends == []
    world.media.segment(4)
    asyncio.run(call())
    assert sends == [operation]


def test_common_backup_errors_keep_retry_and_operator_checkpoint_identity():
    from sentinel import automation_runtime, backup_guard
    from sentinel.automation.model import (
        PermanentOperationalRefusal, TransientInfrastructureFailure)
    from sentinel.cli._shared import paper_refusal_types

    unavailable = authority.BackupRuntimeUnavailable("middle WAL absent")
    invalid = authority.BackupRuntimeRefused("SHA-256 mismatch")
    assert isinstance(unavailable, backup_guard.BackupUnavailable)
    assert isinstance(unavailable, ConnectionError)
    assert isinstance(invalid, backup_guard.BackupConfigurationRefused)
    assert isinstance(automation_runtime.classify_dependency_failure(unavailable),
                      TransientInfrastructureFailure)
    assert isinstance(automation_runtime.classify_dependency_failure(invalid),
                      PermanentOperationalRefusal)
    assert isinstance(unavailable, paper_refusal_types())
    assert isinstance(invalid, paper_refusal_types())


def test_runtime_reads_only_required_horizon(world):
    # Retained generations and concurrently arriving later WAL must not add I/O
    # or turn unrelated unreadable media into this base's authority decision.
    for index in (1, 6):
        (world.media.namespace / wal_name(index)).mkdir()
    result = authority.require(world, operation="bounded restore proof")
    assert result["wal_segments"] == 4
    query, params = world.statements[-1]
    assert "unnest" in query
    assert params[-1] == [wal_name(index) for index in range(2, 6)]


def test_recovery_lock_exemptions_are_limited_to_observation_and_lease():
    import ast
    root = Path(__file__).resolve().parents[2]
    found = set()
    for path in (root / "sentinel").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and any(
                    kw.arg == "recovery_only" for kw in node.keywords):
                found.add(str(path.relative_to(root)))
                assert next(kw.value.value for kw in node.keywords
                            if kw.arg == "recovery_only") is True
    assert found == {
        "sentinel/automation/store.py", "sentinel/paper/recovery.py",
        "sentinel/execution/executor.py"}
