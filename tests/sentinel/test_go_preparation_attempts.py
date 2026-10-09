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
    if code is not entry._RECOVERY_PREPARATION_CODE and "phase = 'SCHEMA_VALIDATION'" in code:
        expected = (False, expected[1])
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
