"""Backup-package ownership across a copied physical restore."""
import os
import time
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import backup_guard, backup_runtime_authority
from tests.internal_state.contract import Action
from tests.internal_state.physical import PhysicalCluster
from tests.internal_state.runtime import Lifecycle


def test_restored_data_does_not_republish_inherited_backup_metadata(tmp_path):
    cluster = object.__new__(PhysicalCluster)
    cluster.root = tmp_path
    cluster.wal_root = tmp_path / "wal"
    cluster.counter = 1
    base = tmp_path / "base"
    base.mkdir()
    names = ("sentinel-recovery-marker", "sentinel-pitr-base-identity")
    for name in names:
        (base / name).write_text("original-proof")
    cluster.checkpoints = {"saved": {"base": base, "system_id": "1", "marker": "saved"}}
    cluster.stop_server = lambda: None
    cluster.own = lambda path: None
    verified = []
    def command(name, *args, **kwargs):
        assert name == "pg_verifybackup"
        assert all((args[-1] / file).read_text() == "original-proof" for file in names)
        verified.append(args[-1])
    cluster.command = command
    def start():
        assert verified == [cluster.primary]
        assert all(not (cluster.primary / name).exists() for name in names)
    cluster._start_server = start
    cluster.sql = lambda query: (False,)
    checkpoints = []
    cluster.checkpoint = checkpoints.append
    cluster.restore("saved")
    assert checkpoints == ["after_restore"]
    assert all((base / name).read_text() == "original-proof" for name in names)


@pytest.mark.parametrize("failure", [
    RuntimeError("WAL publication deadline expired"),
    backup_runtime_authority.BackupRuntimeUnavailable("archiver unresolved"),
    backup_runtime_authority.BackupRuntimeRefused("corrupt restore chain"),
])
def test_failed_media_repair_remains_pending_and_cannot_claim_recovery(failure):
    lab = object.__new__(Lifecycle)
    lab.media_saved = b"retained-marker"
    lab.coverage = set()
    lab.snapshot = lambda: {"state": {"unchanged": True}}

    def repair(marker):
        assert marker == b"retained-marker"
        raise failure

    lab.cluster = SimpleNamespace(repair_wal_media=repair)
    with pytest.raises(type(failure), match=str(failure)):
        lab.action(Action(kind="media_repair"))
    assert lab.media_saved == b"retained-marker"
    assert "backup_authority_recovered" not in lab.coverage


def test_media_repair_recovers_a_real_failed_archive_before_next_mutation():
    try:
        cluster = PhysicalCluster()
    except RuntimeError as exc:
        if os.environ.get("ALPACA_HARNESS_REQUIRE_POSTGRES") == "1":
            raise
        pytest.skip(str(exc))
    try:
        cluster.start()
        marker = cluster.wal_root / ".sentinel-independent-durable-target-v1"
        original = marker.read_bytes()
        with cluster.runtime(), psycopg.connect(cluster.dsn, autocommit=True) as conn:
            marker.unlink()
            failed_target = backup_guard._probe_wal_boundary(  # noqa: SLF001
                conn, operation="deterministic media loss")
            deadline = time.monotonic() + 30
            while True:
                last_ok, last_fail = cluster.sql(
                    "SELECT last_archived_time,last_failed_time FROM pg_stat_archiver")
                if last_fail is not None and (last_ok is None or last_fail > last_ok):
                    break
                if time.monotonic() >= deadline:
                    pytest.fail("archive failure was not observed while media was missing")
                time.sleep(0.1)
            with pytest.raises(backup_runtime_authority.BackupRuntimeUnavailable):
                backup_runtime_authority.require(conn, operation="write during media loss")

            proof = cluster.repair_wal_media(original)
            assert proof["enabled"] is True
            assert proof["recoverable_through_wal"] > failed_target
            assert proof["wal_integrity"] == "sha256-sidecar-v1"
            last_ok, last_fail = cluster.sql(
                "SELECT last_archived_time,last_failed_time FROM pg_stat_archiver")
            assert last_ok >= last_fail
            assert backup_runtime_authority.require(
                conn, operation="next mutation after media repair")["enabled"] is True
    finally:
        cluster.close()
