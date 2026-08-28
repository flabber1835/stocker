from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


go24 = _load("sentinel_go_24x7_entry_test", "scripts/sentinel_go_24x7_entry.py")

DIGEST = "sha256:" + "a" * 64
COMMIT = "b" * 40


class _Runner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        self.calls.append((list(argv), dict(env or {})))
        marker = "SENTINEL_GO_PREPARATION="
        return subprocess.CompletedProcess(
            argv, 0, stdout=marker + json.dumps(self.payload) + "\n",
            stderr="")


def test_preparation_accepts_source_final_frontier_after_its_following_open(monkeypatch):
    monkeypatch.setattr(
        go24.go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])
    runner = _Runner({
        "schema_migrated": True,
        "source_not_before_satisfied": True,
        "following_open_future": False,
        "bounded_sharadar_daily": True,
        "publication_current": True,
    })
    ticks = iter((10.0, 10.25))
    summary = go24._deployment_preparation_probe(
        runner,
        env={"SHARADAR_API_KEY": "x", "SENTINEL_POSTGRES_PASSWORD": "y"},
        runtime_ref=DIGEST, commit=COMMIT,
        monotonic=lambda: next(ticks))

    assert summary.status == go24.go.PASS
    assert summary.complete is True
    assert summary.schema_migration_attempted is True
    assert summary.bounded_sharadar_daily_attempted is True
    assert summary.elapsed_milliseconds == 250
    # This layer must not mint feed or broker authority itself. The real
    # FeedBoundPreparationRunner injects the exact feed capability at runtime.
    call_env = runner.calls[-1][1]
    assert "ALPACA_API_KEY" not in call_env
    assert "SENTINEL_FEED_AUTHORIZED" not in call_env


def test_preparation_still_refuses_non_final_target(monkeypatch):
    monkeypatch.setattr(
        go24.go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])
    runner = _Runner({
        "schema_migrated": True,
        "source_not_before_satisfied": False,
        "following_open_future": True,
        "bounded_sharadar_daily": True,
        "publication_current": True,
    })
    summary = go24._deployment_preparation_probe(
        runner,
        env={"SHARADAR_API_KEY": "x", "SENTINEL_POSTGRES_PASSWORD": "y"},
        runtime_ref=DIGEST, commit=COMMIT,
        monotonic=lambda: 1.0)
    assert summary.status == go24.go.FAIL
    assert summary.complete is False


def test_go_preparation_selects_latest_source_final_session_not_latest_close():
    code = go24._PREPARATION_CODE
    assert "def latest_source_final" in code
    assert "while now < publication_not_before(target)" in code
    assert "outage_recovery.catch_up(c, target_session=target)" in code
    assert "eligible = source_final and prospective" not in code


def test_source_final_overlay_does_not_redefine_public_readiness_or_db_gate():
    source = (ROOT / "scripts" / "sentinel_go_24x7_entry.py").read_text(
        encoding="utf-8")
    assert "_deployment_readiness_probe" not in source
    assert "prospective_trading_window" not in source
    assert "probe_sharadar_readiness" not in source


def test_24x7_overlay_is_internal_and_public_launcher_stays_verified(capsys):
    assert go24.main([]) == 2
    captured = capsys.readouterr()
    assert "internal" in captured.err
    assert "scripts/sentinel-go-validate.sh" in captured.err

    go_launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    deploy_launcher = (
        ROOT / "scripts" / "sentinel-autonomous-deploy.sh").read_text(
            encoding="utf-8")
    assert 'scripts/sentinel_go_verified_entry.py "$@"' in go_launcher
    assert "scripts/sentinel_go_24x7_entry.py" not in go_launcher
    assert 'scripts/sentinel_autonomous_deploy_bootstrap.py "$@"' in deploy_launcher
