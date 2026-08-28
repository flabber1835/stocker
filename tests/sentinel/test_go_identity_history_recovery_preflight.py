from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from sentinel.feed import outage_recovery, universe


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_readonly_data_preflight.py"
spec = importlib.util.spec_from_file_location(
    "sentinel_go_readonly_data_preflight_identity_recovery", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


def test_historical_identity_mutation_is_recovery_required_in_readonly_probe():
    code = preflight._READ_ONLY_CODE
    start = code.index("except universe.HistoricalIdentityMutation as exc:")
    end = code.index("except source_authority.SourceAuthorityRefused", start)
    block = code[start:end]

    assert "'status': 'RECOVERY_REQUIRED'" in block
    assert "'reason_code': 'SOURCE_IDENTITY_HISTORY_MUTATION'" in block
    assert "emit(value)" in block
    assert "refuse('SOURCE_IDENTITY_HISTORY_MUTATION'" not in block


def _run_report(monkeypatch, *, status: str, reason_code: str) -> int:
    class FakeRunner:
        def run(self, argv, *, env=None, cwd=None):
            payload = json.dumps({
                "status": status,
                "reason_code": reason_code,
            }, sort_keys=True)
            return subprocess.CompletedProcess(
                argv, 0, stdout=preflight.MARKER + payload + "\n", stderr="")

    monkeypatch.setattr(preflight.go, "CommandRunner", lambda: FakeRunner())
    monkeypatch.setattr(
        preflight.go,
        "merged_environment",
        lambda: {
            "SHARADAR_API_KEY": "test-key",
            "SENTINEL_POSTGRES_PASSWORD": "test-password",
        },
    )
    monkeypatch.setattr(
        preflight.go,
        "probe_git",
        lambda runner, now_text: (
            SimpleNamespace(commit="a" * 40),
            SimpleNamespace(status=preflight.go.PASS),
        ),
    )
    monkeypatch.setattr(
        preflight,
        "_build_exact_ordinary",
        lambda runner, commit: "sha256:" + "b" * 64,
    )
    monkeypatch.setattr(
        preflight.go, "_without_broker_authority", lambda env: dict(env))
    monkeypatch.setattr(
        preflight.go,
        "_resolve_compose_args",
        lambda runner, env: ["-f", "docker-compose.sentinel.yml"],
    )
    return preflight.main([])


def test_identity_history_recovery_requirement_allows_go_to_continue(
        monkeypatch, capsys):
    rc = _run_report(
        monkeypatch,
        status="RECOVERY_REQUIRED",
        reason_code="SOURCE_IDENTITY_HISTORY_MUTATION",
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert (
        "read-only Sharadar preflight: RECOVERY_REQUIRED - "
        "SOURCE_IDENTITY_HISTORY_MUTATION; certified recovery will decide the write path"
        in captured.out
    )


def test_unrelated_source_refusal_still_blocks_go(monkeypatch, capsys):
    rc = _run_report(
        monkeypatch,
        status="REFUSED",
        reason_code="SOURCE_CDC_AUTHORITY_REFUSED",
    )

    assert rc == 2
    captured = capsys.readouterr()
    assert "REFUSED: read-only Sharadar preflight SOURCE_CDC_AUTHORITY_REFUSED" in captured.err


def test_certified_recovery_owns_historical_identity_rebuild_escalation():
    assert universe.HistoricalIdentityMutation in outage_recovery._RECOVERABLE_LOCAL_STATE
    source = Path(outage_recovery.__file__).read_text(encoding="utf-8")
    assert "except _RECOVERABLE_LOCAL_STATE as exc:" in source
    assert "ingest.seed(conn, date_from=retained_start, date_to=target)" in source
    assert 'mode = "RETAINED_FULL_RESEED"' in source
