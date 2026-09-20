"""Independent return examples and refusal controls for the provisional runner."""
from copy import deepcopy
from decimal import Decimal
import hashlib
from types import SimpleNamespace

import pytest

from research.provisional_20y.inputs import stitch_benchmark, validate_manifest
from research.provisional_20y.run import (
    EconomicPath, END, START, PRODUCTION_REVISION, distributions, metadata,
    performance, verify_production)
from sentinel.core.spinoffs import require_supported_entitlements, SpinoffTermsRequired
from sentinel.feed.calendar import previous_sessions
from sentinel.shadow_observation import ShadowObservationRefused


def complete_rows():
    dates = [d for d in previous_sessions(END, 6000) if d >= START]
    return [{"session": d, "strategy_nav": "100000", "core_nav": "100000", "spy": "100"}
            for d in dates]


def test_twenty_year_multiple_and_drawdown_have_independent_cash_oracle():
    rows = complete_rows()
    rows[1]["strategy_nav"] = "50000"
    rows[-1].update(strategy_nav="400000", core_nav="200000", spy="300")
    result = performance(rows)
    assert Decimal(result["combined"]["multiple"]) == 4
    assert result["combined"]["cagr"] == pytest.approx(0.07177346253629313)
    assert Decimal(result["combined"]["maximum_drawdown"]) == Decimal("-0.5")
    assert Decimal(result["wealth_core"]["multiple"]) == 2
    assert Decimal(result["spy"]["multiple"]) == 3


@pytest.mark.parametrize("mutation", ["prefix", "gap", "duplicate", "nan", "zero"])
def test_incomplete_or_invalid_path_cannot_publish_twenty_year_returns(mutation):
    rows = complete_rows()
    if mutation == "prefix":
        rows.pop()
    elif mutation == "gap":
        del rows[100]
    elif mutation == "duplicate":
        rows[100] = deepcopy(rows[99])
    else:
        rows[100]["strategy_nav"] = "NaN" if mutation == "nan" else "0"
    with pytest.raises(ValueError):
        performance(rows)


def test_unknown_classification_stays_ineligible_and_issuer_groups_are_preserved():
    row = {"security_type_eligible": "0", "security_type": "unknown",
           "security_id": "ABC", "ticker": "ABC", "issuer_id": "UNKNOWN:ABC",
           "listing_first_session": "2000-01-03", "session": START}
    assert metadata(row).category is None
    row.update(security_type="common", security_type_eligible="1", issuer_id="CIK:123")
    other = {**row, "security_id": "ABC.B", "ticker": "ABC.B"}
    assert metadata(row).issuer_key() == metadata(other).issuer_key()


def test_retained_spin_off_reaches_production_entitlement_refusal():
    rows = [{"effective_session": START, "action": "spinoffdividend", "ticker": "ABC",
             "security_id": "ABC", "vendor_value": "42"}]
    events = distributions(rows)
    state = SimpleNamespace(wealth_core={"episodes": {
        "1": {"security_id": "ABC", "ticker": "ABC", "current_shares": 10}}})
    with pytest.raises(SpinoffTermsRequired, match="CHILD_OWNERSHIP_REQUIRED"):
        require_supported_entitlements(state, events[START])
    state.wealth_core["episodes"] = {}
    require_supported_entitlements(state, events[START])


def test_unresolved_core_valuation_cannot_enter_scalar_performance():
    state = SimpleNamespace(shadow_nav_history=[100000.0], last_processed_session=START,
        last_evidence={"observation": {"shadow_nav": 100000.0}, "wealth_core": {
            "session": START, "blocked": True, "resolved_equity": 100000.0,
            "resolved_open_equity": 100000.0, "estimated_equity": 100000.0,
            "open_unresolved_security_ids": []}})
    with pytest.raises(ShadowObservationRefused, match="unresolved or blocked"):
        EconomicPath(100000)._parent_economics(state)


def test_manifest_requires_passing_reconstruction_and_exact_bytes():
    data = b"independent retained input\n"
    digest = hashlib.sha256(data).hexdigest()
    manifest = {"status": "PASS", "members": {
        "rows.csv": {"sha256": digest, "bytes": len(data)}},
        "dataset_hash": hashlib.sha256(f"rows.csv\0{digest}\0{len(data)}\n".encode()).hexdigest()}
    validate_manifest(manifest, lambda _: data)
    with pytest.raises(ValueError, match="bytes differ"):
        validate_manifest(manifest, lambda _: b"changed")
    manifest["status"] = "FAIL"
    with pytest.raises(ValueError, match="unresolved blockers"):
        validate_manifest(manifest, lambda _: data)


def test_modified_production_source_is_refused(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"original production\n")
    manifest = {"revision": PRODUCTION_REVISION, "files": {
        "source.py": hashlib.sha256(source.read_bytes()).hexdigest()}}
    verify_production(tmp_path, manifest)
    source.write_bytes(b"a different strategy\n")
    with pytest.raises(ValueError, match="production source differs"):
        verify_production(tmp_path, manifest)


def test_partition_rebase_preserves_true_boundary_and_within_partition_returns():
    prefix = [{"session": "2005-12-29", "level": "1"},
              {"session": "2005-12-30", "level": "2"}]
    base = [{"session": "2006-01-03", "level": "1"},
            {"session": "2006-01-04", "level": "1.2"}]
    joined = stitch_benchmark(prefix, base, "1.1")
    values = [Decimal(r["level"]) for r in joined]
    assert values[1] / values[0] == Decimal(2)
    assert values[2] / values[1] == pytest.approx(Decimal("1.1"))
    assert values[3] / values[2] == Decimal("1.2")
    assert joined[2:] == base
    assert prefix[-1]["level"] == "2"


@pytest.mark.parametrize("factor", ["0", "-1", "NaN", "Infinity"])
def test_invalid_benchmark_bridge_refuses(factor):
    with pytest.raises(ValueError, match="bridge factor"):
        stitch_benchmark([{"session": "2005-12-30", "level": "1"}],
                         [{"session": "2006-01-03", "level": "1"}], factor)
