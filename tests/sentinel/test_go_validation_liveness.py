from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_data_preflight.py"
spec = importlib.util.spec_from_file_location("sentinel_go_data_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


def test_controlled_sharadar_reason_preserves_actionable_local_detail():
    stderr = "\n".join([
        "Traceback (most recent call last):",
        "sentinel.feed.maintenance_impl.SharadarMutationRefused: SEP mutation ABC/2026-08-20 has no permanent identity; refusing to advance the mutation watermark past it",
    ])
    assert preflight._controlled_sharadar_reason(stderr) == (
        "SEP mutation ABC/2026-08-20 has no permanent identity; refusing to advance the mutation watermark past it")


def test_controlled_sharadar_reason_refuses_url_or_secret_shaped_detail():
    assert preflight._controlled_sharadar_reason(
        "SharadarMutationRefused: https://example.invalid?api_key=secret") is None
    assert preflight._controlled_sharadar_reason(
        "SharadarMutationRefused: postgresql://user:pw@host/db") is None


def test_launcher_runs_data_preflight_before_expensive_validator():
    text = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    runtime = text.index("sentinel_runtime_selection.py preflight")
    data = text.index("sentinel_go_data_preflight.py")
    validator = text.index("sentinel_go_validate_entry.py")
    assert runtime < data < validator


def test_launcher_skips_data_mutation_for_development_input():
    text = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert "RUN_DATA_PREFLIGHT=1" in text
    assert "--input=*|--dev-input" in text
    assert 'if [ "$RUN_DATA_PREFLIGHT" -eq 1 ]' in text


def test_preflight_uses_exact_commit_scoped_ordinary_runtime():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'reference = "sentinel-go-runtime:%s" % commit' in text
    assert '"SOURCE_GIT_SHA=" + commit' in text
    assert "entry.probe_prevalidation_preparation" in text
