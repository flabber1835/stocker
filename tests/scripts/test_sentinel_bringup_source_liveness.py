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
        "reason_code": "ROLLING_PUBLICATION_CURRENT",
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


def test_probe_reads_only_the_bound_rolling_publication():
    source = liveness._CODE
    assert "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert "SHOW transaction_read_only" in source
    assert "require_alpaca_openfigi" in source
    assert "source_final_session" in source
    for unsafe in ("fetch_table", ".acquisition(", "INSERT INTO", "UPDATE sentinel_", "CREATE TABLE"):
        assert unsafe not in source
