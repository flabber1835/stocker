"""Falsifiers for the conservative free-directory universe boundary."""
from __future__ import annotations

import pytest

from sentinel.feed.alpaca_nasdaq import (
    CATEGORY, DirectoryRefused, parse_directory, reference_row, select_assets,
)


def _file(*rows, other=False):
    header = ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
              "Test Issue|NASDAQ Symbol" if other else
              "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
              "Round Lot Size|ETF|NextShares")
    return "\n".join((header, *rows, "File Creation Time: 2026-10-02"))


def _asset(symbol, id=None, **overrides):
    return {"symbol": symbol, "id": id or symbol, "class": "us_equity",
            "status": "active", "tradable": True, "exchange": "NASDAQ",
            **overrides}


def test_non_etf_class_and_adr_equity_remain_while_explicit_nonstock_is_excluded():
    listed = parse_directory(_file(
        "A|Alpha Inc - Common Stock|Q|N|N|100|N|N",
        "B|Beta Inc - Class A Common Stock|Q|N|N|100|N|N",
        "C|Gamma Inc - Common Stock|Q|N|N|100|Y|N",
        "D|Delta Inc - Warrants on Common Stock|Q|N|N|100|N|N",
        "E|Epsilon Inc - Common Stock|Q|Y|N|100|N|N",
        "F|Foreign Inc - American Depositary Shares representing Ordinary Shares|Q|N|N|100|N|N",
        "G|Gamma Series A Preferred Shares|Q|N|N|100|N|N",
        "H|Index ETN Notes|Q|N|N|100|N|N"), name="nasdaqlisted")
    selected, evidence = select_assets([_asset(s) for s in "ABCDEFGH"], listed, {})
    assert [row["ticker"] for row in selected] == ["A", "B", "F"]
    assert evidence["excluded"] == {"explicit_non_stock_instrument": 3,
                                     "test_or_etf": 2}


def test_ambiguous_depositary_preference_and_equity_units_are_not_common_stock():
    listed = parse_directory(_file(
        "A|Cadiz Inc - Depositary Shares|Q|N|N|100|N|N",
        "B|Bank Inc - Preference Shares|Q|N|N|100|N|N",
        "C|Company Inc - Tangible Equity Units|Q|N|N|100|N|N",
        "D|Foreign Inc - American Depositary Shares|Q|N|N|100|N|N",
        "E|Foreign Inc - Global Depositary Shares|Q|N|N|100|N|N"),
        name="nasdaqlisted")
    selected, evidence = select_assets([_asset(s) for s in "ABCDE"], listed, {})
    assert [row["ticker"] for row in selected] == ["D", "E"]
    assert evidence["excluded"] == {"explicit_non_stock_instrument": 3}


def test_otherlisted_and_exact_asset_intersection():
    other = parse_directory(_file(
        "A|Alpha Inc - Common Stock|N|A|N|100|N|A", other=True),
        name="otherlisted")
    selected, _ = select_assets([_asset("A", exchange="NYSE"), _asset("B")], {}, other)
    assert [row["ticker"] for row in selected] == ["A"]
    assert reference_row(selected[0], first_session="2025-01-01",
                         last_session="2026-10-01")["category"] == CATEGORY


@pytest.mark.parametrize("name", [
    "Example Acquisition Corp - Units",
    "Example Acquisition Corp - Unit",
    "Example Acquisition Corp Units, each consisting of one Class A Ordinary Share",
    "Example Acquisition Corp Units comprised of common shares",
    "Example Acquisition Corp Units composed of common shares",
])
def test_plain_and_bundled_units_do_not_count_as_common_stock_candidates(name):
    listed = parse_directory(_file(
        "A|" + name + "|Q|N|N|100|N|N",
        "B|Unit Corporation - Common Stock|Q|N|N|100|N|N",
        "C|Example Partners LP - Common Units Representing Limited Partnership Interests|Q|N|N|100|N|N"),
        name="nasdaqlisted")
    selected, proof = select_assets([_asset(s) for s in "ABC"], listed, {})
    assert [row["ticker"] for row in selected] == ["B", "C"]
    assert proof["excluded"] == {"explicit_non_stock_instrument": 1}


@pytest.mark.parametrize("bad", [
    "Symbol|Security Name|ETF\nA|Alpha Inc - Common Stock|N",
    _file("A|Alpha Inc - Common Stock|Q|N|N|100|N|N", "A|Again|Q|N|N|100|N|N"),
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nA|Alpha Inc - Common Stock|Q|N|N|100|N|N",
])
def test_malformed_directory_fails_closed(bad):
    with pytest.raises(DirectoryRefused):
        parse_directory(bad, name="nasdaqlisted")


def test_duplicate_alpaca_id_and_cross_directory_symbol_refuse():
    listed = parse_directory(_file("A|Alpha Inc - Common Stock|Q|N|N|100|N|N"),
                             name="nasdaqlisted")
    with pytest.raises(DirectoryRefused):
        select_assets([_asset("A", id="SAME"), _asset("B", id="SAME")], listed, {})
    with pytest.raises(DirectoryRefused):
        select_assets([_asset("A")], listed, listed)
