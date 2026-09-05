from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def _read(relative: str) -> str:
    return (ROOT / relative).read_text()


def _write_fake_backup_docker(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = info ]; then\n"
        "  printf '%s\\n' \"${FAKE_DOCKER_ROOT:-/unmounted-docker-root}\"\n"
        "  exit 0\n"
        "fi\n"
        "case \" $* \" in *' --entrypoint id '*) echo 999; exit 0;; esac\n"
        "mode=\n"
        "parent=\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    MODE=*) mode=\"${arg#MODE=}\";;\n"
        "    *:/probe) parent=\"${arg%:/probe}\";;\n"
        "  esac\n"
        "done\n"
        "if [ -n \"$mode\" ]; then\n"
        "  marker=\"$parent/.sentinel-independent-durable-target-v1\"\n"
        "  expected=sentinel-independent-durable-target-v1\n"
        "  if [ \"$mode\" = initialize ] && [ ! -e \"$marker\" ] && [ ! -L \"$marker\" ]; then\n"
        "    printf '%s\\n' \"$expected\" > \"$marker\" || exit 3\n"
        "    chmod 0444 \"$marker\" || exit 3\n"
        "  fi\n"
        "  if [ -L \"$marker\" ]; then echo INVALID_SYMLINK; exit 3; fi\n"
        "  if [ ! -e \"$marker\" ]; then echo MISSING; exit 4; fi\n"
        "  if [ ! -f \"$marker\" ] || [ ! -r \"$marker\" ]; then echo INVALID_TYPE; exit 3; fi\n"
        "  content=\"$(cat \"$marker\")\" || { echo INVALID_UNREADABLE; exit 3; }\n"
        "  if [ \"$content\" != \"$expected\" ]; then echo INVALID_CONTENT; exit 3; fi\n"
        "  echo VALID\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_backup_overlay_archives_wal_to_an_operator_target():
    text = _read("docker-compose.sentinel-backup.yml")
    assert "SENTINEL_BACKUP_DIR:?" in text
    assert "archive_mode=on" in text
    assert "archive_command=" in text
    assert "/usr/local/libexec/sentinel-archive-wal.sh" in text
    assert "test -f /sentinel-backup/wal/%f || cp" not in text
    assert "/sentinel-backup/wal" in text
    assert "/sentinel-backup/base" in text


def test_wal_archive_contract_requires_verified_atomic_durable_publication():
    text = _read("scripts/sentinel-archive-wal.sh")
    assert 'od -An -t u8 -j 24 -N 8 -- "$source_wal"' in text
    assert 'namespace_name="cluster-$system_id"' in text
    assert 'archive_dir="$archive_root/$namespace_name"' in text
    assert 'mktemp "$archive_dir/.${wal_name}.part.XXXXXX"' in text
    assert 'cmp -s -- "$source_wal" "$temporary"' in text
    assert 'sync "$temporary"' in text
    assert 'mv -T --no-clobber -- "$temporary" "$target"' in text
    assert 'sync "$archive_dir"' in text
    assert text.index('sync "$temporary"') < text.index("mv -T --no-clobber")
    assert text.index("mv -T --no-clobber") < text.rindex('sync "$archive_dir"')


def _fake_wal(path: Path, system_id: int, payload: bytes = b"sentinel") -> None:
    data = bytearray(4096)
    data[24:32] = int(system_id).to_bytes(8, byteorder=sys.byteorder, signed=False)
    data[64:64 + len(payload)] = payload
    path.write_bytes(data)


def _namespace(archive: Path, system_id: int) -> Path:
    return archive / f"cluster-{system_id}"


def _archive_wal(source: Path, archive: Path, name: str, *, env=None):
    marker = archive / ".sentinel-independent-durable-target-v1"
    marker.write_text("sentinel-independent-durable-target-v1", encoding="utf-8")
    return subprocess.run(
        ["sh", str(ROOT / "scripts/sentinel-archive-wal.sh"),
         str(source), name, str(archive)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_wal_archive_success_and_identical_retry_are_idempotent(tmp_path):
    if os.name == "nt":
        return
    archive = tmp_path / "wal"
    archive.mkdir()
    source = tmp_path / "source-wal"
    system_id = 7676888197645955109
    _fake_wal(source, system_id, b"complete")
    name = "000000010000000000000001"

    first = _archive_wal(source, archive, name)
    assert first.returncode == 0, first.stderr
    target = _namespace(archive, system_id) / name
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob(f".{name}.part.*"))
    inode = target.stat().st_ino

    retry = _archive_wal(source, archive, name)
    assert retry.returncode == 0, retry.stderr
    assert target.stat().st_ino == inode
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob(f".{name}.part.*"))


def test_two_clusters_may_archive_same_wal_filename_without_collision(tmp_path):
    if os.name == "nt":
        return
    archive = tmp_path / "wal"
    archive.mkdir()
    name = "000000010000000400000007"
    old_id = 7672154738690088997
    current_id = 7676888197645955109
    old = tmp_path / "old-cluster-wal"
    current = tmp_path / "current-cluster-wal"
    _fake_wal(old, old_id, b"old-history")
    _fake_wal(current, current_id, b"current-history")

    old_result = _archive_wal(old, archive, name)
    current_result = _archive_wal(current, archive, name)

    assert old_result.returncode == 0, old_result.stderr
    assert current_result.returncode == 0, current_result.stderr
    old_target = _namespace(archive, old_id) / name
    current_target = _namespace(archive, current_id) / name
    assert old_target.read_bytes() == old.read_bytes()
    assert current_target.read_bytes() == current.read_bytes()
    assert old_target.read_bytes() != current_target.read_bytes()
    assert not (archive / name).exists()


def test_wal_archive_refuses_partial_or_mismatched_final_within_one_cluster(tmp_path):
    if os.name == "nt":
        return
    system_id = 7676888197645955109
    source = tmp_path / "source-wal"
    _fake_wal(source, system_id, b"abcdefgh")
    name = "000000010000000000000002"

    for existing in (b"abc", b"abcdEfgh"):
        archive = tmp_path / f"wal-{len(existing)}-{existing.hex()}"
        archive.mkdir()
        marker = archive / ".sentinel-independent-durable-target-v1"
        marker.write_text("sentinel-independent-durable-target-v1", encoding="utf-8")
        namespace = _namespace(archive, system_id)
        namespace.mkdir(mode=0o700)
        target = namespace / name
        target.write_bytes(existing)
        result = _archive_wal(source, archive, name)
        assert result.returncode != 0
        assert "existing archive differs from source" in result.stderr
        assert target.read_bytes() == existing
        assert not list(namespace.glob(f".{name}.part.*"))


def test_wal_archive_copy_failure_leaves_no_final_or_temporary(tmp_path):
    if os.name == "nt":
        return
    archive = tmp_path / "wal"
    archive.mkdir()
    source = tmp_path / "source-wal"
    system_id = 7676888197645955109
    _fake_wal(source, system_id, b"complete source WAL")
    name = "000000010000000000000003"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_cp = fake_bin / "cp"
    fake_cp.write_text(
        "#!/bin/sh\n"
        "for destination do :; done\n"
        "printf partial > \"$destination\"\n"
        "exit 1\n"
    )
    fake_cp.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    result = _archive_wal(source, archive, name, env=env)
    namespace = _namespace(archive, system_id)
    assert result.returncode != 0
    assert "copy failed" in result.stderr
    assert not (namespace / name).exists()
    assert not list(namespace.glob(f".{name}.part.*"))


def test_wal_archive_file_fsync_failure_leaves_no_final(tmp_path):
    if os.name == "nt":
        return
    archive = tmp_path / "wal"
    archive.mkdir()
    source = tmp_path / "source-wal"
    system_id = 7676888197645955109
    _fake_wal(source, system_id, b"complete source WAL")
    name = "000000010000000000000004"
    namespace = _namespace(archive, system_id)
    namespace.mkdir(mode=0o700)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sync = fake_bin / "sync"
    fake_sync.write_text("#!/bin/sh\nexit 1\n")
    fake_sync.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    result = _archive_wal(source, archive, name, env=env)
    assert result.returncode != 0
    assert "could not fsync temporary archive" in result.stderr
    assert not (namespace / name).exists()
    assert not list(namespace.glob(f".{name}.part.*"))


def test_base_backup_is_physical_streamed_and_verified_before_promotion():
    text = _read("scripts/sentinel-base-backup.sh")
    assert "pg_basebackup" in text and "-Xs" in text
    assert "pg_verifybackup" in text
    assert "pg_control_system()" in text
    assert 'WAL_NAMESPACE="cluster-$SYSTEM_ID"' in text
    assert "schema=sentinel.base-backup-pitr/2" in text
    assert "system_identifier=%s" in text
    promotion = (
        'mv -T --no-clobber -- "/sentinel-backup/base/$staging" '
        '"/sentinel-backup/base/$final"')
    assert promotion in text
    assert text.index("pg_verifybackup") < text.index(promotion)
    assert 'sync -f /sentinel-backup/base' in text
    assert "SHOW archive_mode" in text


def test_restore_drill_is_isolated_and_cleans_only_its_unique_objects():
    text = _read("scripts/sentinel-restore-drill.sh")
    assert text.count("--network none") >= 1
    assert 'docker network create --internal "$NETWORK"' in text
    assert 'WAL_SOURCE="$BACKUP_ROOT/wal/cluster-$SYSTEM_ID"' in text
    assert 'WAL_SOURCE="$BACKUP_ROOT/wal"' in text
    assert '-v "$WAL_SOURCE:/archive:ro"' in text
    assert 'VOLUME="sentinel-restore-drill-$TOKEN"' in text
    assert 'CONTAINER="sentinel-restore-drill-$TOKEN"' in text
    assert 'NETWORK="sentinel-restore-drill-$TOKEN"' in text
    assert 'docker volume rm "$VOLUME"' in text
    assert 'docker network rm "$NETWORK"' in text
    assert "sentinel_pgdata" not in text
    assert "sentinel_processed_sessions" in text
    assert "sentinel_behavioral_schema_migrations" in text
    assert "sentinel_rollout_state" in text
    assert "sentinel_backup_recovery_markers" in text
    assert "pg_last_wal_replay_lsn" in text
    assert "TARGET_LSN" in text
    assert "recovery marker identity is malformed" in text
    assert "recovery marker LSN is malformed" in text
    assert "RAISE EXCEPTION" in text
    assert "pg_promote(true,60)" in text
    assert "SENTINEL_RUNTIME_IMAGE_REF" in text
    assert "sentinel.restore_validation" in text
    assert "--read-only --cap-drop ALL" in text
    assert "physical_wal_replay_ready:true" in text
    assert "restore_semantics_ready:true" in text


def test_backup_status_enforces_cluster_identity_age_and_no_pruning():
    text = _read("scripts/sentinel-backup-status.sh")
    assert "SENTINEL_BACKUP_MAX_AGE_HOURS" in text
    assert "pg_stat_archiver" in text
    assert "pg_control_system()" in text
    assert 'WAL_NAMESPACE="cluster-$SYSTEM_ID"' in text
    assert "backup_matches_current_cluster" in text
    assert "BASE_BACKUP_SYSTEM_ID_MISMATCH" in text
    assert "WAL_NAMESPACE_MISSING" in text
    assert "backup_ready:true" in text
    assert "archive_mode" in text
    assert "last_archived_time" in text
    assert "last_failed_time" in text
    assert "post-base recovery marker" in text
    assert " rm " not in text


def test_retired_in_trader_certification_refuses_before_any_mutation():
    text = _read("scripts/sentinel-certify.sh")
    assert "standalone historical certification system is not installed" in text
    assert "TRUNCATE TABLE" not in text
    assert "docker compose" not in text


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
    _write_fake_backup_docker(docker)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SENTINEL_BACKUP_DIR": str(target),
        "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED": "1",
    }
    result = subprocess.run(
        ["bash", "-c",
         ". scripts/sentinel-backup-lib.sh; "
         "sentinel_backup_root --initialize-markers >/dev/null; "
         "sentinel_backup_root"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(target.resolve())


def _backup_root_case(tmp_path, *, docker_root, root_device="10",
                      docker_device="20", attested=False):
    target = tmp_path / "target"
    (target / "wal").mkdir(parents=True)
    (target / "base").mkdir()
    fake_bin = tmp_path / "bin-case"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    _write_fake_backup_docker(docker)
    stat = fake_bin / "stat"
    stat.write_text(
        "#!/bin/sh\n"
        "case \"$3\" in \"$SENTINEL_BACKUP_DIR\") echo \"$FAKE_ROOT_DEVICE\";;"
        " *) echo \"$FAKE_DOCKER_DEVICE\";; esac\n")
    stat.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SENTINEL_BACKUP_DIR": str(target),
        "FAKE_DOCKER_ROOT": str(docker_root),
        "FAKE_ROOT_DEVICE": root_device,
        "FAKE_DOCKER_DEVICE": docker_device,
    }
    if attested:
        env["SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED"] = "1"
    return subprocess.run(
        ["bash", "-c",
         ". scripts/sentinel-backup-lib.sh; "
         "sentinel_backup_root --initialize-markers >/dev/null; "
         "sentinel_backup_root"],
        cwd=ROOT, env=env, capture_output=True, text=True)


def test_backup_root_absent_or_unreadable_fails_closed_without_attestation(
        tmp_path):
    if os.name == "nt":
        return
    absent = _backup_root_case(tmp_path / "absent",
                               docker_root=tmp_path / "missing")
    assert absent.returncode != 0 and "could not be traversed" in absent.stderr

    unreadable = tmp_path / "unreadable" / "docker-root"
    unreadable.parent.mkdir(parents=True)
    unreadable.write_text("not a traversable directory")
    refused = _backup_root_case(tmp_path / "protected", docker_root=unreadable)
    assert refused.returncode != 0 and "could not be traversed" in refused.stderr
    attested = _backup_root_case(
        tmp_path / "protected-attested", docker_root=unreadable, attested=True)
    assert attested.returncode == 0, attested.stderr


def test_backup_root_readable_device_and_attestation_matrix(tmp_path):
    if os.name == "nt":
        return
    docker_root = tmp_path / "docker-root"
    docker_root.mkdir()
    same = _backup_root_case(tmp_path / "same", docker_root=docker_root,
                             root_device="7", docker_device="7")
    assert same.returncode != 0 and "same device" in same.stderr

    independent = _backup_root_case(
        tmp_path / "independent", docker_root=docker_root,
        root_device="7", docker_device="8")
    assert independent.returncode == 0, independent.stderr

    attested = _backup_root_case(
        tmp_path / "attested", docker_root=docker_root,
        root_device="7", docker_device="7", attested=True)
    assert attested.returncode == 0, attested.stderr


def test_attestation_never_allows_a_path_inside_docker_root(tmp_path):
    if os.name == "nt":
        return
    docker_root = tmp_path / "docker-root"
    target = docker_root / "backups"
    (target / "wal").mkdir(parents=True)
    (target / "base").mkdir()
    fake_bin = tmp_path / "inside-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\nif [ \"$1\" = info ]; then echo \"$FAKE_DOCKER_ROOT\"; fi\n")
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", ". scripts/sentinel-backup-lib.sh; sentinel_backup_root"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
             "FAKE_DOCKER_ROOT": str(docker_root),
             "SENTINEL_BACKUP_DIR": str(target),
             "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED": "1"})
    assert result.returncode != 0
    assert "inside Docker's data root" in result.stderr


def test_base_backup_requires_post_base_marker_wal_before_metadata():
    text = _read("scripts/sentinel-base-backup.sh")
    assert "sentinel_backup_recovery_markers" in text
    assert "pg_switch_wal" in text
    wal_proof = 'test -f "/sentinel-backup/wal/$namespace/$wal"'
    metadata_publish = 'metadata="/sentinel-backup/base/$name/sentinel-recovery-marker"'
    assert wal_proof in text
    assert 'test -r "/sentinel-backup/wal/$namespace/$wal"' in text
    assert metadata_publish in text
    assert text.index(wal_proof) < text.index(metadata_publish)
    assert 'system_identifier=%s' in text
    assert 'sync "$metadata"' in text
    assert 'test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker"' in text


def test_supported_compose_wrapper_always_includes_backup_and_preserves_refusal():
    resolver = _read("scripts/sentinel-compose.sh")
    assert 'BACKUP="docker-compose.sentinel-backup.yml"' in resolver
    assert "sentinel_backup_root >/dev/null" in resolver
    assert 'exec docker compose "${COMPOSE_ARGS[@]}" "$@"' in resolver
    for relative in ("Makefile", "scripts/sentinel-measure.sh",
                     "docs/sentinel-paper-activation.md"):
        assert "sentinel-compose.sh --run" in _read(relative), relative
