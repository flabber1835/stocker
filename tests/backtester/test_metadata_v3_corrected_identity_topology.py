from backtester import rebuild_historical_metadata_identity_topology_v3 as m


def test_corrected_topology_merges_false_fragments_and_preserves_real_boundaries():
    guard = [
        {"security_id": "N1", "ticker": "AAA", "first_session": "2006-01-03", "last_session": "2007-06-29"},
        {"security_id": "N2", "ticker": "AAA", "first_session": "2007-07-02", "last_session": "2008-12-31"},
        {"security_id": "N3", "ticker": "BBB", "first_session": "2006-01-03", "last_session": "2008-12-31"},
    ]
    by_ticker = m.by_ticker_guard(guard)

    # Old CIK-driven fragments inside one continuous corrected episode collapse.
    sid, disposition, overlaps = m.map_interval(
        "AAA", "2006-03-01", "2006-04-01", by_ticker
    )
    assert sid == "N1" and disposition == "CONTAINED" and overlaps == ["N1"]
    sid, disposition, _ = m.map_interval(
        "AAA", "2007-01-01", "2007-01-31", by_ticker
    )
    assert sid == "N1" and disposition == "CONTAINED"

    # An old episode spanning a real corrected terminal/relisting boundary is a blocker.
    sid, disposition, overlaps = m.map_interval(
        "AAA", "2007-06-15", "2007-07-15", by_ticker
    )
    assert sid == ""
    assert disposition == "CROSSES_CORRECTED_BOUNDARY"
    assert overlaps == ["N1", "N2"]

    # Dated evidence inside an episode maps to it without consulting CIK.
    assert m.allocate_date("AAA", "2006-05-01", by_ticker) == "N1"
    assert m.allocate_date("AAA", "2007-08-01", by_ticker) == "N2"

    # Pre-listing evidence may seed only the first safely reachable episode.
    assert m.allocate_date("BBB", "2005-12-15", by_ticker) == "N3"


def test_corrected_topology_never_uses_cik_to_create_episode():
    guard = [
        {"security_id": "N1", "ticker": "MLS", "first_session": "2006-01-03", "last_session": "2007-12-31"},
    ]
    by_ticker = m.by_ticker_guard(guard)
    # The same ticker remains the same security episode regardless of what CIK a filing carries.
    assert m.allocate_date("MLS", "2007-02-08", by_ticker) == "N1"
    assert m.allocate_date("MLS", "2007-03-30", by_ticker) == "N1"
