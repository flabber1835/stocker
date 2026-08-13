from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def _read(relative: str) -> str:
    return (ROOT / relative).read_text()


def test_backup_overlay_archives_wal_to_an_operator_target():
    text = _read("docker-compose.sentinel-backup.yml")
    assert "SENTINEL_BACKUP_DIR:?" in text
    assert "archive_mode=on" in text
    assert "archive_command=" in text
    assert "test -f /sentinel-backup/wal/%f || cp" in text
    assert "/sentinel-backup/wal" in text
    assert "/sentinel-backup/base" in text


def test_base_backup_is_physical_streamed_and_verified_before_promotion():
    text = _read("scripts/sentinel-base-backup.sh")
    assert "pg_basebackup" in text and "-Xs" in text
    assert "pg_verifybackup" in text
    assert text.index("pg_verifybackup") < text.index('mv "/sentinel-backup/base/')
    assert "SHOW archive_mode" in text


def test_restore_drill_is_isolated_and_cleans_only_its_unique_objects():
    text = _read("scripts/sentinel-restore-drill.sh")
    assert text.count("--network none") >= 2
    assert ":/archive:ro" in text
    assert 'VOLUME="sentinel-restore-drill-$TOKEN"' in text
    assert 'CONTAINER="sentinel-restore-drill-$TOKEN"' in text
    assert 'docker volume rm "$VOLUME"' in text
    assert "sentinel_pgdata" not in text
    assert "sentinel_processed_sessions" in text
    assert "sentinel_backup_recovery_markers" in text
    assert "pg_last_wal_replay_lsn" in text
    assert "TARGET_LSN" in text
    assert "RAISE EXCEPTION" in text


def test_backup_status_enforces_a_bounded_age_without_pruning():
    text = _read("scripts/sentinel-backup-status.sh")
    assert "SENTINEL_BACKUP_MAX_AGE_HOURS" in text
    assert "pg_stat_archiver" in text
    assert "backup_ready:true" in text
    assert "archive_mode" in text
    assert "last_archived_time" in text
    assert "last_failed_time" in text
    assert "post-base recovery marker" in text
    assert " rm " not in text


def test_certification_refuses_without_backup_readiness():
    text = _read("scripts/sentinel-certify.sh")
    assert "SENTINEL_BACKUP_DIR is unset" in text
    assert "scripts/sentinel-backup-status.sh" in text
    assert text.index("scripts/sentinel-backup-status.sh") < text.index("TRUNCATE TABLE")


def test_backup_root_refuses_the_repository(tmp_path):
    # Linux is the certified/test-image host. Windows collection leaves this
    # process-level shell falsifier to that image.
    if os.name == "nt":
        return
    env = {**os.environ, "SENTINEL_BACKUP_DIR": str(ROOT)}
    result = subprocess.run(
        ["bash", "-c", ". scripts/sentinel-backup-lib.sh; sentinel_backup_root"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "protected local path" in result.stderr


def test_backup_root_accepts_an_explicit_dedicated_target(tmp_path):
    if os.name == "nt":
        return
    target = tmp_path / "second-target"
    (target / "wal").mkdir(parents=True)
    (target / "base").mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = info ]; then echo /unmounted-docker-root; exit 0; fi\n"
        "case \" $* \" in *' --entrypoint id '*) echo 999;; esac\n"
        "exit 0\n")
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SENTINEL_BACKUP_DIR": str(target),
        "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED": "1",
    }
    result = subprocess.run(
        ["bash", "-c", ". scripts/sentinel-backup-lib.sh; sentinel_backup_root"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(target.resolve())


def test_base_backup_requires_post_base_marker_wal_before_metadata():
    text = _read("scripts/sentinel-base-backup.sh")
    assert "sentinel_backup_recovery_markers" in text
    assert "pg_switch_wal" in text
    assert '"$BACKUP_ROOT/wal/$MARKER_WAL"' in text
    assert "sentinel-recovery-marker" in text


def test_supported_compose_wrapper_always_includes_backup_and_preserves_refusal():
    resolver = _read("scripts/sentinel-compose.sh")
    assert 'BACKUP="docker-compose.sentinel-backup.yml"' in resolver
    assert "sentinel_backup_root >/dev/null" in resolver
    assert 'exec docker compose "${COMPOSE_ARGS[@]}" "$@"' in resolver
    for relative in ("Makefile", "scripts/sentinel-certify.sh",
                     "scripts/sentinel-measure.sh",
                     "docs/sentinel-paper-activation.md"):
        assert "sentinel-compose.sh --run" in _read(relative), relative
