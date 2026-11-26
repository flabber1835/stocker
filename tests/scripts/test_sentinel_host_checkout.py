"""The host materializes an exact routine checkout without the filing archive."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.sentinel_local_delivery import checkout, model, qualification


SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def git(directory, *args):
    return subprocess.check_output(['git', '-C', str(directory), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    git(source, 'init', '-q')
    git(source, 'config', 'user.name', 'Checkout Test')
    git(source, 'config', 'user.email', 'checkout@example.invalid')
    for name, content in (
        ('sentinel/decision.py', 'value = 1\n'),
        ('tests/fixture.txt', 'fixture\n'),
        ('sec-filings/filing.zip', 'historical\n'),
        ('other/sec-filings/fixture.txt', 'nested fixture\n'),
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    git(source, 'add', '.')
    git(source, 'commit', '-qm', 'fixture')
    return source


def test_create_never_materializes_filings_and_keeps_exact_tree(repository, tmp_path, monkeypatch):
    target = tmp_path / 'qualification tree'
    revision = git(repository, 'rev-parse', 'HEAD')
    branch = 'codex/test-qualification'
    run_git = checkout._git
    after_add = []

    def observe(directory, *args):
        value = run_git(directory, *args)
        if args[:2] == ('worktree', 'add'):
            after_add.append(checkout.has_filing_archive(target))
        return value

    monkeypatch.setattr(checkout, '_git', observe)
    assert checkout.main(['create', '--repository', str(repository), '--worktree', str(target),
                          '--branch', branch, '--revision', revision]) == 0
    assert after_add == [False]
    assert git(target, 'rev-parse', 'HEAD') == revision
    assert git(target, 'rev-parse', 'HEAD^{tree}') == git(repository, 'rev-parse', 'HEAD^{tree}')
    assert git(target, 'branch', '--show-current') == branch
    assert git(target, 'status', '--porcelain') == ''
    assert git(target, 'ls-files', '-v', '--', 'sec-filings/') == 'S sec-filings/filing.zip'
    assert not checkout.has_filing_archive(target)
    assert (target / 'sentinel/decision.py').is_file()
    assert (target / 'tests/fixture.txt').is_file()
    assert (target / 'other/sec-filings/fixture.txt').is_file()
    assert (repository / 'sec-filings/filing.zip').is_file()
    assert git(repository, 'status', '--porcelain') == ''


def test_create_refuses_an_existing_destination(repository, tmp_path):
    target = tmp_path / 'existing'
    target.mkdir()
    payload = target / 'retain.txt'
    payload.write_text('retain', encoding='utf-8')
    with pytest.raises(checkout.CheckoutRefused, match='already exists'):
        checkout.create_worktree(repository, target, branch='codex/existing',
                                 revision=git(repository, 'rev-parse', 'HEAD'))
    assert payload.read_text(encoding='utf-8') == 'retain'
    assert git(repository, 'branch', '--list', 'codex/existing') == ''


def test_operational_qualification_checks_archive_presence_before_source_reads(repository):
    revision = git(repository, 'rev-parse', 'HEAD')

    def git_read(*args):
        pytest.fail(f'operational qualification continued to read Git with the archive present: {args}')

    with pytest.raises(model.DeliveryRefused, match='QUALIFICATION_HISTORICAL_FILINGS_PRESENT'):
        qualification.source_files(repository, scope=qualification.OPERATIONAL_SCOPE,
                                   predecessor_commit=revision, commit=revision, git_reader=git_read)
    assert 'sec-filings/filing.zip' in qualification.source_files(repository)


@pytest.mark.parametrize('launcher', ['sentinel-autonomous-deploy.sh', 'sentinel-go-validate.sh'])
def test_operational_launchers_refuse_full_checkout_before_environment_load(tmp_path, launcher):
    scripts = tmp_path / 'scripts'
    delivery = scripts / 'sentinel_local_delivery'
    delivery.mkdir(parents=True)
    shutil.copyfile(SCRIPTS / launcher, scripts / launcher)
    shutil.copyfile(SCRIPTS / 'sentinel_local_delivery/checkout.py', delivery / 'checkout.py')
    (scripts / 'sentinel_host_python.py').write_text('pass\n', encoding='utf-8')
    (scripts / 'sentinel-env.sh').write_text('exit 91\n', encoding='utf-8')
    (tmp_path / 'sec-filings').mkdir()
    result = subprocess.run(['bash', str(scripts / launcher)], text=True, capture_output=True,
                            env=dict(os.environ, SENTINEL_HOST_PYTHON=sys.executable,
                                     SENTINEL_GO_LOCK_HELD='1'), timeout=10)
    assert result.returncode == 2
    assert 'Historical SEC filings are present' in result.stderr
