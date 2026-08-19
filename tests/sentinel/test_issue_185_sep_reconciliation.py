"""Focused tests for #185 complete SEP key/value reconciliation."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.feed import publication, sep_reconciliation as recon, store


def _fp(*rows):
    fp = recon._Fingerprint()
    for row in rows:
        fp.add(*row)
    return fp


def _proof(fp, *, value_digest="c" * 64,
           max_lastupdated=dt.date(2026, 8, 18)):
    return recon._PartitionProof(
        rows=fp.rows, key_digest=fp.digest(), value_digest=value_digest,
        max_lastupdated=max_lastupdated)


def _result(year=2024, *, digest="a" * 64, value_digest="b" * 64,
            max_lastupdated=dt.date(2026, 8, 18), version=7):
    return recon.ReconciliationResult(
        year=year, start=f"{year}-01-01", end=f"{year}-12-31",
        rows=123, digest=digest, value_digest=value_digest,
        max_lastupdated=max_lastupdated, publication_version=version)


def test_keyset_fingerprint_is_order_independent_and_multiplicity_sensitive():
    a = ("P:1", "2020-01-02", "AAA")
    b = ("P:2", "2020-01-02", "BBB")
    assert _fp(a, b).digest() == _fp(b, a).digest()
    assert _fp(a, b).digest() != _fp(a, b, b).digest()


def test_numeric_canonicalization_matches_sql_decimal_and_python_float():
    assert recon._number(Decimal("124.808000")) == recon._number(124.808)
    assert recon._number(Decimal("1000000")) == recon._number(1_000_000.0)
    assert recon._number(Decimal("-0.000")) == "0"
    assert recon._number(None) is None


def test_value_fingerprint_changes_on_strategy_economics_not_numeric_spelling():
    left = recon._ValueFingerprint()
    right = recon._ValueFingerprint()
    left.add("P:1", "2020-01-02", "AAA",
             Decimal("12.5000"), Decimal("50.00"), Decimal("49.00"), 1000)
    right.add("P:1", "2020-01-02", "AAA", 12.5, 50.0, 49.0, 1000.0)
    assert left.digest() == right.digest()

    changed = recon._ValueFingerprint()
    changed.add("P:1", "2020-01-02", "AAA", 12.5, 50.01, 49.0, 1000.0)
    assert changed.digest() != left.digest()


def test_stable_equal_complete_year_passes_key_and_value_proof(monkeypatch):
    source_fp = _fp(("P:1", "2020-01-02", "AAA"),
                    ("P:2", "2020-01-02", "BBB"))
    local_fp = _fp(("P:2", "2020-01-02", "BBB"),
                   ("P:1", "2020-01-02", "AAA"))
    source = _proof(source_fp, value_digest="d" * 64,
                    max_lastupdated=dt.date(2026, 8, 17))
    local = _proof(local_fp, value_digest="d" * 64,
                   max_lastupdated=None)
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "_source_fingerprint", lambda *a, **k: source)
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: local)
    monkeypatch.setattr(
        publication, "require_current", lambda conn: SimpleNamespace(version=9))

    result = recon.reconcile_year(
        object(), fetch=object(), year=2020,
        start="2020-01-01", end="2020-12-31")
    assert result.year == 2020
    assert result.rows == 2
    assert result.digest == source.key_digest
    assert result.value_digest == "d" * 64
    assert result.max_lastupdated == dt.date(2026, 8, 17)
    assert result.publication_version == 9


@pytest.mark.parametrize(("source_fp", "local_fp"), [
    pytest.param(
        _fp(("P:1", "2020-01-02", "AAA")), _fp(), id="row-count-drift"),
    pytest.param(
        _fp(("P:1", "2020-01-02", "AAA")),
        _fp(("P:2", "2020-01-02", "BBB")), id="same-count-different-key"),
])
def test_complete_year_keyset_drift_refuses_instead_of_guessing(
        monkeypatch, source_fp, local_fp):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(
        recon, "_source_fingerprint", lambda *a, **k: _proof(source_fp))
    monkeypatch.setattr(
        recon, "_local_fingerprint", lambda *a, **k: _proof(local_fp))
    with pytest.raises(recon.SepKeysetDrift, match="Refusing to guess"):
        recon.reconcile_year(
            object(), fetch=object(), year=2020,
            start="2020-01-01", end="2020-12-31")


def test_same_keys_with_stale_price_or_volume_refuse_value_authority(monkeypatch):
    fp = _fp(("P:1", "2020-01-02", "AAA"))
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(
        recon, "_source_fingerprint",
        lambda *a, **k: _proof(fp, value_digest="1" * 64))
    monkeypatch.setattr(
        recon, "_local_fingerprint",
        lambda *a, **k: _proof(fp, value_digest="2" * 64,
                                max_lastupdated=None))
    with pytest.raises(recon.SepValueDrift, match="strategy values disagree"):
        recon.reconcile_year(
            object(), fetch=object(), year=2020,
            start="2020-01-01", end="2020-12-31")


def test_failed_reconciliation_does_not_advance_rotation_cursor(monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "YEARS_PER_RUN", 1)
    monkeypatch.setattr(
        recon, "_next_year",
        lambda conn: (2020, dt.date(2020, 1, 1), dt.date(2020, 12, 31)))
    monkeypatch.setattr(
        recon, "reconcile_year",
        lambda *a, **k: (_ for _ in ()).throw(recon.SepValueDrift("drift")))
    monkeypatch.setattr(
        recon, "_save_result",
        lambda *a, **k: pytest.fail("failed proof must not advance cursor"))
    with pytest.raises(recon.SepValueDrift, match="drift"):
        recon.reconcile_next(object(), fetch=object(), through="2026-08-18")


def test_rotation_advances_one_year_and_wraps(monkeypatch):
    monkeypatch.setattr(
        recon, "_visible_bounds",
        lambda conn: (dt.date(1997, 1, 2), dt.date(2026, 8, 18)))
    monkeypatch.setattr(
        recon, "_load_state",
        lambda conn: {"last_completed_year": 2000})
    year, start, end = recon._next_year(object())
    assert (year, start, end) == (
        2001, dt.date(2001, 1, 1), dt.date(2001, 12, 31))

    monkeypatch.setattr(
        recon, "_load_state",
        lambda conn: {"last_completed_year": 2026})
    year, start, end = recon._next_year(object())
    assert (year, start, end) == (
        1997, dt.date(1997, 1, 2), dt.date(1997, 12, 31))


def test_reconcile_next_saves_only_successful_complete_proof(monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "YEARS_PER_RUN", 1)
    monkeypatch.setattr(
        recon, "_next_year",
        lambda conn: (2024, dt.date(2024, 1, 1), dt.date(2024, 12, 31)))
    result = _result(2024)
    monkeypatch.setattr(recon, "reconcile_year", lambda *a, **k: result)
    saved = []
    monkeypatch.setattr(
        recon, "_save_result",
        lambda conn, value, *, checked_on: saved.append((value, checked_on)))
    assert recon.reconcile_next(
        object(), fetch=object(), through="2026-08-18") == [result]
    assert saved == [(result, dt.date(2026, 8, 18))]


def test_complete_launch_sweep_visits_every_published_year_partition(monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(
        recon, "_visible_bounds",
        lambda conn: (dt.date(2024, 3, 4), dt.date(2026, 8, 18)))
    calls = []

    def check(conn, *, fetch, year, start, end):
        calls.append((year, start, end))
        return recon.ReconciliationResult(
            year=year, start=start, end=end, rows=year,
            digest=(f"{year:04d}" * 16)[:64], value_digest="e" * 64,
            max_lastupdated=dt.date(2026, 8, 18), publication_version=11)

    monkeypatch.setattr(recon, "reconcile_year", check)
    monkeypatch.setattr(recon, "_save_result", lambda *a, **k: None)
    results = recon.reconcile_all(
        object(), fetch=object(), through="2026-08-18")
    assert calls == [
        (2024, "2024-03-04", "2024-12-31"),
        (2025, "2025-01-01", "2025-12-31"),
        (2026, "2026-01-01", "2026-08-18"),
    ]
    assert [r.year for r in results] == [2024, 2025, 2026]


def test_complete_launch_sweep_stops_at_first_bad_year_and_claims_no_later_year(
        monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(
        recon, "_visible_bounds",
        lambda conn: (dt.date(2024, 1, 2), dt.date(2026, 8, 18)))
    checked = []
    saved = []

    def check(conn, *, fetch, year, start, end):
        checked.append(year)
        if year == 2025:
            raise recon.SepValueDrift("2025 drift")
        return recon.ReconciliationResult(
            year=year, start=start, end=end, rows=1,
            digest="b" * 64, value_digest="c" * 64,
            max_lastupdated=dt.date(2026, 8, 18), publication_version=12)

    monkeypatch.setattr(recon, "reconcile_year", check)
    monkeypatch.setattr(
        recon, "_save_result",
        lambda conn, result, *, checked_on: saved.append(result.year))
    with pytest.raises(recon.SepValueDrift, match="2025 drift"):
        recon.reconcile_all(object(), fetch=object(), through="2026-08-18")
    assert checked == [2024, 2025]
    assert saved == [2024]
