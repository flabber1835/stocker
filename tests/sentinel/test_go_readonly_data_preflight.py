from __future__ import annotations

import importlib.util
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


def test_preflight_container_is_transactionally_read_only_and_has_no_write_primitives():
    code = preflight._READ_ONLY_CODE
    assert "REPEATABLE READ READ ONLY" in code
    assert "SHOW transaction_read_only" in code
    assert "maintenance._stable_rows" in code
    assert "source_authority.SepUpdateEnvelope.interval" in code
    assert "source_authority.CanonicalSourceFetch" in code
    assert "identity_refresh.validate_with_current_tickers_if_refreshable" in code
    assert "publication_not_before" in code
    assert "SHARADAR_SOURCE_NOT_FINAL" in code
    forbidden = (
        "schema.ensure_schema",
        "store.migrate_schema",
        "ingest.daily",
        "IngestRun(",
        "renormalize.renormalize",
        "publication.publish",
        "maintenance._write_cursor",
        "establish_sep_cursor",
        "snapshot_export.fetch_complete_actions",
        "snapshot_export.fetch_complete_sep",
        "recent_reconciliation.reconcile_recent",
        "maintenance.reconcile_actions_if_due",
    )
    for token in forbidden:
        assert token not in code


def test_preflight_validates_all_local_maintenance_cursor_authority():
    code = preflight._READ_ONLY_CODE
    assert "maintenance.SEP_CURSOR_NAME" in code
    assert "maintenance.ACTIONS_CURSOR_NAME" in code
    assert "maintenance.ACTIONS_CURSOR_KIND" in code
    assert "recent_reconciliation.CURSOR_NAME" in code
    assert "recent_reconciliation.CURSOR_KIND" in code
    assert "load_cursor_readonly" in code
    assert "require_not_future" in code
    assert "processed_through %s is ahead of %s %s" in code
    assert "target <= through" not in code
    assert "if through >= target" not in code
    assert "through == source_day" in code


def test_missing_legacy_cursor_state_is_recovery_not_source_corruption():
    code = preflight._READ_ONLY_CODE
    assert "CORPUS_SCHEMA_NOT_INSTALLED" in code
    assert "CURSOR_SCHEMA_NOT_INSTALLED" in code
    assert "SEP_CURSOR_MISSING" in code
    assert "ACTIONS_CURSOR_MISSING" in code
    assert "RECENT_SEP_CURSOR_MISSING" in code
    assert "local_followup" in code


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


def test_launcher_runs_readonly_data_preflight_before_verified_certification():
    launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    account = launcher.index("sentinel_go_account_preflight.py")
    data = launcher.index("sentinel_go_readonly_data_preflight.py")
    certified = launcher.index("sentinel_go_verified_entry.py")
    assert account < data < certified
    # Development/test input remains non-mutating and bypasses production probes.
    data_pos = launcher.index('if [ "$PRODUCTION_RUN" -eq 1 ]', account)
    assert data_pos < data


def test_source_final_deferral_is_non_negative_authority():
    code = preflight._READ_ONLY_CODE
    deferred = code.index("'status': 'DEFERRED'")
    fetch = code.index("maintenance._stable_rows")
    assert deferred < fetch
    assert "SHARADAR_SOURCE_NOT_FINAL" in code


def test_safe_identity_refresh_is_diagnostic_pass_not_local_authority():
    code = preflight._READ_ONLY_CODE
    assert "LOCAL_IDENTITY_REFRESH_REQUIRED" in code
    assert "identity_refresh.SepMutationIdentityRefused" in code
    assert "SOURCE_IDENTITY_NO_PERMANENT_ID" in code
    assert "SOURCE_IDENTITY_INTERVAL_GAP" in code
    assert "SOURCE_IDENTITY_TICKER_REUSE_UNRESOLVED" in code
    assert "SOURCE_IDENTITY_AMBIGUOUS" in code
    assert "SOURCE_CDC_AUTHORITY_REFUSED" in code
    # Candidate proof is read-only liveness evidence; no source row is stored.
    assert "write_universe" not in code
    assert "feed_universe_current" not in code


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
                + '{"reason_code":"SEP_CDC_SOURCE_VALID","status":"PASS"}\n'),
        stderr="")
    assert preflight._payload(ok) == {
        "reason_code": "SEP_CDC_SOURCE_VALID", "status": "PASS"}
    malformed = subprocess.CompletedProcess(
        ["x"], 0, stdout=preflight.MARKER + "not-json\n", stderr="")
    assert preflight._payload(malformed) is None
