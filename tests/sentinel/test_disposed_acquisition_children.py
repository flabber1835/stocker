"""Execute host-owned acquisition children without reusing disposed sessions."""
import ast
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import backup_guard, backup_runtime_authority, deployment_fence, retained_go, schema
from sentinel.feed import operational_snapshot, publication, rolling_go_inputs, rolling_jobs, store, writer_schedule


ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
OWNERS = {
    'source_final': ('sentinel_go_24x7_entry.py', '_PREPARATION_CODE'),
    'install_refresh': ('sentinel_install_source_refresh.py', 'CODE'),
    'direct_go': ('sentinel_go_validate.py', '_PREPARATION_CODE'),
}
NOW = datetime(2026, 10, 6, 4, 1, tzinfo=timezone.utc)
TARGET = '2026-10-05'


def child(owner):
    """Read each actual source-owned program, independent of installed overlays."""
    filename, name = OWNERS[owner]
    tree = ast.parse((ROOT / 'scripts' / filename).read_bytes(), feature_version=(3, 8))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    assert len(values) == 1
    value = values[0]
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
    assert value.func.attr == 'strip' and value.args == [] and value.keywords == []
    return ast.literal_eval(value.func.value).strip()


class Connection:
    def __init__(self):
        self.disposed = False
        self.closed = False
        self.prepared = False
        self.after_prepare = []

    def _use(self, operation):
        if self.prepared:
            self.after_prepare.append(operation)
        assert not self.disposed, 'disposed child connection reused'

    def rollback(self):
        self._use('rollback')

    def close(self):
        self._use('close')
        self.closed = True


def primary(kind):
    if kind == 'interrupt':
        return KeyboardInterrupt('original acquisition interruption')
    if kind == 'exit':
        return SystemExit('original acquisition exit')
    if kind == 'database':
        return psycopg.errors.QueryCanceled('original acquisition cancellation')
    if kind == 'horizon':
        error = backup_runtime_authority.BackupHorizonExceeded('original backup horizon')
        error.resume_job_id = '12f7a9c2-7bf5-41a9-9ad9-eead86e0d3d4'
        return error
    if kind == 'deadline':
        return rolling_jobs.JobDeadlineExceeded('original acquisition deadline')
    if kind == 'frontier':
        return rolling_go_inputs.RollingGoRefused('ROLLING_SOURCE_FINAL_TARGET_CHANGED')
    return RuntimeError('ordinary acquisition refusal')


def execute(monkeypatch, owner, *, error=None, disposed=False, closed=False, code=None):
    connection = Connection()
    noop = lambda *args, **kwargs: None
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'private-child-fixture')
    monkeypatch.setenv('SENTINEL_GO_PREPARATION_DEADLINE', '2026-10-06T13:30:00+00:00')
    monkeypatch.setenv('SENTINEL_INSTALL_SOURCE_DEADLINE', '2026-10-06T13:30:00+00:00')
    monkeypatch.setenv('SENTINEL_INSTALL_SOURCE_TARGET', TARGET)
    monkeypatch.setattr(store, 'connect', lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(schema, 'ensure_schema', noop)
    monkeypatch.setattr(store, 'migrate_schema', noop)
    monkeypatch.setattr(store, 'require_feed_schema', noop)
    monkeypatch.setattr(backup_guard, 'require_writes_permitted', noop)
    monkeypatch.setattr(deployment_fence, 'require', noop)
    monkeypatch.setattr(rolling_go_inputs, 'require_schemas', noop)
    monkeypatch.setattr(operational_snapshot, 'source_final_session', lambda *_a, **_k: TARGET)
    monkeypatch.setattr(rolling_go_inputs, 'current', lambda *_a: SimpleNamespace(window_end=TARGET))
    monkeypatch.setattr(publication, 'chain_gaps', lambda *_a: [])

    def prepare(*args, **kwargs):
        connection.prepared = True
        if error is not None:
            connection.disposed = disposed
            connection.closed = closed
            if disposed:
                setattr(error, writer_schedule._DISCARDED, True)
            raise error
        return {'status': 'PUBLISHED', 'schema': rolling_go_inputs.SCHEMA}

    monkeypatch.setattr(retained_go, 'prepare', prepare)
    monkeypatch.setattr(rolling_go_inputs, 'prepare', prepare)
    monkeypatch.setattr(rolling_go_inputs, '_prepare', prepare)
    code = child(owner) if code is None else code
    assert code.count('now = datetime.now(timezone.utc)') == 1
    code = code.replace('now = datetime.now(timezone.utc)', 'now = _qualified_now')
    output = StringIO()
    caught = None
    with redirect_stdout(output):
        try:
            exec(compile(code, '<actual-acquisition-child>', 'exec'), {'_qualified_now': NOW})
        except BaseException as observed:
            caught = observed
    assert connection.prepared, 'fixture never reached the actual acquisition call'
    return connection, caught, output.getvalue()


def assert_disposed(monkeypatch, owner, *, kind='interrupt', closed=False, code=None):
    error = primary(kind)
    connection, caught, output = execute(monkeypatch, owner, error=error,
        disposed=True, closed=closed, code=code)
    assert caught is error, 'original child exception was replaced'
    assert connection.after_prepare == [], 'disposed child received later database calls'
    assert output == '', 'disposed child emitted translated failure, retry or success evidence'


@pytest.mark.parametrize('owner', OWNERS)
@pytest.mark.parametrize('kind', ['interrupt', 'exit', 'database', 'horizon', 'deadline', 'frontier'])
@pytest.mark.parametrize('closed', [False, True], ids=['failed-close', 'closed'])
def test_disposed_acquisition_children_preserve_exact_primary_without_database_use(
        monkeypatch, owner, kind, closed):
    assert_disposed(monkeypatch, owner, kind=kind, closed=closed)


@pytest.mark.parametrize('owner', OWNERS)
def test_removed_child_disposal_predicate_is_detected(monkeypatch, owner):
    source = child(owner)
    guard = 'writer_schedule.connection_discarded(exc)'
    assert guard in source
    changed = source.replace(guard, 'False')
    with pytest.raises(AssertionError, match='original child exception was replaced'):
        assert_disposed(monkeypatch, owner, code=changed)


def assert_healthy(monkeypatch, owner, *, succeed, code=None):
    error = None if succeed else primary('ordinary')
    connection, caught, output = execute(monkeypatch, owner, error=error, code=code)
    assert caught is error
    expected = (['rollback', 'close'] if owner == 'install_refresh'
                or owner == 'source_final' and not succeed else ['close'])
    assert connection.after_prepare == expected, 'healthy child cleanup changed'
    assert connection.closed
    if succeed:
        marker = 'SENTINEL_INSTALL_SOURCE_REFRESH=' if owner == 'install_refresh' else 'SENTINEL_GO_PREPARATION='
        assert marker in output
    elif owner == 'source_final':
        assert 'SENTINEL_GO_PREPARATION_FAILURE=' in output
    else:
        assert output == ''


@pytest.mark.parametrize('owner', OWNERS)
@pytest.mark.parametrize('succeed', [False, True], ids=['ordinary-failure', 'success'])
def test_healthy_acquisition_children_keep_cleanup_and_outcomes(monkeypatch, owner, succeed):
    assert_healthy(monkeypatch, owner, succeed=succeed)


@pytest.mark.parametrize('owner', OWNERS)
def test_removed_healthy_child_cleanup_is_detected(monkeypatch, owner):
    source = child(owner)
    guard = ('if c is not None and not discard_connection:' if owner == 'source_final'
             else 'if not discard_connection:')
    assert source.count(guard) == 1
    with pytest.raises(AssertionError, match='healthy child cleanup changed'):
        assert_healthy(monkeypatch, owner, succeed=True, code=source.replace(guard, 'if False:'))


@pytest.mark.parametrize('kind,status', [('horizon', 'BACKUP_HORIZON_EXCEEDED'),
                                       ('deadline', 'WINDOW_EXPIRED'), ('frontier', 'WINDOW_EXPIRED')])
def test_healthy_install_refresh_keeps_typed_outcomes(monkeypatch, kind, status):
    error = primary(kind)
    connection, caught, output = execute(monkeypatch, 'install_refresh', error=error)
    assert caught is None
    assert connection.after_prepare == ['rollback', 'rollback', 'close']
    value = json.loads(output.removeprefix('SENTINEL_INSTALL_SOURCE_REFRESH='))
    assert value == {'status': status,
                     'resume_job_id': error.resume_job_id if kind == 'horizon' else None}


@pytest.mark.parametrize('owner', OWNERS)
def test_changed_host_and_embedded_child_keep_python38_syntax(owner):
    ast.parse(child(owner), feature_version=(3, 8))
