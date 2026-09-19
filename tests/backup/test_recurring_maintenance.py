"""Positive lifecycle and independent calendar/WAL retention boundary oracles."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sentinel import backup_retention as retention

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_backup_maintenance as coordinator

SYSTEM = "7377777777777777777"
IMAGE = "sha256:" + "d" * 64
SEGMENT = 16 * 1024 * 1024
NOW = int(datetime(2026, 9, 19, 12, tzinfo=timezone.utc).timestamp())


def position(index):
    value = index * SEGMENT
    return f"{value >> 32:X}/{value & 0xffffffff:X}"


def make_base(root, name, index=10, timeline=1):
    path = root / "base" / name
    path.mkdir()
    (path / "backup_manifest").write_text(json.dumps({"WAL-Ranges": [
        {"Timeline": timeline, "Start-LSN": position(index), "End-LSN": position(index + 1)}]}))
    (path / "backup_label").write_text("independent synthetic metadata; no physical proof claimed\n")
    (path / "sentinel-recovery-marker").write_text(
        f"marker=sentinel-backup-{name[5:]}-42\nlsn={position(index + 2)}\n"
        f"wal={timeline:08X}0000000000000010\nsystem_identifier={SYSTEM}\n")
    (path / "sentinel-pitr-base-identity").write_text(
        f"schema=sentinel.base-backup-pitr/2\nsystem_identifier={SYSTEM}\n")
    (path / "relation-data").write_bytes(b"preserve or unlink this file; never use it as restore authority")
    return path


def select(root, name):
    (root / "base" / f".sentinel-runtime-base-{SYSTEM}-v1").write_text(
        f"schema=sentinel.runtime-base/1\nsystem_identifier={SYSTEM}\nbase_backup={name}\n")


def receipt(item):
    return {"base_backup": item["name"], "metadata_sha256": item["metadata_sha256"],
            "marker": item["marker"], "target_lsn": item["target_lsn"],
            "system_identifier": SYSTEM, "runtime_image": IMAGE, "physical_only": False}


@pytest.fixture
def media(tmp_path):
    for part in ("base", "wal"):
        (tmp_path / part).mkdir()
        (tmp_path / part / retention.MARKER).write_text(retention.MARKER[1:] + "\n")
    (tmp_path / "wal" / ("cluster-" + SYSTEM)).mkdir()
    first = datetime(2026, 8, 15, tzinfo=timezone.utc)
    for day in range(36):
        for hour in (0, 12):
            stamp = first + timedelta(days=day, hours=hour)
            make_base(tmp_path, stamp.strftime("base-%Y%m%dT%H%M%SZ"), 100 + day * 2 + hour // 12)
    select(tmp_path, "base-20260919T120000Z")
    return retention.Media(tmp_path, SYSTEM)


def apply(media):
    with retention.media_lock(media.base):
        return retention.retain(media, receipt(media.selected()), IMAGE, NOW, SEGMENT)


def test_calendar_retention_and_exact_start_segment_boundary(media):
    namespace = media.wal / ("cluster-" + SYSTEM)
    for name in ("000000010000000000000082", "000000010000000000000083",
                 "000000020000000000000001", "00000002.history", "unknown.keep"):
        (namespace / name).write_bytes(b"archived fixture")
        (namespace / (name + ".sha256")).write_text("fixture")
    result = apply(media)
    # Sep 13..19 daily, Aug 30 and Sep 6 weekly, plus the recent midnight.
    expected = {f"base-202609{day:02}T120000Z" for day in range(13, 20)} | {
        "base-20260919T000000Z", "base-20260906T120000Z", "base-20260830T120000Z"}
    assert set(media.inventory()) == expected
    assert result["base_removed"] == 62
    assert result["wal_floor_segment"] == 131
    assert not (namespace / "000000010000000000000082").exists()
    assert not (namespace / "000000010000000000000082.sha256").exists()
    for name in ("000000010000000000000083", "000000020000000000000001",
                 "00000002.history", "unknown.keep"):
        assert (namespace / name).read_bytes() == b"archived fixture"
    assert apply(media)["base_removed"] == 0


@pytest.mark.parametrize("field,value", [
    ("physical_only", True), ("physical_only", 0), ("metadata_sha256", "a" * 64),
    ("runtime_image", "sha256:" + "b" * 64), ("system_identifier", "123"),
    ("base_backup", "base-20260919T000000Z"), ("marker", "wrong"), ("target_lsn", "0/1"),
])
def test_bad_restore_evidence_never_deletes(media, field, value):
    proof = receipt(media.selected())
    proof[field] = value
    with pytest.raises(retention.Refused, match="receipt identity"):
        retention.retain(media, proof, IMAGE, NOW, SEGMENT)
    assert len(media.inventory()) == 72


def test_every_manifest_range_contributes_to_retention_floor(media):
    path = media.base / "base-20260830T120000Z" / "backup_manifest"
    value = json.loads(path.read_text())
    value["WAL-Ranges"].insert(0, {"Timeline": 1, "Start-LSN": "0/1000000", "End-LSN": "0/2000000"})
    path.write_text(json.dumps(value))
    assert apply(media)["wal_floor_segment"] == 1


def test_mixed_timelines_keep_all_wal(media):
    path = media.base / "base-20260830T120000Z" / "backup_manifest"
    value = json.loads(path.read_text())
    value["WAL-Ranges"][0]["Timeline"] = 2
    path.write_text(json.dumps(value))
    namespace = media.wal / ("cluster-" + SYSTEM)
    old = namespace / "000000010000000000000001"
    old.write_bytes(b"old timeline")
    assert apply(media)["wal_policy"] == "mixed_timelines_preserved"
    assert old.exists()


@pytest.mark.parametrize("fault", ["alias", "foreign", "incomplete", "future", "duplicate"])
def test_ambiguous_inventory_never_deletes(media, fault):
    path = media.base / "base-20260815T000000Z"
    if fault == "alias":
        (path / "backup_label").unlink()
        (path / "backup_label").symlink_to(media.base / "base-20260919T120000Z" / "backup_label")
    elif fault == "foreign":
        (path / "sentinel-pitr-base-identity").write_text("system_identifier=123\n")
    elif fault == "incomplete":
        (media.base / ".base-20260919T120000Z.part-1").mkdir()
    elif fault == "future":
        make_base(media.base.parent, "base-20260920T120000Z")
    else:
        (path / "backup_manifest").write_text('{"WAL-Ranges":[],"WAL-Ranges":[]}')
    with pytest.raises((retention.Refused, OSError)):
        apply(media)
    assert (media.base / "base-20260816T000000Z").is_dir()
    assert not (media.base / retention.JOURNAL).exists()


def test_restart_after_partial_quarantine_deletion(media, monkeypatch):
    real = retention.shutil.rmtree
    def interrupted(path):
        (path / "backup_manifest").unlink()
        raise OSError("simulated power loss during removal")
    interrupted.avoids_symlink_attacks = True
    monkeypatch.setattr(retention.shutil, "rmtree", interrupted)
    with pytest.raises(OSError, match="power loss"):
        apply(media)
    assert (media.base / retention.JOURNAL).exists()
    assert list(media.base.glob(".sentinel-prune-*"))
    monkeypatch.setattr(retention.shutil, "rmtree", real)
    assert apply(media)["retention_ready"]
    assert len(media.inventory()) == 10
    assert not (media.base / retention.JOURNAL).exists()


def test_restart_revalidates_every_protected_identity(media, monkeypatch):
    real = retention.os.rename
    monkeypatch.setattr(retention.os, "rename", lambda *_: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        apply(media)
    monkeypatch.setattr(retention.os, "rename", real)
    (media.base / "base-20260830T120000Z" / "backup_label").write_text("changed")
    with pytest.raises(retention.Refused, match="protected backup changed"):
        apply(media)
    assert (media.base / "base-20260815T000000Z").is_dir()


def test_metadata_digest_matches_external_sha256sum(media):
    item = media.selected()
    directory = media.base / item["name"]
    raw = subprocess.check_output(["sha256sum", *retention.FIELDS], cwd=directory)
    assert hashlib.sha256(raw).hexdigest() == item["metadata_sha256"]


def test_worker_lock_survives_parent_death(media, tmp_path):
    ready = tmp_path / "worker.ready"
    command = (f'. "{ROOT}/scripts/sentinel-backup-media-lock.sh"; '
               f'sentinel_media_lock "{media.base}" shared; '
               f'sleep 30 & child=$!; echo "$child" > "{ready}"; wait')
    parent = subprocess.Popen(["sh", "-ceu", command])
    child = None
    try:
        until = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < until:
            time.sleep(.01)
        assert ready.exists()
        child = int(ready.read_text())
        parent.kill()
        parent.wait(timeout=5)
        with pytest.raises(BlockingIOError):
            with retention.media_lock(media.base):
                pytest.fail("lost-worker lock was not inherited")
    finally:
        if child:
            os.kill(child, signal.SIGKILL)
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)
    until = time.monotonic() + 5
    while True:
        try:
            with retention.media_lock(media.base):
                break
        except BlockingIOError:
            assert time.monotonic() < until
            time.sleep(.01)


class Boundary:
    """Only process/provider boundaries are doubled; production policy executes."""
    def __init__(self):
        self.name = "base-20260919T120000Z"
        self.calls = []
        self.restored = False
        self.fail = None
        self.old = False
        self.selected_override = None

    def selected(self):
        return {"name": self.selected_override or self.name, "metadata_sha256": "a" * 64,
                "timestamp": NOW - (50000 if self.old else 0),
                "ranges": [{"timeline": 1, "start": 10 * SEGMENT, "end": 11 * SEGMENT}],
                "marker": "sentinel-backup-20260919T120000Z-42", "target_lsn": "0/D000000"}

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        joined = " ".join(command)
        if self.fail and self.fail in joined:
            raise coordinator.Refused("injected boundary failure")
        if command == ["git", "rev-parse", "HEAD"]:
            return "f" * 40
        if command[:3] == ["git", "status", "--porcelain"]:
            return ""
        if command[:3] == ["docker", "image", "inspect"]:
            return "f" * 40
        if command[:3] in (["docker", "volume", "ls"], ["docker", "network", "ls"]):
            return ""
        if "json_build_object" in joined:
            return json.dumps({"system_id": SYSTEM, "now": NOW, "timeline": "00000001",
                               "lsn": "0/D000000", "segment_size": SEGMENT})
        if "SELECT proof::text" in joined:
            return json.dumps(receipt(self.selected())) if self.restored else ""
        if "sentinel.backup_retention" in command:
            if "observe" in command:
                return json.dumps(self.selected())
            request = json.loads(kwargs["stdin"])
            retention.valid_receipt(request["receipt"], self.selected(), SYSTEM, IMAGE)
            return '{"retention_ready":true}'
        if command[:2] == ["bash", "scripts/sentinel-base-backup.sh"]:
            self.old = False
            return "verified_base_backup:/media/base/" + self.name
        if command[:2] == ["bash", "scripts/sentinel-restore-drill.sh"]:
            assert command == ["bash", "scripts/sentinel-restore-drill.sh", "--backup", "/media/base/" + self.name]
            self.restored = True
            return "full restore succeeded"
        if command[:2] == ["bash", "scripts/sentinel-backup-status.sh"]:
            assert command[-1] == "/media/base/" + self.name
            return "backup_ready:true"
        raise AssertionError("unmodeled command: " + repr(command))


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(coordinator, "ROOT", tmp_path)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_REF", IMAGE)
    return Boundary()


def test_production_tick_renews_verifies_restores_then_retains_and_restarts(boundary):
    boundary.old = True
    assert coordinator.tick("/media", boundary)["retention_ready"]
    calls = [" ".join(call) for call in boundary.calls]
    create = next(i for i, call in enumerate(calls) if "scripts/sentinel-base-backup.sh" in call)
    verify = next(i for i, call in enumerate(calls) if "scripts/sentinel-backup-status.sh" in call)
    restore = next(i for i, call in enumerate(calls) if "scripts/sentinel-restore-drill.sh" in call)
    delete = next(i for i, call in enumerate(calls) if "sentinel.backup_retention retain" in call)
    assert create < verify < restore < delete
    boundary.calls.clear()
    assert coordinator.tick("/media", boundary)["retention_ready"]
    assert not any("scripts/sentinel-base-backup.sh" in call or "scripts/sentinel-restore-drill.sh" in call
                   for call in boundary.calls)


@pytest.mark.parametrize("failure", ["scripts/sentinel-base-backup.sh", "scripts/sentinel-backup-status.sh",
                                     "scripts/sentinel-restore-drill.sh", "SELECT proof::text"])
def test_failed_boundary_never_reaches_retention(boundary, failure):
    boundary.old = True
    boundary.fail = failure
    with pytest.raises(coordinator.Refused):
        coordinator.tick("/media", boundary)
    assert not any("retain" in call for call in boundary.calls)


def test_successful_restore_without_durable_receipt_refuses(boundary):
    real = boundary.__call__
    def lost_receipt(command, **kwargs):
        result = real(command, **kwargs)
        return "" if "SELECT proof::text" in " ".join(command) else result
    with pytest.raises(coordinator.Refused, match="without matching durable evidence"):
        coordinator.tick("/media", lost_receipt)
    assert not any("retain" in call for call in boundary.calls)


@pytest.mark.parametrize("segments,due", [(14, False), (15, True), (16, True)])
def test_proactive_wal_boundary_is_independent_of_age(boundary, segments, due):
    item = boundary.selected()
    observation = {"now": NOW, "timeline": "00000001", "segment_size": SEGMENT,
                   "lsn": position(10 + segments)}
    assert coordinator.renewal_due(item, observation) is due


def test_timeline_advance_renews_and_regression_refuses(boundary):
    observation = {"now": NOW, "timeline": "00000002", "segment_size": SEGMENT, "lsn": "0/D000000"}
    assert coordinator.renewal_due(boundary.selected(), observation)
    observation["timeline"] = "00000000"
    with pytest.raises(coordinator.Refused, match="regressed"):
        coordinator.renewal_due(boundary.selected(), observation)


def test_selected_historical_generation_is_never_pruned(media):
    select(media.base.parent, "base-20260815T000000Z")
    result = apply(media)
    assert "base-20260815T000000Z" in result["kept"]
    assert result["wal_floor_segment"] == 100


def test_successor_identity_mismatch_refuses_before_status_or_retention(boundary):
    boundary.old = True
    boundary.selected_override = "base-20260919T110000Z"
    with pytest.raises(coordinator.Refused, match="successor differs"):
        coordinator.tick("/media", boundary)
    assert not any("scripts/sentinel-backup-status.sh" in call or "retain" in call
                   for call in boundary.calls)


def test_reaper_keeps_active_recent_foreign_and_unlabeled_resources():
    old = "sentinel-restore-drill-20260918T120000Z-42-" + "a" * 32
    recent = "sentinel-restore-drill-20260919T113000Z-42-" + "b" * 32
    active = "sentinel-restore-drill-20260918T120000Z-43-" + "c" * 32
    removed = []
    def runner(command, **_):
        kind = command[1]
        if command[1:3] == ["volume", "ls"]:
            return "\n".join([old, recent, active])
        if command[1:3] == ["network", "ls"]:
            return old
        if command[2] == "inspect":
            name = command[-1]
            return json.dumps({"Name": name, "Labels": {"sentinel.restore-drill": "v1"},
                               "CreatedAt" if kind == "volume" else "Created":
                                   "2026-09-19T11:30:00.123456789Z" if name == recent else "2026-09-18T12:00:00.987654321Z",
                               "Containers": {"active": {}} if kind == "network" else None})
        if command[1] == "ps":
            return "running-container" if "volume=" + active in command else ""
        if command[2] == "rm":
            removed.append((kind, command[-1]))
            return ""
        raise AssertionError(command)
    assert coordinator.reap_restore_resources(NOW, runner) == 1
    assert removed == [("volume", old)]
    def changed_label(command, **kwargs):
        raw = runner(command, **kwargs)
        if command[2] == "inspect":
            value = json.loads(raw)
            value["Labels"] = {}
            return json.dumps(value)
        return raw
    removed.clear()
    with pytest.raises(coordinator.Refused, match="identity changed"):
        coordinator.reap_restore_resources(NOW, changed_label)
    assert removed == []


def test_bounds_are_checked_before_deletion(media, monkeypatch):
    monkeypatch.setattr(retention, "MAX_BASES", 3)
    original, reads = retention.metadata, []
    def counted(*args):
        reads.append(args[1])
        return original(*args)
    monkeypatch.setattr(retention, "metadata", counted)
    with pytest.raises(retention.Refused):
        apply(media)
    assert len(reads) <= 4, "inventory ceiling must stop reads before spending the full scan budget"
    assert (media.base / "base-20260815T000000Z").is_dir()
    assert not (media.base / retention.JOURNAL).exists()


def test_renewal_refuses_future_clock_and_regressed_wal(boundary):
    item = boundary.selected()
    observation = {"now": NOW - 1, "timeline": "00000001", "lsn": "0/D000000", "segment_size": SEGMENT}
    with pytest.raises(coordinator.Refused, match="future-dated"):
        coordinator.renewal_due(item, observation)
    observation.update(now=NOW, lsn="0/1000000")
    with pytest.raises(coordinator.Refused, match="WAL regressed"):
        coordinator.renewal_due(item, observation)


def test_journal_clock_regression_preserves_obsolete_and_protected_bases(media, monkeypatch):
    real = retention.os.rename
    monkeypatch.setattr(retention.os, "rename", lambda *_: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        retention.retain(media, receipt(media.selected()), IMAGE, NOW + 600, SEGMENT)
    monkeypatch.setattr(retention.os, "rename", real)
    with pytest.raises(retention.Refused, match="journal clock regressed"):
        apply(media)
    assert len(media.inventory()) == 72


def test_private_wal_alias_refuses_before_any_base_deletion(media):
    outside = media.base.parent / "untouched"
    outside.write_bytes(b"outside retained data")
    os.link(outside, media.wal / ("cluster-" + SYSTEM) / "000000010000000000000001")
    with pytest.raises(retention.Refused):
        apply(media)
    assert len(media.inventory()) == 72
    assert outside.read_bytes() == b"outside retained data"


def test_loop_has_one_owner_retries_failed_tick_and_releases_lock(tmp_path, monkeypatch):
    import types
    monkeypatch.setenv("SENTINEL_BASE_BACKUP_LOCK_ROOT", str(tmp_path))
    calls = []
    active = []
    def child(command, **kwargs):
        assert not active, "a second supervisor launched a concurrent tick"
        active.append(True)
        assert command == ["bash", "scripts/sentinel-backup-maintenance.sh"]
        assert len(kwargs["pass_fds"]) == 1
        os.fstat(kwargs["pass_fds"][0])
        assert coordinator.supervise() == 0
        active.clear()
        calls.append(command)
        return types.SimpleNamespace(returncode=4)
    def stop(delay):
        assert delay == 60
        raise KeyboardInterrupt()
    monkeypatch.setattr(coordinator.subprocess, "run", child)
    monkeypatch.setattr(coordinator.time, "sleep", stop)
    for _ in range(2):
        with pytest.raises(KeyboardInterrupt):
            coordinator.supervise()
    assert len(calls) == 2


def test_real_postgres_semantic_bootstrap_and_durable_receipt_query(media):
    import psycopg
    from psycopg.types.json import Jsonb
    from tests.support.postgres import _EphemeralPostgres
    from sentinel import schema, restore_validation
    from sentinel.feed import store

    server = _EphemeralPostgres()
    try:
        server.start()
        with psycopg.connect(server.sync_dsn) as conn:
            schema.ensure_schema(conn)
            store.migrate_schema(conn)
            report = restore_validation.validate_restored_database(conn)
            assert report["transaction_read_only"] is True
            assert report["command_count"] == 0
            assert report["account_bound"] is False
        item = media.selected()
        proof = receipt(item)
        with psycopg.connect(server.sync_dsn) as conn:
            conn.execute("""WITH evidence AS (SELECT %s::jsonb AS proof)
                INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof)
                SELECT 'RESTORE_DRILL',encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof
                FROM evidence""", (Jsonb(proof),))
            conn.commit()
            def database_boundary(command, **_):
                assert command[:2] == ["docker", "compose"]
                row = conn.execute(command[-1]).fetchone()
                return row[0] if row else ""
            observation = {"system_id": SYSTEM}
            assert coordinator.receipt_for(item, observation, IMAGE, database_boundary) == proof
            assert coordinator.receipt_for(item, observation, "sha256:" + "e" * 64, database_boundary) is None
    finally:
        server.stop()
