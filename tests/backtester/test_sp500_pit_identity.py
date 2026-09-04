from backtester.sp500_pit_identity import bind_membership
from backtester.strict_pit_metadata import CausalIdentityResolver, IdentityEpisode


def _row(ticker, start, end="", confidence="secondary_historical"):
    return {
        "ticker": ticker,
        "member_from": start,
        "member_until_exclusive": end,
        "confidence": confidence,
    }


def _resolver(mapping):
    episodes = {}
    for ticker, starts in mapping.items():
        episodes[ticker] = [
            IdentityEpisode(ticker, first, sid, episode, None)
            for episode, (first, sid) in enumerate(starts)
        ]
    return CausalIdentityResolver(episodes)


def test_single_episode_binds_full_membership():
    resolver = _resolver({"AAA": [("1997-01-02", "sid1")]})
    bindings, worklist, counts = bind_membership([_row("AAA", "2001-01-01", "2005-01-01")], resolver)
    assert len(bindings) == 1
    assert bindings[0]["security_id"] == "sid1"
    assert bindings[0]["binding_from"] == "2001-01-01"
    assert bindings[0]["binding_until_exclusive"] == "2005-01-01"
    assert not worklist
    assert counts["fully_bound_intervals"] == 1


def test_membership_before_local_tape_is_explicit_prefix_gap():
    resolver = _resolver({"AAA": [("1997-06-01", "sid1")]})
    bindings, worklist, counts = bind_membership([_row("AAA", "1996-01-02", "2000-01-01")], resolver)
    assert bindings[0]["binding_from"] == "1997-06-01"
    assert bindings[0]["binding_status"] == "PREFIX_UNBOUND_THEN_CAUSAL_IDENTITY"
    assert worklist[0]["reason"] == "MEMBERSHIP_PRECEDES_LOCAL_SEP_TAPE"
    assert counts["prefix_unbound_intervals"] == 1


def test_identity_absent_for_entire_membership_is_unresolved():
    resolver = _resolver({"AAA": [("2005-01-01", "sid1")]})
    bindings, worklist, counts = bind_membership([_row("AAA", "1996-01-02", "2000-01-01")], resolver)
    assert not bindings
    assert worklist[0]["reason"] == "NO_CAUSAL_IDENTITY_DURING_MEMBERSHIP"
    assert counts["unresolved_intervals"] == 1


def test_ticker_missing_from_identity_domain_is_unresolved():
    resolver = _resolver({})
    bindings, worklist, counts = bind_membership([_row("MISSING", "2001-01-01", "2002-01-01")], resolver)
    assert not bindings
    assert worklist[0]["reason"] == "NO_CAUSAL_IDENTITY"
    assert counts["unresolved_intervals"] == 1


def test_membership_crossing_causal_relisting_splits_binding():
    resolver = _resolver({"AAA": [("1997-01-02", "sid1"), ("2003-06-01", "sid2")]})
    bindings, worklist, counts = bind_membership([_row("AAA", "2001-01-01", "2005-01-01")], resolver)
    assert [row["security_id"] for row in bindings] == ["sid1", "sid2"]
    assert bindings[0]["binding_until_exclusive"] == "2003-06-01"
    assert bindings[1]["binding_from"] == "2003-06-01"
    assert any(row["reason"] == "MULTIPLE_CAUSAL_SECURITY_EPISODES" for row in worklist)
    assert counts["multi_episode_intervals"] == 1
