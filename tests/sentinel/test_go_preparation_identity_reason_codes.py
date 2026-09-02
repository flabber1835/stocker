from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_24x7_entry as source_final
import sentinel_go_validate_entry as validate_entry


class SepMutationIdentityRefused(Exception):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__("identity mutation refused: %s" % reason_code)


def _reason_function(code: str):
    prefix = code.split("\ndef emit_failure", 1)[0]
    namespace = {}
    exec(prefix, namespace)
    return namespace["reason_code"]


def test_preparation_codes_preserve_structured_identity_reason_codes():
    expected = {
        "NO_PERMANENT_ID": "SOURCE_IDENTITY_NO_PERMANENT_ID",
        "IDENTITY_INTERVAL_GAP": "SOURCE_IDENTITY_INTERVAL_GAP",
        "TICKER_REUSE_UNRESOLVED": "SOURCE_IDENTITY_TICKER_REUSE_UNRESOLVED",
        "AMBIGUOUS_IDENTITY": "SOURCE_IDENTITY_AMBIGUOUS",
    }
    for code in (
            validate_entry._RECOVERY_PREPARATION_CODE,
            source_final._PREPARATION_CODE):
        reason_code = _reason_function(code)
        for source_reason, machine_reason in expected.items():
            exc = SepMutationIdentityRefused(source_reason)
            assert reason_code("DAILY_CATCHUP", exc) == machine_reason
        assert (
            reason_code("DAILY_CATCHUP", SepMutationIdentityRefused("NEW_REASON"))
            == "SOURCE_IDENTITY_UNRESOLVED"
        )


def test_preparation_failure_markers_retain_raw_identity_reason_field():
    for code in (
            validate_entry._RECOVERY_PREPARATION_CODE,
            source_final._PREPARATION_CODE):
        assert "value['identity_reason'] = identity_reason" in code
        assert "getattr(exc, 'reason_code', '')" in code
