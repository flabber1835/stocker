"""Only pre-mutation backup contention permits an exact CLI step retry."""

import asyncio
from inspect import isawaitable

import psycopg
import pytest

from sentinel import automation_runtime, backup_runtime_authority as backup, binding, paper, schema
from sentinel.activation_backup_protocol import EXIT_BACKUP_PROOF_BUSY, backup_proof_busy_record
from sentinel.cli import _shared, authority, automation, main, paper as paper_cli
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.execution import journal
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope='module')
def postgres():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.mark.parametrize('proof_number', [1, 2])
def test_only_opted_in_writer_entry_translates_busy_and_releases_lock(postgres, monkeypatch, proof_number):
    busy = backup.BackupIntegrityBusy('exact proof owner is still active')
    proofs = []

    def require(conn, *, operation, allow_continuity):
        assert operation == 'plan/execution writer mutation'
        assert allow_continuity is True
        proofs.append(conn)
        if len(proofs) == proof_number:
            raise busy

    monkeypatch.setattr(backup, 'require', require)
    for retry in (False, True):
        proofs.clear()
        with psycopg.connect(postgres.sync_dsn) as conn, psycopg.connect(postgres.sync_dsn) as peer:
            expected = journal.ActivationBackupEntryBusy if retry else type(busy)
            with pytest.raises(expected) as failure:
                with journal.writer_lock(conn, activation_backup_retry=retry):
                    pytest.fail('busy entry admitted the writer body')
            if retry:
                assert type(failure.value) is journal.ActivationBackupEntryBusy
                assert failure.value.__cause__ is busy
            else:
                assert failure.value is busy
            assert proofs == [conn] * proof_number
            assert peer.execute('SELECT pg_try_advisory_lock(%s)', (journal.WRITER_LOCK_KEY,)).fetchone() == (True,)


def test_busy_after_entry_preserves_committed_work_and_never_certifies_a_retry(postgres, monkeypatch):
    monkeypatch.setattr(backup, 'require', lambda *args, **kwargs: None)
    busy = backup.BackupIntegrityBusy('later proof is busy')
    with psycopg.connect(postgres.sync_dsn) as conn:
        conn.execute('CREATE TEMP TABLE retained_activation_work (sequence integer)')
        conn.commit()
        with pytest.raises(backup.BackupIntegrityBusy) as failure:
            with journal.writer_lock(conn, activation_backup_retry=True):
                conn.execute('INSERT INTO retained_activation_work VALUES (1)')
                conn.commit()
                conn.execute('INSERT INTO retained_activation_work VALUES (2)')
                raise busy
        assert failure.value is busy
        assert conn.execute('SELECT sequence FROM retained_activation_work').fetchall() == [(1,)]


@pytest.mark.parametrize('retry', [False, True])
def test_first_preparation_proof_keeps_the_default_refusal_and_can_opt_in(monkeypatch, retry):
    busy = backup.BackupIntegrityBusy('proof is busy before preparation')

    def require(_conn, *, operation, allow_continuity):
        assert operation == 'paper plan preparation' and allow_continuity is True
        raise busy

    monkeypatch.setattr(backup, 'require', require)
    expected = journal.ActivationBackupEntryBusy if retry else paper.PaperRetryableRefused
    with pytest.raises(expected) as failure:
        asyncio.run(paper.prepare_paper_plan(conn=object(), broker=object(), base_url=DEFAULT_BASE_URL,
            through='2026-11-16', activation_backup_retry=retry))
    assert type(failure.value) is expected
    assert failure.value.__cause__ is busy


@pytest.fixture
def authorized_cli(postgres, monkeypatch, tmp_path):
    for module in (_shared, authority, automation, paper_cli):
        monkeypatch.setattr(module, 'require_authorized_runtime', lambda command: None)
    monkeypatch.setattr(store, 'connect', lambda _url: psycopg.connect(postgres.sync_dsn))
    monkeypatch.setattr(store, 'require_feed_schema', lambda conn: None)
    monkeypatch.setattr(schema, 'require_runtime_schema', lambda conn: None)
    monkeypatch.setattr(automation_runtime, 'config_from_env', lambda: object())
    monkeypatch.setattr(paper, 'build_security_resolver', lambda conn, session: None)
    monkeypatch.setattr(paper_cli, 'build_execution_broker', lambda config, **kwargs: object())
    return SentinelConfig(alpaca_key='PKFIXTURE', alpaca_secret='fixture', base_url=DEFAULT_BASE_URL,
                          state_dir=tmp_path, max_cycles=1, poll_seconds=0, database_url='postgresql://fixture/unused')


def _call(authorized_cli, command, tmp_path):
    certificate = 'c' * 64
    predecessor = 'b' * 64
    declared_subject = ['--confirm-paper-account', 'PAFIXTURE', '--confirm-deployment-id', 'fixture']
    reasons = ['--actor', 'fixture', '--reason', 'qualification']
    staged_file = tmp_path / 'certificate.json'
    staged_file.write_text('{}')
    args = {
        'install-system-certificate': [
            '--certificate', str(staged_file), '--confirm-certificate-sha256', certificate,
            '--confirm-install-alpaca-paper-execution-certificate', '--reason', 'qualification'],
        'activate-system-certificate': [
            *declared_subject, '--certificate-sha256', certificate,
            '--confirm-activate-alpaca-paper-execution-certificate', '--reason', 'qualification'],
        'rotate-system-certificate': [
            *declared_subject, '--certificate-sha256', certificate, '--confirm-supersedes-certificate-sha256', predecessor,
            '--confirm-rotate-alpaca-paper-execution-certificate', '--reason', 'qualification'],
        'prepare-paper-plan': ['--through', '2026-11-16', '--expect-account', 'PAFIXTURE'],
        'activate-paper-automation': [
            *declared_subject, *reasons, '--confirm-certificate-sha256', certificate,
            '--confirm-old-writer-fenced', '--confirm-enable-unattended-alpaca-paper-automation'],
        'release-paper-automation-kill-switch': [
            *declared_subject, *reasons, '--confirm-certificate-sha256', certificate,
            '--confirm-release-unattended-paper-kill-switch'],
    }
    handlers = {
        'install-system-certificate': authority._install_system_certificate,
        'activate-system-certificate': authority._activate_system_certificate,
        'rotate-system-certificate': authority._activate_system_certificate,
        'prepare-paper-plan': paper_cli._prepare_paper_plan,
        'activate-paper-automation': automation._activate_paper_automation,
        'release-paper-automation-kill-switch': automation._release_paper_automation_kill,
    }
    value = handlers[command](authorized_cli, main.build_parser().parse_args([command, *args[command]]))
    return asyncio.run(value) if isawaitable(value) else value


@pytest.mark.parametrize('command', [
    'install-system-certificate', 'activate-system-certificate', 'rotate-system-certificate',
    'prepare-paper-plan', 'activate-paper-automation', 'release-paper-automation-kill-switch',
])
def test_authorized_cli_emits_the_exact_command_bound_entry_result(authorized_cli, tmp_path, monkeypatch, capsys, command):
    def require(*args, **kwargs):
        raise backup.BackupIntegrityBusy('proof owner is active')

    monkeypatch.setattr(backup, 'require', require)
    assert _call(authorized_cli, command, tmp_path) == EXIT_BACKUP_PROOF_BUSY
    captured = capsys.readouterr()
    assert captured.out == backup_proof_busy_record(command) + '\n'
    assert captured.err == ''


@pytest.mark.parametrize('entry_failure', [True, False])
def test_generic_backup_failure_and_later_busy_keep_cli_refusal(authorized_cli, tmp_path, monkeypatch, capsys,
                                                              entry_failure):
    def unavailable(*args, **kwargs):
        raise backup.BackupRuntimeUnavailable('media is unavailable')

    def body_busy(_conn):
        raise backup.BackupIntegrityBusy('later proof is busy')

    monkeypatch.setattr(backup, 'require', unavailable if entry_failure else lambda *args, **kwargs: None)
    monkeypatch.setattr(binding, 'require', body_busy)
    assert _call(authorized_cli, 'install-system-certificate', tmp_path) == _shared.EXIT_NOT_ESTABLISHED
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ('REFUSED: media is unavailable\n' if entry_failure else 'REFUSED: later proof is busy\n')
