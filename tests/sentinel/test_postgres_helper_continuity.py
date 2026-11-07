"""A release pathname change alone must leave the PostgreSQL bind unchanged."""
import importlib
import inspect
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
helpers = importlib.import_module('sentinel_postgres_helpers')


@pytest.fixture
def graph(tmp_path):
    previous, current = (tmp_path/name for name in ('previous-release', 'next-release'))
    for root in (previous, current):
        (root/'scripts').mkdir(parents=True)
        (root/'scripts'/helpers.HELPER).write_text('reviewed standalone archive helper\n')
    record = dict(name='/sentinel-sentinel-postgres-1', image=helpers.POSTGRES,
        project='sentinel', service='sentinel-postgres', mounts=[dict(
            Type='bind', Source=str(previous/'scripts'), Destination='/usr/local/libexec', RW=False)])
    calls = []
    def inspect(argv):
        calls.append(argv)
        return 'canonical-id\n' if 'ps' in argv else json.dumps(record)
    return previous, current, record, inspect, calls


def test_identical_archive_bytes_retain_existing_source_without_pg_work(graph, tmp_path):
    previous, current, record, inspect, calls = graph
    selected = helpers.unchanged_mount(current, inspect)
    assert selected == previous/'scripts'
    target = tmp_path/'override.yml'
    helpers.publish_override(target, selected)
    parsed = json.loads(target.read_bytes())
    mount = parsed['services']['sentinel-postgres']['volumes'][0]
    assert mount == dict(type='bind',source=str(previous/'scripts'),target='/usr/local/libexec',read_only=True)
    assert len(calls) == 2 and all('up' not in call and 'exec' not in call for call in calls)
    original = target.stat().st_mtime_ns
    helpers.publish_override(target, selected)
    assert target.stat().st_mtime_ns == original


def test_changed_helper_requires_normal_current_source_reconciliation(graph):
    previous, current, _, inspect, _ = graph
    (current/'scripts'/helpers.HELPER).write_text('different reviewed archive implementation\n')
    assert helpers.unchanged_mount(current, inspect) is None
    assert (previous/'scripts'/helpers.HELPER).read_text() == 'reviewed standalone archive helper\n'


def test_removed_content_guard_is_detected(graph, monkeypatch):
    source = inspect.getsource(helpers.unchanged_mount)
    guard = 'if mounted.read_bytes() != candidate.read_bytes():'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if False:'), '<removed-helper-content-guard>', 'exec'),
         helpers.__dict__, namespace)
    monkeypatch.setattr(helpers, 'unchanged_mount', namespace['unchanged_mount'])
    with pytest.raises(AssertionError):
        test_changed_helper_requires_normal_current_source_reconciliation(graph)


@pytest.mark.parametrize('change', [
    {'project':'other'}, {'service':'other'}, {'name':'/foreign'}, {'image':'postgres:latest'},
    {'mounts':[dict(Type='bind',Source='/unexpected',Destination='/usr/local/libexec',RW=True)]},
])
def test_ownership_or_mount_drift_refuses(graph, change):
    _, current, record, inspect, _ = graph
    record.update(change)
    with pytest.raises(RuntimeError):helpers.unchanged_mount(current, inspect)


def test_unknown_or_multiple_primary_ownership_cannot_select_a_mount(tmp_path):
    assert helpers.unchanged_mount(tmp_path, lambda argv:'') is None
    with pytest.raises(RuntimeError, match='ambiguous'):
        helpers.unchanged_mount(tmp_path, lambda argv:'first\nsecond\n')


def test_missing_and_symlinked_prior_helper_cannot_be_reused(graph):
    previous, current, _, inspect, _ = graph
    helper = previous/'scripts'/helpers.HELPER
    helper.unlink()
    assert helpers.unchanged_mount(current, inspect) is None
    helper.symlink_to(current/'scripts'/helpers.HELPER)
    assert helpers.unchanged_mount(current, inspect) is None
