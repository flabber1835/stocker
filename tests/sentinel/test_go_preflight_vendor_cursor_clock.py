from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_readonly_data_preflight as preflight  # noqa: E402


def test_diagnostic_compares_the_published_frontier_to_the_source_final_session():
    code = preflight._READ_ONLY_CODE
    assert "operational_snapshot.source_final_session()" in code
    assert "held.window_end > frontier" in code
    assert "held.window_end < frontier" in code
