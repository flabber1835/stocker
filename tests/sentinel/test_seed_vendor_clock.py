from __future__ import annotations

from types import SimpleNamespace

from sentinel.feed import ingest, recovery


def _run(monkeypatch, *, boundary):
    seen = {}
    tracked = object()

    def seed_source(fetch, *, final_hi, update_ceiling):
        seen["fetch"] = fetch
        seen["final_hi"] = final_hi
        seen["update_ceiling"] = update_ceiling
        return tracked, tracked

    monkeypatch.setattr(ingest, "_seed_source", seed_source)
    monkeypatch.setattr(
        ingest, "_seed_authority",
        lambda **_kwargs: SimpleNamespace())
    progress = SimpleNamespace(run_id="seed-regression")
    monkeypatch.setattr(
        ingest, "_ordinary_seed_generation",
        lambda *_args, **_kwargs: progress)

    fetch = object()
    plan = recovery.FullReseedPlan(
        "2025-01-02", "2026-09-02", ())
    result, returned_tracker = ingest._run_seed_generation(
        object(), recovery_plan=plan, fetch=fetch,
        final_hi="2026-09-02", boundary=boundary)
    assert result is progress
    assert returned_tracker is tracked
    assert seen["fetch"] is fetch
    assert seen["final_hi"] == "2026-09-02"
    return seen["update_ceiling"]


def test_production_seed_uses_captured_vendor_boundary(monkeypatch):
    assert _run(monkeypatch, boundary="2026-09-03") == "2026-09-03"


def test_injected_seed_keeps_market_end_as_deterministic_update_ceiling(
        monkeypatch):
    assert _run(monkeypatch, boundary=None) == "2026-09-02"
