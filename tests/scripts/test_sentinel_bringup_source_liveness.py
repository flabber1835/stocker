from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
MODULE = ROOT / "scripts" / "sentinel_bringup_source_liveness.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_bringup_source_liveness_test_module", MODULE)
liveness = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = liveness
spec.loader.exec_module(liveness)


def test_payload_requires_exactly_one_machine_report():
    value = {
        "status": "PASS",
        "reason_code": "SHARADAR_LIVENESS_OK",
        "source_rows": 9,
    }
    line = liveness.MARKER + json.dumps(value, sort_keys=True) + "\n"
    completed = subprocess.CompletedProcess(["fixture"], 0, stdout=line, stderr="")
    assert liveness.payload(completed) == value

    duplicate = subprocess.CompletedProcess(
        ["fixture"], 0, stdout=line + line, stderr="")
    assert liveness.payload(duplicate) is None


def test_safe_detail_suppresses_credentials_and_urls():
    assert liveness.safe_detail("https://example.invalid/?api_key=secret") is None
    assert liveness.safe_detail("password=secret") is None
    assert liveness.safe_detail("bounded source timeout") == "bounded source timeout"


def test_probe_uses_read_only_database_and_small_single_ticker_source_window():
    source = MODULE.read_text(encoding="utf-8")
    assert "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert "SHOW transaction_read_only" in source
    assert "'ticker': 'SPY'" in source
    assert "dt.timedelta(days=14)" in source
    assert "sharadar.SEP" in source
    assert "source_rows" in source


def test_probe_has_no_source_stability_identity_or_mutation_authority():
    source = MODULE.read_text(encoding="utf-8")
    forbidden = (
        "_stable_rows",
        "CanonicalSourceFetch",
        "SepUpdateEnvelope",
        "identity_refresh",
        "HistoricalIdentityMutation",
        "sharadar.TICKERS",
        "INSERT INTO",
        "UPDATE sentinel_",
        "DELETE FROM",
        "CREATE TABLE",
        "TRUNCATE TABLE",
        "pg_switch_wal",
    )
    for token in forbidden:
        assert token not in source
