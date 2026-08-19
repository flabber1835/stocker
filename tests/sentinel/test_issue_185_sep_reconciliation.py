"""Focused tests for #185 complete/periodic SEP key-set reconciliation."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import publication, sep_reconciliation as recon, store


def _fp(*rows):
    fp = recon._Fingerprint()
    for row in rows:
        fp.add(*row)
    return fp


def test_keyset_fingerprint_is_order_independent_and_multiplicity_sensitive():
    a = ("P:1", "2020-01-02", "AAA")
    b = ("P:2", "2020-01-02", "BBB")
    assert _fp(a, b).digest() == _fp(b, a).digest()
    assert _fp(a, b).digest() != _fp(a, b, b).digest()


def test_stable_equal_complete_year_passes_without_repair(monkeypatch):
    source = _fp(("P:1", "2020-01-02", "AAA"),
                 ("P:2", "2020-01-02", "BBB"))
    local = _fp(("P:2", "2020-01-02", "BBB"),
                ("P:1", "2020-01-02", "AAA"))
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
    assert result.digest == source.digest()
    assert result.publication_version == 9


@pytest.mark.parametrize(("source", "local", "case"), [
    pytest.param(
        _fp(("P:1", "2020-01-02", "AAA")),
        _fp(), "vendor-deletion-or-local-extra", id="row-count-drift"),
    pytest.param(
        _fp(("P:1", "2020-01-02", "AAA")),
        _fp(("P:2", "2020-01-02", "BBB")),
        "identity-or-key-substitution", id="same-count-different-key"),
])
def test_complete_year_keyset_drift_refuses_instead_of_guessing(
        monkeypatch, source, local, case):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "_source_fingerprint", lambda *a, **k: source)
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: local)
    with pytest.raises(recon.SepKeysetDrift, match="Refusing to guess"):
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
        lambda *a, **k: (_ for _ in ()).throw(recon.SepKeysetDrift("drift")))
    monkeypatch.setattr(
        recon, "_save_result",
        lambda *a, **k: pytest.fail("failed proof must not advance cursor"))
    with pytest.raises(recon.SepKeysetDrift, match="drift"):
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
    result = recon.ReconciliationResult(
        year=2024, start="2024-01-01", end="2024-12-31",
        rows=123, digest="a" * 64, publication_version=7)
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
            digest=(f"{year:04d}" * 16)[:64], publication_version=11)

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
            raise recon.SepKeysetDrift("2025 drift")
        return recon.ReconciliationResult(
            year=year, start=start, end=end, rows=1,
            digest="b" * 64, publication_version=12)

    monkeypatch.setattr(recon, "reconcile_year", check)
    monkeypatch.setattr(
        recon, "_save_result",
        lambda conn, result, *, checked_on: saved.append(result.year))
    with pytest.raises(recon.SepKeysetDrift, match="2025 drift"):
        recon.reconcile_all(object(), fetch=object(), through="2026-08-18")
    assert checked == [2024, 2025]
    assert saved == [2024]
