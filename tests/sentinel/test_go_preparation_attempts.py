"""Execute the real child program through failures and retain attempt evidence."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_go_24x7_entry as source_final
import sentinel_go_validate_entry as entry
from sentinel import backup_guard, schema
from sentinel.feed import outage_recovery, store


@pytest.mark.parametrize("code", [source_final._PREPARATION_CODE, entry._RECOVERY_PREPARATION_CODE])
@pytest.mark.parametrize("failure,expected", [
    ("connect", (False, False)), ("backup", (False, False)),
    ("schema", (True, False)), ("daily", (True, True)),
])
def test_partial_preparation_attempts_survive_failure(monkeypatch, code, failure, expected):
    def fail(*args, **kwargs):
        raise RuntimeError("controlled preparation failure")

    noop = lambda *a, **k: None
    conn = SimpleNamespace(rollback=noop, close=noop)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "fixture")
    # Direct payload execution must supply the deadline normally injected by GO.
    monkeypatch.setenv("SENTINEL_GO_PREPARATION_DEADLINE", "2026-08-12T05:46:00+00:00")
    monkeypatch.setattr(store, "connect", fail if failure == "connect" else lambda *a: conn)
    monkeypatch.setattr(backup_guard, "require_writes_permitted", fail if failure == "backup" else noop)
    monkeypatch.setattr(schema, "ensure_schema", fail if failure == "schema" else noop)
    monkeypatch.setattr(store, "migrate_schema", noop)
    monkeypatch.setattr(schema, "require_runtime_schema", fail if failure == "schema" else noop)
    monkeypatch.setattr(store, "require_feed_schema", noop)
    monkeypatch.setattr(outage_recovery, "catch_up", fail)
    from sentinel.feed import rolling_go_inputs
    monkeypatch.setattr(rolling_go_inputs, "prepare", fail)
    from sentinel import retained_go
    monkeypatch.setattr(retained_go, 'prepare', fail)
    # Select a deterministic eligible instant without rewriting phase/attempt code.
    code = code.replace("now = datetime.now(timezone.utc)",
                        "now = datetime(2026, 8, 12, 3, 46, tzinfo=timezone.utc)")
    code = code.replace("target = calendar.latest_closed_session()",
                        "target = '2026-08-11'")
    output = io.StringIO()
    with redirect_stdout(output), pytest.raises(RuntimeError, match="controlled"):
        exec(code, {})
    payload = json.loads(output.getvalue().split("SENTINEL_GO_PREPARATION_FAILURE=", 1)[1])
    assert (payload["schema_migration_attempted"], payload["bounded_sharadar_daily_attempted"]) == expected

    class Runner:
        def run(self, argv, **kwargs):
            if source_final._RETAINED_REVISION_CODE in argv:
                return subprocess.CompletedProcess(argv, 0, '{"retained_revision":null}', '')
            return subprocess.CompletedProcess(argv, 1, output.getvalue(), "")

    monkeypatch.setattr(source_final.go, "_resolve_compose_args", lambda *a: [])
    summary = source_final._deployment_preparation_probe(
        Runner(), env={"ALPACA_API_KEY": "market-data-key",
                       "ALPACA_SECRET_KEY": "market-data-secret",
                       "SENTINEL_POSTGRES_PASSWORD": "fixture"},
        runtime_ref="sha256:" + "a" * 64, commit="b" * 40)
    assert summary.status == source_final.go.FAIL
    assert not summary.complete
    assert (summary.schema_migration_attempted, summary.bounded_sharadar_daily_attempted) == expected


@pytest.mark.parametrize("text", ["not-json", "[]", '{}',
    '{"schema_migration_attempted":"true","bounded_sharadar_daily_attempted":true}'])
def test_malformed_attempt_evidence_does_not_invent_attempts(text):
    result = subprocess.CompletedProcess([], 1, "SENTINEL_GO_PREPARATION_FAILURE=" + text, "")
    assert source_final.go.preparation_attempts(result, schema_migrated=False, daily_completed=False) == (False, False)


def test_ambiguous_attempt_markers_are_not_evidence():
    marker = 'SENTINEL_GO_PREPARATION_FAILURE={"schema_migration_attempted":true,"bounded_sharadar_daily_attempted":true}\n'
    result = subprocess.CompletedProcess([], 1, marker + marker, "")
    assert source_final.go.preparation_attempts(result, schema_migrated=False, daily_completed=False) == (False, False)


def _probe(monkeypatch, completed):
    class Runner:
        def run(self, argv, **kwargs):
            if source_final._RETAINED_REVISION_CODE in argv:
                return subprocess.CompletedProcess(argv, 0, '{"retained_revision":null}', '')
            return completed

    monkeypatch.setattr(source_final.go, '_resolve_compose_args', lambda *a: [])
    return source_final._deployment_preparation_probe(Runner(), env={
        'ALPACA_API_KEY': 'fixture', 'ALPACA_SECRET_KEY': 'fixture',
        'SENTINEL_POSTGRES_PASSWORD': 'fixture'},
        runtime_ref='sha256:'+'a'*64, commit='b'*40)


@pytest.mark.parametrize('change', ['duplicate_key', 'duplicate_marker', 'stderr_duplicate',
                                  'missing', 'extra', 'string', 'integer', 'nonfinite'])
def test_ambiguous_success_json_never_completes_preparation(monkeypatch, change):
    value = dict(schema_migrated=True, source_not_before_satisfied=True,
                 following_open_future=False, bounded_sharadar_daily=True,
                 publication_current=True)
    if change == 'missing':
        del value['following_open_future']
    if change == 'extra':
        value['invented'] = True
    if change in {'string', 'integer', 'nonfinite'}:
        value['following_open_future'] = {'string': 'false', 'integer': 0,
                                         'nonfinite': float('nan')}[change]
    payload = json.dumps(value)
    if change == 'duplicate_key':
        payload = payload[:-1]+',"schema_migrated":true}'
    marker = 'SENTINEL_GO_PREPARATION='+payload+'\n'
    completed = subprocess.CompletedProcess([], 0,
        marker*2 if change == 'duplicate_marker' else marker,
        marker if change == 'stderr_duplicate' else '')
    summary = _probe(monkeypatch, completed)
    assert summary.status == source_final.go.FAIL
    assert not summary.complete


def test_duplicate_failure_keys_never_invent_attempts_or_renewal():
    import sentinel_go_backup_retry as retry
    payload = ('{"phase":"DAILY_CATCHUP","error_type":"BackupHorizonExceeded",'
        '"reason_code":"BACKUP_RUNTIME_HORIZON_EXCEEDED",'
        '"schema_migration_attempted":false,"schema_migration_attempted":true,'
        '"bounded_sharadar_daily_attempted":true,'
        '"resume_job_id":"00000000-0000-0000-0000-000000000001"}')
    completed = subprocess.CompletedProcess([], 1, retry.FAILURE+payload, '')
    assert source_final.go.preparation_attempts(completed,
        schema_migrated=False, daily_completed=False) == (False, False)
    assert retry.resumable_job(completed) is None


def test_broken_success_marker_uniqueness_is_detected(monkeypatch):
    import inspect, textwrap
    source = textwrap.dedent(inspect.getsource(source_final._deployment_preparation_probe))
    assert 'len(lines) == 1' in source
    namespace = {}
    exec(compile(source.replace('len(lines) == 1', 'len(lines) >= 1'),
        'ambiguous-preparation-success', 'exec'), source_final.__dict__, namespace)
    monkeypatch.setattr(source_final, '_deployment_preparation_probe',
        namespace['_deployment_preparation_probe'])
    with pytest.raises(AssertionError):
        test_ambiguous_success_json_never_completes_preparation(monkeypatch, 'duplicate_marker')


@pytest.mark.parametrize('module_name,function,hook', [
    ('sentinel_go_validate', 'preparation_attempts', '_preparation_json_object'),
    ('sentinel_go_backup_retry', 'failure_payload', '_failure_object'),
])
def test_broken_failure_duplicate_key_guards_are_detected(monkeypatch, module_name, function, hook):
    import importlib, inspect, textwrap
    module = importlib.import_module(module_name)
    source = textwrap.dedent(inspect.getsource(getattr(module, function)))
    old = ', object_pairs_hook='+hook
    assert old in source
    namespace = {}
    exec(compile(source.replace(old, ''), 'ambiguous-preparation-failure', 'exec'),
        module.__dict__, namespace)
    monkeypatch.setattr(module, function, namespace[function])
    with pytest.raises(AssertionError):
        test_duplicate_failure_keys_never_invent_attempts_or_renewal()
