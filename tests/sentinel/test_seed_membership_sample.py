"""Diagnostic sampling must preserve the reviewed full-history contract."""
import pytest

from sentinel.feed import coherence, sharadar, source_authority, universe


def test_context_dependent_onset_exception_stays_with_full_capture():
    first, last = "2025-09-05", "2025-09-08"
    listing = dict(table="SEP", permaticker="645169", ticker="SOCAU",
                   category="Domestic Common Stock Secondary Class",
                   firstpricedate=first, lastpricedate=last)
    calls = []
    bar = dict(ticker="SOCAU", date=last, close=10, closeunadj=10, open=10, volume=100)
    def fetch(table, params):
        assert table == sharadar.SEP
        calls.append(params)
        return [bar] if params["date.gte"] == last else []
    guarded = source_authority.StableSharadarFetch(fetch, seed_mode=True)
    # This unit isolates sampling against already captured authority. Export,
    # bracketing, SQL and publication are covered by test_exported_symbol_identity.
    projection = source_authority.SeedListingProjection([listing], source_digest="a" * 64)
    resolver = universe.IdentityResolver(universe.listings_from_rows([listing]))
    guarded._seed_projection, guarded._seed_resolver = projection, resolver
    guarded.preflight_seed_membership(date_from=first, date_to=last)
    assert calls == [sharadar.date_params(last, last)] * 2
    assert guarded.seed_coverage_evidence is None
    coverage = source_authority.SeedCoverageAccumulator(projection, resolver.resolve)
    try:
        coverage.add(bar)
        evidence = coverage.require_complete(date_from=first, date_to=last)
        assert evidence["reviewed_exceptions_applied_total"] == 1
    finally:
        coverage.close()
    # Missing prices on the sampled non-exception date are still refused.
    guarded._canonical_fetch = lambda *args: []
    with pytest.raises(coherence.SeedHistoryIncomplete, match="SOCAU"):
        guarded.preflight_seed_membership(date_from=first, date_to=last)
