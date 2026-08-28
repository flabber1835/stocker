from __future__ import annotations

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

import sentinel_go_24x7_entry as source_final  # noqa: E402


go = source_final.go
DIGEST = "sha256:" + "a" * 64
COMMIT = "b" * 40


class PreparationRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        self.calls.append((list(argv), dict(env or {})))
        return subprocess.CompletedProcess(
            argv, 0,
            stdout=("SENTINEL_GO_PREPARATION="
                    + json.dumps(self.payload, sort_keys=True) + "\n"),
            stderr="")


def test_source_final_preparation_does_not_require_following_open_future(monkeypatch):
    monkeypatch.setattr(
        go, "_resolve_compose_args",
        lambda runner, env: ["-f", "compose.yml"])
    runner = PreparationRunner({
        "schema_migrated": True,
        "source_not_before_satisfied": True,
        "following_open_future": False,
        "bounded_sharadar_daily": True,
        "publication_current": True,
    })
    ticks = iter((10.0, 10.25))

    summary = source_final._deployment_preparation_probe(
        runner,
        env={
            "SHARADAR_API_KEY": "private",
            "SENTINEL_POSTGRES_PASSWORD": "private",
            "ALPACA_API_KEY": "must-not-enter",
            "ALPACA_SECRET_KEY": "must-not-enter",
        },
        runtime_ref=DIGEST,
        commit=COMMIT,
        monotonic=lambda: next(ticks))

    assert summary.status == go.PASS
    assert summary.complete is True
    assert summary.bounded_sharadar_daily_attempted is True
    assert summary.elapsed_milliseconds == 250
    prepared_env = runner.calls[-1][1]
    assert "ALPACA_API_KEY" not in prepared_env
    assert "ALPACA_SECRET_KEY" not in prepared_env


def test_preparation_selects_newest_causally_final_frontier():
    code = source_final._PREPARATION_CODE
    assert "def latest_source_final(now)" in code
    assert "while now < publication_not_before(target)" in code
    assert "calendar.previous_sessions(target, 2)" in code
    assert "outage_recovery.catch_up(c, target_session=target)" in code
    assert "eligible = source_final and prospective" not in code


def test_nonfinal_selected_target_can_never_pass(monkeypatch):
    monkeypatch.setattr(
        go, "_resolve_compose_args",
        lambda runner, env: ["-f", "compose.yml"])
    runner = PreparationRunner({
        "schema_migrated": True,
        "source_not_before_satisfied": False,
        "following_open_future": True,
        "bounded_sharadar_daily": True,
        "publication_current": True,
    })

    summary = source_final._deployment_preparation_probe(
        runner,
        env={
            "SHARADAR_API_KEY": "private",
            "SENTINEL_POSTGRES_PASSWORD": "private",
        },
        runtime_ref=DIGEST,
        commit=COMMIT,
        monotonic=lambda: 1.0)

    assert summary.status == go.FAIL
    assert summary.complete is False


def test_source_final_overlay_is_internal_only(capsys):
    assert source_final.main([]) == 2
    captured = capsys.readouterr()
    assert "internal" in captured.err
    assert "scripts/sentinel-go-validate.sh" in captured.err
