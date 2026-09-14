"""The original failure must remain explainable across the GO subprocess/ZIP boundary."""
import ast
import json
import runpy
from types import SimpleNamespace

import pytest

from sentinel import source_diagnostic
from sentinel.feed import coherence, source_authority, symbol_identity
from test_go_preparation_identity_reason_codes import source_final, validate_entry, ROOT
from test_reused_symbol_identity import REUSED_LISTING, COMPLETED_REUSED_ACTIONS
from test_historical_symbol_identity import HISTORICAL_RENAMES
from test_seed_symbol_transition import OLD_LISTINGS
from test_symbol_identity_recovery import THROUGH


def collision_failure():
    # An actual overlapping permanent-ID conflict remains a refusal. Its full
    # typed reason must survive even when the human-readable text is truncated.
    rows = [*OLD_LISTINGS, dict(REUSED_LISTING, firstpricedate="2018-12-14")]
    identity = symbol_identity.SymbolProjection(
        rows, HISTORICAL_RENAMES + COMPLETED_REUSED_ACTIONS, through=THROUGH)
    coverage = source_authority.SeedCoverageAccumulator(
        source_authority.SeedListingProjection(rows, source_digest="a" * 64),
        identity.resolver().resolve, exceptions={})
    try:
        coverage.add({"ticker": "HLSQ", "date": "2025-07-01"})
        with pytest.raises(source_authority.SourceAuthorityRefused) as caught:
            coverage.require_complete(date_from="2025-07-01", date_to="2025-07-01")
        return coherence.SeedHistoryIncomplete(str(caught.value))
    finally:
        coverage.close()


def test_real_conflict_survives_both_preparation_markers_and_bundle_view():
    import sentinel_go_phase_controller as controller
    failure = collision_failure()
    for code in (source_final._PREPARATION_CODE, validate_entry._RECOVERY_PREPARATION_CODE):
        namespace = {}
        exec(code.split("\ndef emit_failure", 1)[0], namespace)
        diagnostic = namespace["failure_detail"](failure)
        assert len(diagnostic["detail"]) <= 420
        payload = source_diagnostic.collect_source_coverage(
            source_diagnostic.FAILURE_MARKER + json.dumps(diagnostic))
        assert payload["session"] == "2025-07-01"
        reasons = payload["identity_diagnostics"]["rejections"]
        assert any(r["reason_code"] == "RENAME_ANCHOR_IDENTITY_OR_CATEGORY_AMBIGUOUS"
                   for r in reasons)
        assert any(str(r["permaticker"]) == "644444" for d in reasons for r in d["anchors"])
        view = controller.PreparationView(SimpleNamespace(to_dict=lambda: {}), source_coverage=payload)
        assert view.to_dict()["source_coverage"] == payload


def test_diagnostic_is_standalone_host_python38_and_rejects_credential_shaped_data():
    path = ROOT / "sentinel" / "source_diagnostic.py"
    ast.parse(path.read_text(), feature_version=(3, 8))
    plain = runpy.run_path(str(path))  # No runtime feed imports required on NAS.
    assert plain["coverage_diagnostic"](str(collision_failure()))
    for bad in ("https://private.invalid?api_key=secret", "password", "a\nb", "x" * 257):
        raw = source_diagnostic.PREFIX + json.dumps({"session": "2025-07-01",
                                                    "unresolved_source_tickers": [bad]})
        assert plain["coverage_diagnostic"](raw) is None
    assert plain["coverage_diagnostic"](source_diagnostic.PREFIX + "x" * 40000) is None
