from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from sentinel.feed import sep_reconciliation as recon
from sentinel.feed import snapshot_source


def test_production_rotation_reconciles_actions_before_sep_partition(monkeypatch):
    order = []
    action_calls = []

    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "YEARS_PER_RUN", 1)
    monkeypatch.setattr(
        recon, "_production_source_ceiling",
        lambda fetch, market_through: market_through)
    monkeypatch.setattr(
        recon.maintenance, "reconcile_actions_if_due",
        lambda conn, **kwargs: (
            order.append("actions"), action_calls.append(kwargs)))
    monkeypatch.setattr(
        recon.maintenance, "reconcile_sep_mutations",
        lambda conn, **kwargs: order.append("sep_mutations"))
    monkeypatch.setattr(
        recon, "_next_year",
        lambda conn: (2026, dt.date(2026, 1, 1), dt.date(2026, 9, 4)))

    def fake_reconcile_year(*_args, **_kwargs):
        order.append("sep_partition")
        return SimpleNamespace(year=2026)

    monkeypatch.setattr(recon, "reconcile_year", fake_reconcile_year)
    monkeypatch.setattr(recon, "_save_result", lambda *args, **kwargs: None)

    recon.reconcile_next(
        object(), fetch=snapshot_source.fetch_table, through="2026-09-04")

    assert order == ["actions", "sep_mutations", "sep_partition"]
    assert action_calls == [{"through": "2026-09-04"}]


def test_injected_rotation_does_not_gain_production_actions_authority(monkeypatch):
    calls = []

    def injected(*_args, **_kwargs):
        return iter(())

    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "YEARS_PER_RUN", 1)
    monkeypatch.setattr(
        recon, "_production_source_ceiling",
        lambda fetch, market_through: market_through)
    monkeypatch.setattr(
        recon.maintenance, "reconcile_actions_if_due",
        lambda *args, **kwargs: calls.append("actions"))
    monkeypatch.setattr(
        recon.maintenance, "reconcile_sep_mutations",
        lambda *args, **kwargs: calls.append("sep_mutations"))
    monkeypatch.setattr(
        recon, "_next_year",
        lambda conn: (2026, dt.date(2026, 1, 1), dt.date(2026, 9, 4)))
    monkeypatch.setattr(
        recon, "reconcile_year",
        lambda *args, **kwargs: SimpleNamespace(year=2026))
    monkeypatch.setattr(recon, "_save_result", lambda *args, **kwargs: None)

    recon.reconcile_next(object(), fetch=injected, through="2026-09-04")

    assert calls == []
