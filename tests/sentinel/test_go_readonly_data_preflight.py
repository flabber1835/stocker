from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_readonly_data_preflight.py"
spec = importlib.util.spec_from_file_location("sentinel_go_readonly_data_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


def test_preflight_never_receives_broker_authority():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "go._without_broker_authority(env)" in source
    assert "ALPACA_API_KEY" not in preflight._READ_ONLY_CODE
    assert "ALPACA_SECRET_KEY" not in preflight._READ_ONLY_CODE
    assert "SENTINEL_PAPER_ACCOUNT_ID" not in preflight._READ_ONLY_CODE


def test_preflight_builds_only_exact_commit_scoped_ordinary_runtime():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'ref = "sentinel-go-runtime:%s" % commit' in source
    assert '"SOURCE_GIT_SHA=" + commit' in source
    assert '"-f", "Dockerfile.sentinel"' in source
    assert "sentinel-go-authorized:" not in source
    assert "sentinel-go-test:" not in source


def test_launcher_uses_verified_alpaca_preparation_without_legacy_preflight():
    launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    account = launcher.index("sentinel_go_account_preflight.py")
    certified = launcher.index("sentinel_go_verified_entry.py")
    assert account < certified
    assert '"$PYTHON" scripts/sentinel_go_readonly_data_preflight.py' not in launcher


def test_controlled_detail_scrubs_transport_or_credential_shaped_text():
    assert preflight._safe_detail(
        "SEP mutation ABC/2026-08-20 identity unresolved: IDENTITY_INTERVAL_GAP") is not None
    assert preflight._safe_detail(
        "https://example.invalid?api_key=super-secret") is None
    assert preflight._safe_detail(
        "postgresql://user:password@host/db") is None


def test_payload_accepts_only_one_marker_json_object():
    ok = subprocess.CompletedProcess(
        ["x"], 0,
        stdout=(preflight.MARKER
                + '{"reason_code":"ROLLING_PUBLICATION_CURRENT","status":"PASS"}\n'),
        stderr="")
    assert preflight._payload(ok) == {
        "reason_code": "ROLLING_PUBLICATION_CURRENT", "status": "PASS"}
    malformed = subprocess.CompletedProcess(
        ["x"], 0, stdout=preflight.MARKER + "not-json\n", stderr="")
    assert preflight._payload(malformed) is None

def test_shared_diagnostic_executes_bound_rolling_frontier(monkeypatch, capsys):
    from types import SimpleNamespace
    from datetime import date
    from sentinel.feed import operational_snapshot, rolling_go_inputs, store
    class Connection:
        last = ""
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def cursor(self): return self
        def execute(self, sql): self.last = sql
        def fetchone(self): return ("on" if "SHOW" in self.last else "published",)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "fixture")
    monkeypatch.setattr(store, "connect", lambda _: Connection())
    final = date(2026, 8, 19)
    monkeypatch.setattr(operational_snapshot, "source_final_session", lambda: final)
    monkeypatch.setattr(rolling_go_inputs, "is_rolling", lambda held: True)
    bound = []
    monkeypatch.setattr(operational_snapshot, "require_alpaca_openfigi", lambda c, held: bound.append(held.window_end))
    for day, status in [(18, "RECOVERY_REQUIRED"), (19, "PASS"), (20, "REFUSED")]:
        pub = SimpleNamespace(window_end=date(2026, 8, day))
        monkeypatch.setattr(rolling_go_inputs, "current", lambda c: pub)
        exec(preflight._READ_ONLY_CODE, {})
        raw = capsys.readouterr().out.split(preflight.MARKER)[1]
        assert json.loads(raw)["status"] == status
    assert len(bound) == 3
