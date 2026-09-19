from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

import pytest

from lab import ROOT, SYSTEM_ID, wal_name


def _write_checksum(path: Path) -> None:
    path.with_name(path.name + ".sha256").write_text(
        f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()}\n")


class ShellLab:
    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "repo"
        self.media = root / "media"
        self.base = self.media / "base"
        self.base.mkdir(parents=True)
        namespace = self.media / "wal" / f"cluster-{SYSTEM_ID}"
        namespace.mkdir(parents=True)
        wal = namespace / wal_name(3)
        with wal.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024)
        _write_checksum(wal)
        self.scripts = self.repo / "scripts"
        self.scripts.mkdir(parents=True)
        for name in ("sentinel-base-backup.sh", "sentinel-backup-status.sh",
                     "sentinel-backup-verify-chain.py", "sentinel-backup-verify-chain.sh",
                     "sentinel-restore-drill.sh", "sentinel_host_python.py",
                     "sentinel_backup_lock.py", "sentinel_lock_ownership.py",
                     "sentinel-backup-metadata-access.sh",
                     "sentinel-backup-publish-selection.sh",
                     "sentinel-backup-media-lock.sh", "sentinel-restore-worker.sh",
                     "sentinel-backup-archive-identity.sh", "sentinel-archive-wal.sh",
                     "sentinel-env.sh", "sentinel_env.py"):
            shutil.copy2(ROOT / "scripts" / name, self.scripts / name)
        # Separate mount-validation tests execute the real backup library.
        (self.scripts / "sentinel-backup-lib.sh").write_text(
            'sentinel_backup_root() { printf "%s\\n" "$BACKUP_LAB_ROOT/media"; }\n')
        bin_path = root / "bin"
        bin_path.mkdir()
        adapter = Path(__file__).with_name("command_adapter.py").read_text()
        adapter = adapter.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1)
        for command in ("docker", "psql", "pg_basebackup", "pg_verifybackup", "date", "sleep", "id", "chown", "stat", "docker-entrypoint.sh"):
            path = bin_path / command
            path.write_text(adapter)
            path.chmod(0o755)
        self.env = {"PATH": f"{bin_path}:{os.environ['PATH']}", "LANG": "C",
                    "BACKUP_LAB_ROOT": str(root), "SENTINEL_HOST_PYTHON": sys.executable,
                    "PYTHONPATH": str(ROOT), "SENTINEL_BACKUP_DIR": str(self.media),
                    "SENTINEL_POSTGRES_PASSWORD": "synthetic-only",
                    "SENTINEL_PUBLICATION_RECEIPT_KEY":
                        "synthetic-backup-lab-receipt-key-0123456789abcdef",
                    "POSTGRES_PASSWORD": "synthetic-only"}

    @property
    def namespace(self):
        return self.media / "wal" / f"cluster-{SYSTEM_ID}"

    def run(self, script="sentinel-base-backup.sh", *args):
        return subprocess.run(["bash", str(self.scripts / script), *args],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def events(self):
        return [json.loads(line)["stage"] for line in
                (self.root / "events.jsonl").read_text().splitlines()]


def _runtime_horizon_lab(tmp_path, count, timeline=1):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    base = lab.base / 'base-20260910T120000Z'
    manifest_path = base / 'backup_manifest'
    manifest = json.loads(manifest_path.read_text())
    manifest['WAL-Ranges'][-1]['Timeline'] = timeline
    manifest_path.write_text(json.dumps(manifest))
    os.utime(manifest_path, (1789041600, 1789041600))
    marker = base / 'sentinel-recovery-marker'
    marker.write_text(marker.read_text().replace(wal_name(3), wal_name(3, timeline)))
    checksum = hashlib.sha256(b'\0' * (16 * 1024 * 1024)).hexdigest()
    for index in range(3, 3 + count):
        path = lab.namespace / wal_name(index, timeline)
        with path.open('wb') as stream:
            stream.truncate(16 * 1024 * 1024)
        path.with_name(path.name + '.sha256').write_text('sha256=' + checksum + '\n')
    if timeline > 1:
        history = lab.namespace / f'{timeline:08X}.history'
        history.write_bytes(b'1\t0/03000000\tlocal geometry fixture\n')
        _write_checksum(history)
    lab.env['BACKUP_LAB_FRONTIER'] = wal_name(2 + count, timeline)
    return lab, base


@pytest.mark.parametrize('count,timeline,ready', [
    (64, 1, True), (65, 1, False), (63, 2, True), (64, 2, False),
])
def test_status_runtime_horizon_matches_independent_payload_budget(tmp_path, count, timeline, ready):
    from sentinel import backup_runtime_authority
    assert backup_runtime_authority.RUNTIME_MAX_VERIFIED_BYTES == 1024 ** 3
    assert backup_runtime_authority.RUNTIME_MAX_ARCHIVE_OBJECTS == 1024
    lab, base = _runtime_horizon_lab(tmp_path, count, timeline)
    # Independent accounting: actual retained history is part of the byte sum.
    history_bytes = ((lab.namespace / f'{timeline:08X}.history').stat().st_size
                     if timeline > 1 else 0)
    assert (count * 16 * 1024 * 1024 + history_bytes <= 1024 ** 3) is ready
    result = subprocess.run(['bash', str(lab.scripts / 'sentinel-backup-status.sh'),
        '--backup', str(base)], env=lab.env, capture_output=True, text=True, timeout=120)
    assert (result.returncode == 0) is ready, (result.stdout, result.stderr)
    assert ('backup_ready:true' in result.stdout) is ready
    if not ready:
        assert result.returncode == 4
        assert 'SENTINEL_BACKUP_STATUS_REASON=BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED' in result.stderr
        assert 'wal_chain_ready:true' not in result.stdout


@pytest.mark.parametrize('timeline,count', [(1, 1025), (2, 1024)])
def test_status_chain_object_bound_precedes_payload_reads(tmp_path, timeline, count):
    lab, base = _runtime_horizon_lab(tmp_path, 1, timeline)
    manifest = json.loads((base / 'backup_manifest').read_text())
    manifest['WAL-Ranges'][-1]['End-LSN'] = '0/0'
    (base / 'backup_manifest').write_text(json.dumps(manifest))
    # One-byte geometry isolates the object ceiling; it is not a real PG cluster.
    # Later objects are absent, so a late guard gives a missing-file error.
    end = f'{timeline:08X}00000000{count - 1:08X}'
    script = (lab.scripts / 'sentinel-backup-verify-chain.sh').read_text()
    script = script.replace('/sentinel-backup', str(lab.media))
    result = subprocess.run(['bash', '-s', '--', base.name, 'cluster-' + str(SYSTEM_ID),
        str(SYSTEM_ID), end, '1'], input=script, env=lab.env,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 5, (result.stdout, result.stderr)
    assert result.stdout.strip() == 'SENTINEL_BACKUP_CHAIN_REASON=RUNTIME_HORIZON_EXCEEDED'


def test_runtime_horizon_shell_uses_actual_postgres_manifest():
    import psycopg
    from tests.support.postgres import _EphemeralPostgres, _find_pg_bin

    server = _EphemeralPostgres()
    try:
        server.start()
        with psycopg.connect(server.sync_dsn, autocommit=True) as conn:
            conn.execute('CREATE ROLE sentinel WITH LOGIN SUPERUSER')
            conn.execute('CREATE DATABASE sentinel')
        lab, base = _runtime_horizon_lab(Path(server.datadir) / 'horizon-fixture', 65)
        # The real server must read this test-owned manifest. Production UID
        # grants and physical restore are owned by the separate physical harness.
        for directory in (lab.root, lab.media, lab.base, base):
            directory.chmod(0o711)
        (base / 'backup_manifest').chmod(0o644)
        source = (ROOT / 'scripts/sentinel-backup-verify-chain.sh').read_text()
        source = source.replace('/sentinel-backup', str(lab.media))
        env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': str(server.port),
               'PATH': str(Path(_find_pg_bin('psql')).parent) + ':' + os.environ['PATH']}
        for end, code in [('000000010000000000000042', 0),
                          ('000000010000000000000043', 5)]:
            result = subprocess.run(['bash', '-s', '--', base.name,
                'cluster-' + str(SYSTEM_ID), str(SYSTEM_ID), end, str(16 * 1024 * 1024)],
                input=source, env=env, capture_output=True, text=True, timeout=120)
            assert result.returncode == code, (result.stdout, result.stderr)
            if code == 0:
                assert 'wal_chain_ready:true' in result.stdout and 'segments=64' in result.stdout
            else:
                assert result.stdout.strip() == 'SENTINEL_BACKUP_CHAIN_REASON=RUNTIME_HORIZON_EXCEEDED'
    finally:
        server.stop()


@pytest.mark.parametrize('fault', ['none', 'verify', 'post-check'])
def test_go_runtime_horizon_renews_exact_successor_or_refuses(tmp_path, monkeypatch, fault):
    from scripts import sentinel_go_backup_refresh as refresh

    lab, base = _runtime_horizon_lab(tmp_path, 65)
    old = base.with_name('base-20260909T120000Z')
    base.rename(old)
    retained = (old / 'backup_manifest').read_bytes()
    checkpoint = lab.namespace / '000000010000000000000044'
    with checkpoint.open('wb') as stream:
        stream.truncate(16 * 1024 * 1024)
    _write_checksum(checkpoint)
    commit, token = 'a' * 40, 'b' * 64
    monkeypatch.setitem(refresh.phase._PHASE, 'certified', True)
    monkeypatch.setattr(refresh.go_lock, 'lifecycle_lock_is_held', lambda env=None: True)
    monkeypatch.setattr(refresh.go_lock, 'current_run_token', lambda env=None: token)
    calls = []

    class Runner:
        def run(self, argv, *, env=None):
            calls.append(tuple(argv))
            if argv[0] == 'git':
                # Separate existing process tests own checkout/certification gates.
                out = commit + '\n' if argv[1] == 'rev-parse' else ''
                return subprocess.CompletedProcess(argv, 0, out, '')
            assert not any(key.startswith(('ALPACA_', 'APCA_')) for key in env)
            assert argv[0] == 'bash'
            if argv[1] == 'scripts/sentinel-base-backup.sh':
                lab.env.update(BACKUP_LAB_CHECKPOINT_WAL=checkpoint.name,
                    BACKUP_LAB_CHECKPOINT_LSN='0/44000040',
                    BACKUP_LAB_FRONTIER=checkpoint.name)
                if fault == 'verify':
                    lab.env['BACKUP_LAB_FAULT'] = 'base-verify:before'
            if len(argv) > 2:
                assert argv[2:] == ['--backup', str(base)]
                if fault == 'post-check':
                    checkpoint.with_name(checkpoint.name + '.sha256').unlink()
            completed = subprocess.run(['bash', str(lab.repo / argv[1]), *argv[2:]],
                env=lab.env, capture_output=True, text=True, timeout=120)
            if argv[1] == 'scripts/sentinel-base-backup.sh' and completed.returncode == 0:
                os.utime(base / 'backup_manifest', (1789041600, 1789041600))
            return completed

    env = {**lab.env, 'ALPACA_API_KEY': 'synthetic-not-a-credential',
           refresh.go_lock.RUN_TOKEN_ENV: token}
    if fault == 'none':
        result = refresh.ensure_recent_verified_base_backup(Runner(), env=env, commit=commit)
        assert result.refreshed and result.post_refresh_exact_path_verified
        assert result.reason_code == 'BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED'
        assert result.backup_path == str(base)
        # Repeat from a fresh runner: the new intact horizon needs no renewal.
        again = refresh.ensure_recent_verified_base_backup(Runner(), env=env, commit=commit)
        assert not again.refreshed
    else:
        with pytest.raises(refresh.BackupRefreshRefused) as exc:
            refresh.ensure_recent_verified_base_backup(Runner(), env=env, commit=commit)
        expected = ('BASE_BACKUP_REFRESH_FAILED' if fault == 'verify'
                    else 'BASE_BACKUP_RECOVERY_EVIDENCE_INVALID')
        assert exc.value.reason_code == expected
    assert calls.count(('bash', 'scripts/sentinel-base-backup.sh')) == 1
    if fault != 'verify':
        assert ('bash', 'scripts/sentinel-backup-status.sh', '--backup', str(base)) in calls
    assert (old / 'backup_manifest').read_bytes() == retained
    assert (lab.namespace / '000000010000000000000043').is_file()


@pytest.mark.parametrize('exit_code,output', [
    (5, ''), (4, 'SENTINEL_BACKUP_CHAIN_REASON=RUNTIME_HORIZON_EXCEEDED\n'),
    (5, 'SENTINEL_BACKUP_CHAIN_REASON=RUNTIME_HORIZON_EXCEEDED\nextra\n'),
], ids=['missing-token', 'wrong-exit', 'extra-output'])
def test_status_horizon_classification_requires_exact_code_and_output(tmp_path, exit_code, output):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    base = lab.base / 'base-20260910T120000Z'
    os.utime(base / 'backup_manifest', (1789041600, 1789041600))
    # A failed dependency's exit status alone is not a renewal decision.
    checker = lab.scripts / 'sentinel-backup-verify-chain.sh'
    checker.write_text('printf %s ' + shlex.quote(output) + '\nexit ' + str(exit_code) + '\n')
    result = lab.run('sentinel-backup-status.sh', '--backup', str(base))
    assert result.returncode == 4
    assert 'SENTINEL_BACKUP_STATUS_REASON=BASE_BACKUP_RECOVERY_EVIDENCE_INVALID' in result.stderr
    assert 'SENTINEL_BACKUP_STATUS_REASON=BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED' not in result.stderr


def test_base_before_application_schema_defers_only_display_evidence(tmp_path):
    lab = ShellLab(tmp_path)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    assert "SENTINEL_BASE_BACKUP_EVIDENCE=DEFERRED_SCHEMA_NOT_INSTALLED" in result.stdout
    assert "verified_base_backup:" in result.stdout
    assert "evidence-insert" not in lab.events()


def test_verified_producer_publishes_exact_runtime_selection(tmp_path):
    lab = ShellLab(tmp_path)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    record = lab.base / f'.sentinel-runtime-base-{SYSTEM_ID}-v1'
    assert record.read_bytes() == (
        f'schema=sentinel.runtime-base/1\nsystem_identifier={SYSTEM_ID}\n'
        'base_backup=base-20260910T120000Z\n').encode()
    stages = lab.events()
    assert stages.index('base-verify') < stages.index('base-publish') < stages.index('selection-publish')
    assert record.stat().st_mode & 0o777 == 0o640
    assert not list(lab.base.glob('.sentinel-runtime-base-*.part-*'))


@pytest.mark.parametrize('point', ['before', 'after'])
def test_selection_publication_failure_preserves_a_complete_old_or_new_record(tmp_path, point):
    lab = ShellLab(tmp_path)
    record = lab.base / f'.sentinel-runtime-base-{SYSTEM_ID}-v1'
    old = (f'schema=sentinel.runtime-base/1\nsystem_identifier={SYSTEM_ID}\n'
           'base_backup=base-20260909T120000Z\n').encode()
    record.write_bytes(old)
    lab.env['BACKUP_LAB_FAULT'] = 'selection-publish:' + point
    result = lab.run()
    assert result.returncode != 0
    assert 'verified_base_backup:' not in result.stdout
    expected = old if point == 'before' else old.replace(b'20260909', b'20260910')
    assert record.read_bytes() == expected


def test_unknown_evidence_schema_is_not_treated_as_absent(tmp_path):
    lab = ShellLab(tmp_path)
    lab.env["BACKUP_LAB_EVIDENCE_QUERY_FAIL"] = "1"
    result = lab.run()
    assert result.returncode == 4
    assert "BASE_BACKUP_EVIDENCE_SCHEMA_UNAVAILABLE" in result.stderr
    assert "verified_base_backup:" not in result.stdout


@pytest.mark.parametrize("write_fails", [False, True])
def test_existing_evidence_table_requires_successful_insert(tmp_path, write_fails):
    lab = ShellLab(tmp_path)
    lab.env["BACKUP_LAB_EVIDENCE_TABLE"] = "present"
    if write_fails:
        lab.env["BACKUP_LAB_FAULT"] = "evidence-insert:before"
    result = lab.run()
    assert "evidence-insert" in lab.events()
    assert (result.returncode == 0) is not write_fails
    assert ("verified_base_backup:" in result.stdout) is not write_fails
    if write_fails:
        assert "SENTINEL_BASE_BACKUP_REASON=BASE_BACKUP_EVIDENCE_WRITE_FAILED" in result.stderr


@pytest.mark.parametrize("script", ["sentinel-base-backup.sh", "sentinel-backup-status.sh"])
def test_stale_running_archiver_refuses_before_copy_or_writes(tmp_path, script):
    lab = ShellLab(tmp_path)
    lab.env["BACKUP_LAB_ARCHIVER_DRIFT"] = "1"
    result = lab.run(script)
    assert result.returncode == 4, result.stderr
    assert "WAL_ARCHIVE_SCRIPT_DRIFT" in result.stderr
    assert "base-copy" not in lab.events()
    assert "marker-row" not in lab.events()


@pytest.mark.parametrize("stage", [
    "base-copy", "base-verify", "base-identity", "marker-row", "wal-proof",
    "marker-file", "metadata-access", "base-publish",
])
@pytest.mark.parametrize("moment", ["before", "after"])
def test_interrupted_backup_preserves_old_generation_and_retry(tmp_path, stage, moment):
    lab = ShellLab(tmp_path)
    old = lab.base / "base-20260909T120000Z"
    old.mkdir()
    (old / "retained").write_bytes(b"last-known-recovery-point")
    lab.env["BACKUP_LAB_FAULT"] = f"{stage}:{moment}"
    result = lab.run()
    assert result.returncode != 0, (stage, moment, result)
    assert "verified_base_backup:" not in result.stdout
    assert (old / "retained").read_bytes() == b"last-known-recovery-point"
    assert not list(lab.base.glob(".base-*.part-*"))
    del lab.env["BACKUP_LAB_FAULT"]
    final = lab.base / "base-20260910T120000Z"
    if final.exists():
        # Crash after promotion may leave a completed recovery point. The
        # producer must preserve it and refuse a same-name second publication.
        assert (final / "sentinel-recovery-marker").is_file()
        assert lab.run().returncode != 0
    else:
        retry = lab.run()
        assert retry.returncode == 0, retry.stderr
        assert f"verified_base_backup:{final}" in retry.stdout


def test_abandoned_staging_reaped_only_under_real_lock(tmp_path):
    lab = ShellLab(tmp_path)
    (lab.base / ".base-20260901T000000Z.part-123").mkdir()
    assert lab.run().returncode == 0
    assert not list(lab.base.glob(".base-*.part-*"))
    stages = lab.events()
    assert stages.index("base-copy") < stages.index("base-verify")
    assert stages.index("base-verify") < stages.index("marker-file") < stages.index("base-publish")


def test_restore_rechecks_manifest_after_storage_corruption(tmp_path):
    lab = ShellLab(tmp_path)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    final = lab.base / "base-20260910T120000Z"
    (final / "relation-data").write_bytes(b"bit rot after initial verification")
    result = lab.run("sentinel-restore-drill.sh", "--backup", str(final), "--physical-only")
    assert result.returncode != 0
    assert "manifest checksum mismatch" in result.stderr
    assert "restore-start" not in lab.events()
    assert "physical_wal_replay_ready:true" not in result.stdout
    assert "cleanup" in lab.events()


@pytest.mark.parametrize("fault", [
    "partial-marker", "missing-wal", "truncated-wal", "same-size-corrupt",
    "missing-checksum", "missing-label", "middle-gap", "future-mtime",
])
def test_status_never_claims_ready_for_invalid_recovery_point(tmp_path, fault):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    # Set the otherwise-valid manifest mtime to the deterministic current time.
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    wal = lab.namespace / wal_name(3)
    if fault == "partial-marker":
        (final / "sentinel-recovery-marker").write_text(f"system_identifier={SYSTEM_ID}\n")
    elif fault == "missing-wal":
        wal.unlink()
    elif fault == "truncated-wal":
        wal.write_bytes(b"truncated")
    elif fault == "same-size-corrupt":
        with wal.open("r+b") as stream:
            stream.seek(1024)
            stream.write(b"same-size-bit-rot")
    elif fault == "missing-checksum":
        wal.with_name(wal.name + ".sha256").unlink()
    elif fault == "missing-label":
        (final / "backup_label").unlink()
    elif fault == "middle-gap":
        manifest_path = final / "backup_manifest"
        manifest = json.loads(manifest_path.read_text())
        manifest["WAL-Ranges"][-1]["End-LSN"] = "0/01000040"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True))
        os.utime(manifest_path, (1789041600, 1789041600))
        for index in (1, 2):
            extra = lab.namespace / wal_name(index)
            with extra.open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
            _write_checksum(extra)
        (lab.namespace / wal_name(2)).unlink()
    else:
        os.utime(final / "backup_manifest", (1789041600 + 3600, 1789041600 + 3600))
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert result.returncode != 0, result.stdout
    assert "backup_ready:true" not in result.stdout


@pytest.mark.parametrize("last_ok,now,expected_ready", [
    ("1789041600.6", "1789041600.8", True),
    ("1789041600.1", "1789041600.0", False),
    ("1789041600.8", "1789041600.8", True),
])
def test_status_archive_clock_preserves_subsecond_order(tmp_path, last_ok, now, expected_ready):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    lab.env.update(BACKUP_LAB_LAST_OK=last_ok, BACKUP_LAB_DB_NOW=now)
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert (result.returncode == 0) == expected_ready, (result.stdout, result.stderr)
    if not expected_ready:
        assert "ARCHIVE_CLOCK_INVALID" in result.stderr


def test_status_resamples_clock_after_concurrent_manifest_publication(tmp_path):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041601, 1789041601))
    lab.env["BACKUP_LAB_PUBLISH_DURING_STATUS"] = "1"
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert result.returncode == 0, result.stderr
    assert "backup_ready:true" in result.stdout
    assert "wal_chain_ready:true" in result.stdout


@pytest.mark.parametrize("fault", ["missing-middle", "corrupt-middle", "missing-checksum"])
def test_status_proves_marker_through_later_frontier_and_repairs(tmp_path, fault):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    for index in (4, 5):
        path = lab.namespace / wal_name(index)
        with path.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024)
        _write_checksum(path)
    lab.env["BACKUP_LAB_FRONTIER"] = wal_name(5)
    middle = lab.namespace / wal_name(4)
    assert wal_name(3) < middle.name < wal_name(5)
    healthy = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert healthy.returncode == 0, healthy.stderr
    if fault == "missing-middle":
        middle.unlink()
    elif fault == "missing-checksum":
        middle.with_name(middle.name + ".sha256").unlink()
    else:
        with middle.open("r+b") as stream:
            stream.seek(4096)
            stream.write(b"SAME-SIZE-BIT-ROT")
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert result.returncode != 0
    assert "backup_ready:true" not in result.stdout
    assert middle.name in result.stderr
    with middle.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024)
    _write_checksum(middle)
    repaired = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert repaired.returncode == 0, repaired.stderr
    assert "backup_ready:true" in repaired.stdout


@pytest.mark.parametrize("last_ok,last_fail,ready", [
    ("1789041600.1", "1789041600.2", False),
    ("1789041600.3", "1789041600.2", True),
])
def test_status_preserves_subsecond_archive_failure_order(tmp_path, last_ok, last_fail, ready):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    lab.env.update(BACKUP_LAB_LAST_OK=last_ok, BACKUP_LAB_LAST_FAIL=last_fail,
                   BACKUP_LAB_DB_NOW="1789041600.4")
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert (result.returncode == 0) == ready, (result.stdout, result.stderr)
    if not ready:
        assert "WAL_ARCHIVE_UNRESOLVED_FAILURE" in result.stderr


@pytest.mark.parametrize("maximum,age_hours,reason", [
    ("08", 7, None), ("08", 9, "WAL_ARCHIVE_STALE"),
    ("030", 29, None), ("9" * 25, 0, "CONFIGURATION_INVALID"),
])
def test_status_age_limit_is_bounded_decimal(tmp_path, maximum, age_hours, reason):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    observed = 1789041600 - age_hours * 3600
    os.utime(final / "backup_manifest", (observed, observed))
    lab.env.update(SENTINEL_BACKUP_MAX_AGE_HOURS=maximum, BACKUP_LAB_LAST_OK=str(observed))
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert (result.returncode == 0) == (reason is None), (result.stdout, result.stderr)
    if reason:
        assert reason in result.stderr
    else:
        assert result.stderr == ""
