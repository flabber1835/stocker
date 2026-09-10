from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sentinel import backup_runtime_authority as authority
from sentinel import paper
from sentinel.feed import ingest_authority_impl as ingest_authority
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
