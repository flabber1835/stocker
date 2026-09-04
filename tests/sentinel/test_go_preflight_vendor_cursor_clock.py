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


def test_readonly_preflight_keeps_sep_vendor_clock_separate_from_market_clock():
    code = preflight._READ_ONLY_CODE
    assert "source_day = dt.datetime.now(dt.timezone.utc).date()" in code
    assert "target=source_day" in code
    assert "boundary_label='current source observation date'" in code
    assert "if through >= target:" in code


def test_readonly_preflight_keeps_market_cursors_on_market_target():
    code = preflight._READ_ONLY_CODE
    assert (
        "actions_cursor, name=maintenance.ACTIONS_CURSOR_NAME, target=target"
        in code)
    assert (
        "recent_cursor, name=recent_reconciliation.CURSOR_NAME, target=target"
        in code)
    assert "'lastupdated.lte': target.isoformat()" in code
