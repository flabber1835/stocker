from backtester.sp500_pit_alias_resolution import _overlap, _split_symbols, build_discovery


def test_split_symbols_normalizes_delimiters():
    assert _split_symbols("ABC, DEF|GHI;JKL/MNO") == {"ABC", "DEF", "GHI", "JKL", "MNO"}


def test_overlap_uses_actual_price_sessions_and_exclusive_membership_end():
    sessions = ["2000-01-03", "2000-01-04", "2000-01-05"]
    assert _overlap("2000-01-04", "2000-01-05", sessions) == ("2000-01-04", "2000-01-04")
    assert _overlap("1999-12-01", "2000-01-03", sessions) is None


def test_discovery_expands_through_permaticker_group():
    rows = [
        {"ticker": "OLD", "permaticker": "1", "relatedtickers": "LEGACY"},
        {"ticker": "NEW", "permaticker": "1", "relatedtickers": ""},
        {"ticker": "OTHER", "permaticker": "2", "relatedtickers": ""},
    ]
    by_symbol, by_perm, perms = build_discovery(rows)
    assert by_perm["1"] == {"OLD", "NEW"}
    assert by_symbol["LEGACY"] == {"OLD", "NEW"}
    assert perms["LEGACY"] == {"1"}
