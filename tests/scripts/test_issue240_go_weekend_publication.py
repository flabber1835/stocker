"""Regression for weekend GO validation publication coverage semantics."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_validate.py"

spec = importlib.util.spec_from_file_location("sentinel_go_validate_issue240", SCRIPT)
go = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = go
spec.loader.exec_module(go)


def test_database_health_accepts_publication_window_beyond_visible_frontier():
    """A Sunday through-date may legitimately cover a Friday XNYS frontier."""
    code = go._DATABASE_HEALTH_CODE
    assert "and held.window_end >= frontier" in code
    assert "and held.window_end == frontier" not in code


def test_preparation_and_database_health_use_same_publication_coverage_rule():
    assert "after.window_end >= target" in go._PREPARATION_CODE
    assert "held.window_end >= frontier" in go._DATABASE_HEALTH_CODE
