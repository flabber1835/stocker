from __future__ import annotations

import pytest

from sentinel.feed import coherence, tickers_authority


def _row(**changes):
    row = {
        "table": "SEP",
        "permaticker": "1001",
        "ticker": "AAA",
        "category": "Domestic Common Stock",
        "relatedtickers": "AAA",
        "firstpricedate": "2020-01-02",
        "lastpricedate": "2020-12-31",
        "sector": "Technology",
        "isdelisted": "N",
    }
    row.update(changes)
    return row


def test_identical_duplicates_collapse_before_first_fingerprint():
    canonical = tickers_authority.validate([_row(), _row()])
    assert canonical == [_row()]
    # The public coherence membrane must expose the same policy.
    assert coherence.assert_tickers_metadata([_row(), _row()]) == canonical


def test_conflicting_duplicate_refuses_with_order_independent_evidence():
    rows = [_row(sector="Technology"), _row(sector="Industrials")]
    messages = []
    for candidate in (rows, list(reversed(rows))):
        with pytest.raises(tickers_authority.TickersStructureInvalid) as error:
            tickers_authority.validate(candidate)
        messages.append(str(error.value))
        assert error.value.evidence.invariant == "unique_canonical_identity_pair"
        assert len(error.value.evidence.row_fingerprints) == 2
    assert messages[0] == messages[1]


def test_inclusive_boundary_overlap_between_permanent_identities_refuses():
    with pytest.raises(tickers_authority.TickersStructureInvalid) as error:
        tickers_authority.validate([
            _row(permaticker="1", lastpricedate="2020-06-30"),
            _row(permaticker="2", firstpricedate="2020-06-30",
                 lastpricedate=None),
        ])
    assert error.value.evidence.invariant == "nonoverlapping_ticker_reuse_intervals"


def test_adjacent_nonoverlapping_ticker_reuse_is_accepted():
    rows = tickers_authority.validate([
        _row(permaticker="1", lastpricedate="2020-06-29"),
        _row(permaticker="2", firstpricedate="2020-06-30",
             lastpricedate=None),
    ])
    assert [(row["permaticker"], row["ticker"]) for row in rows] == [
        ("1", "AAA"), ("2", "AAA")]


@pytest.mark.parametrize(
    ("changes", "invariant"),
    [
        ({"ticker": ""}, "nonblank_canonical_identity_key"),
        ({"permaticker": None}, "nonblank_canonical_identity_key"),
        ({"firstpricedate": "2020-13-01"}, "valid_listing_date"),
        ({"firstpricedate": "2021-01-01"}, "ordered_listing_interval"),
        ({"isdelisted": "MAYBE"}, "supported_isdelisted_domain"),
        ({"isdelisted": 2}, "supported_isdelisted_domain"),
    ],
)
def test_malformed_authority_row_refuses_entire_candidate(changes, invariant):
    with pytest.raises(tickers_authority.TickersStructureInvalid) as error:
        tickers_authority.validate([_row(**changes)])
    assert error.value.evidence.invariant == invariant


def test_one_permanent_identity_can_change_ticker_historically():
    rows = tickers_authority.validate([
        _row(permaticker="77", ticker="OLD", lastpricedate="2020-06-29"),
        _row(permaticker="77", ticker="NEW", firstpricedate="2020-06-30",
             lastpricedate=None),
    ])
    assert {(row["permaticker"], row["ticker"]) for row in rows} == {
        ("77", "OLD"), ("77", "NEW")}


def test_non_sep_rows_do_not_define_sentinel_identity():
    rows = tickers_authority.validate([
        _row(),
        _row(table="SFP", permaticker="fund", ticker="FUND"),
    ])
    assert rows == [_row()]
