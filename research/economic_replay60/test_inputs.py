from decimal import Decimal
import pytest

from .inputs import Classification, START, performance, progress


def row(sid, ticker, day, value="unknown"):
    return dict(security_id=sid, ticker=ticker, session=day, security_type=value)


def test_reference_interval_and_known_classification_precedence():
    model = Classification()
    assert model.apply(row("214820292338870148", "CHAP1", "2006-07-05"))["security_type"] == "common"
    assert model.apply(row("214820292338870148", "CHAP1", "2006-01-03"))["security_type"] == "unknown"
    assert model.apply(row("214820292338870148", "CHAP1", "2006-07-05", "non_common"))["security_type"] == "non_common"
    assert model.apply(row("unreviewed", "OTHER", "2006-07-05"))["security_type"] == "unknown"


def test_identity_and_historical_type_transition():
    model = Classification()
    with pytest.raises(ValueError):
        model.apply(row("214820292338870148", "WRONG", "2006-07-05"))
    assert model.apply(row("594891209465982980", "PDS", "2010-06-01"))["security_type"] == "non_common"
    assert model.apply(row("594891209465982980", "PDS", "2010-06-02"))["security_type"] == "common"


def test_three_independent_bases_same_dates():
    refs = {START: Decimal("200"), "2007-07-31": Decimal("220")}
    spy = {START: Decimal("50"), "2007-07-31": Decimal("60")}
    stats, baseline = progress({}, START, "100", refs, spy)
    assert all(r["multiple"] == "1" and r["cagr"] is None for r in baseline["comparison"].values())
    resumed, report = progress(dict(stats), "2007-07-31", "150", refs, spy)
    result = report["comparison"]
    assert [result[k]["multiple"] for k in ["current", "reference", "spy"]] == ["1.5", "1.1", "1.2"]
    assert 0.5003 < result["current"]["cagr"] < 0.5005
    assert 0.1000 < result["reference"]["cagr"] < 0.1001
    assert 0.2001 < result["spy"]["cagr"] < 0.2002
    assert resumed["base"] == "100"


def test_flat_series_and_bad_periods():
    assert performance("100", "100", START, "2008-09-02")["cagr"] == 0
    with pytest.raises(ValueError):
        performance("100", "100", START, "2006-07-01")
    with pytest.raises(ValueError):
        performance("0", "100", START, "2008-09-02")
    with pytest.raises(ValueError):
        progress({}, "2006-08-01", "100", {}, {})


def test_formation_has_no_performance_and_baseline_cannot_change():
    assert progress({}, "2006-07-06", "99000", {}, {})[1]["comparison"] is None
    refs = {START: Decimal("200")}
    spy = {START: Decimal("50")}
    stats, _ = progress({}, START, "100", refs, spy)
    with pytest.raises(ValueError):
        progress(stats, START, "100", refs, {START: Decimal("51")})
