"""The full reconciliation CLI is the safe upgrade path to the SEP CDC cursor."""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace

from scripts import sentinel_reconcile_sep as cli
from sentinel.feed import maintenance, sep_reconciliation


class _Conn:
    def close(self):
        pass


@contextmanager
def _lock(_conn):
    yield


def _result(year, updated):
    return sep_reconciliation.ReconciliationResult(
        year=year, start=f"{year}-01-01", end=f"{year}-12-31", rows=10,
        digest="a" * 64, value_digest="b" * 64,
        max_lastupdated=updated, publication_version=7)


def _common(monkeypatch):
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("SHARADAR_API_KEY", "secret")
    monkeypatch.setattr(cli.sharadar, "validate_config", lambda: None)
    monkeypatch.setattr(cli.sharadar, "_api_key", lambda: "secret")
    monkeypatch.setattr(cli.store, "connect", lambda dsn: _Conn())
    monkeypatch.setattr(cli.store, "require_feed_schema", lambda conn: None)
    monkeypatch.setattr(cli.store, "corpus_write_lock", _lock)


def test_complete_value_proof_earns_initial_mutation_cursor(monkeypatch):
    _common(monkeypatch)
    results = [
        _result(2024, dt.date(2026, 8, 16)),
        _result(2025, dt.date(2026, 8, 18)),
    ]
    monkeypatch.setattr(
        cli.sep_reconciliation, "reconcile_all",
        lambda conn, through: results)
    monkeypatch.setattr(cli.maintenance, "load_sep_cursor", lambda conn: None)
    monkeypatch.setattr(
        cli.publication, "require_current", lambda conn: SimpleNamespace(version=7))
    calls = []

    def establish(conn, *, through, publication_version):
        calls.append((through, publication_version))
        return maintenance.SourceCursor(
            kind="sharadar-sep-lastupdated/v1", processed_through=through,
            publication_version=publication_version)

    monkeypatch.setattr(
        cli.maintenance, "establish_sep_cursor_after_complete_reconciliation",
        establish)
    assert cli.main(["--through", "2026-08-18"]) == 0
    assert calls == [(dt.date(2026, 8, 18), 7)]


def test_failed_historical_value_proof_can_never_create_cursor(monkeypatch):
    _common(monkeypatch)
    monkeypatch.setattr(
        cli.sep_reconciliation, "reconcile_all",
        lambda conn, through: (_ for _ in ()).throw(
            sep_reconciliation.SepValueDrift("old row differs")))
    monkeypatch.setattr(
        cli.maintenance, "establish_sep_cursor_after_complete_reconciliation",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("cursor must not be established after failed proof")))
    assert cli.main(["--through", "2026-08-18"]) == 2


def test_existing_newer_cursor_is_never_moved_backward(monkeypatch):
    _common(monkeypatch)
    results = [_result(2025, dt.date(2026, 8, 17))]
    monkeypatch.setattr(
        cli.sep_reconciliation, "reconcile_all",
        lambda conn, through: results)
    existing = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date(2026, 8, 18), publication_version=8)
    monkeypatch.setattr(cli.maintenance, "load_sep_cursor", lambda conn: existing)
    monkeypatch.setattr(
        cli.maintenance, "establish_sep_cursor_after_complete_reconciliation",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("complete proof must not regress CDC cursor")))
    assert cli.main(["--through", "2026-08-18"]) == 0


def test_future_vendor_update_date_refuses_cursor_bootstrap(monkeypatch):
    _common(monkeypatch)
    monkeypatch.setattr(
        cli.sep_reconciliation, "reconcile_all",
        lambda conn, through: [_result(2026, dt.date(2026, 8, 19))])
    monkeypatch.setattr(cli.maintenance, "load_sep_cursor", lambda conn: None)
    monkeypatch.setattr(
        cli.maintenance, "establish_sep_cursor_after_complete_reconciliation",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("future update date must not become CDC cursor")))
    assert cli.main(["--through", "2026-08-18"]) == 2
