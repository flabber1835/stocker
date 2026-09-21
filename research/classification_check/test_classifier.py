from copy import deepcopy

import pytest

from .classifier import Classifier, filing_date


def positive(ticker, filed, issuer="123"):
    return {"ticker": ticker, "filed": filed, "cik": issuer}


def observation(ticker="EXAMPLE", sid="1", issuer="SEC_CIK:123", session="2006-07-05"):
    return dict(ticker=ticker, security_id=sid, issuer_id=issuer, session=session,
                security_type="unknown", security_type_source="OLD",
                security_type_eligible="0", metadata_admitted="0")


@pytest.mark.parametrize("filed,expected", [
    ("29-JUN-2006", "common"), ("10-AUG-2007", "unknown"),
    ("05-JUL-2006", "unknown"), ("2006-07-04", "common"),
])
def test_independent_calendar_oracle(filed, expected):
    model = Classifier([positive("EXAMPLE", filed)], [])
    assert model.apply(observation(), "dates")["security_type"] == expected


def test_earliest_date_is_chronological_and_known_issuer_must_match():
    model = Classifier([positive("EXAMPLE", "01-JAN-2007"),
                        positive("EXAMPLE", "29-JUN-2006")], [])
    assert model.dated("EXAMPLE", "SEC_CIK:123", "2006-07-05") == "common"
    assert model.dated("EXAMPLE", "SEC_CIK:456", "2006-07-05") == "unknown"


def test_only_explicit_episode_links_without_mutating_observations():
    model = Classifier([positive("CHAP", "05-JAN-2006", "1319048")], [])
    row = observation("CHAP1", "214820292338870148", "SEC_UNKNOWN:214820292338870148")
    before = deepcopy(row)
    assert model.apply(row, "dates")["security_type"] == "unknown"
    assert model.apply(row, "combined")["security_type"] == "common"
    assert row == before
    assert model.apply({**row, "security_id": "another-episode"}, "combined")["security_type"] == "unknown"
    assert model.apply({**row, "session": "2006-07-07"}, "combined")["security_type"] == "unknown"


def test_manual_evidence_persists_only_for_explicit_reviewed_interval():
    model = Classifier([], [])
    row = observation("LFCHY", "788900523736619527", "SEC_UNKNOWN:788900523736619527")
    assert model.apply(row, "combined")["security_type"] == "common"
    assert model.apply({**row, "session": "2006-05-30"}, "combined")["security_type"] == "unknown"
    assert model.apply({**row, "session": "2006-05-31"}, "combined")["security_type"] == "common"


def test_invalid_date_and_identity_conflict_refuse():
    with pytest.raises(ValueError):
        filing_date("31-FEB-2006")
    model = Classifier([], [])
    with pytest.raises(ValueError):
        model.apply(observation("LFCHY", "788900523736619527", "SEC_CIK:123"), "combined")


def test_exact_session_noncommon_is_preserved():
    manual = [dict(admission="admitted", buy_date="2006-07-05", evidence_date="2006-06-01",
                   resolved_as="non_common", orion_ticker="EXAMPLE")]
    model = Classifier([positive("EXAMPLE", "01-JUN-2006")], manual)
    assert model.apply(observation(), "dates")["security_type"] == "non_common"


def test_future_and_same_day_manual_admission_refuses():
    for evidence in ("2006-07-05", "2006-07-06"):
        manual = [dict(admission="admitted", buy_date="2006-07-05", evidence_date=evidence,
                       resolved_as="common", orion_ticker="EXAMPLE")]
        with pytest.raises(ValueError):
            Classifier([], manual)


def test_unknown_issuer_uses_only_prior_symbol_evidence():
    model = Classifier([positive("EXAMPLE", "10-AUG-2007")], [])
    assert model.dated("EXAMPLE", "SEC_UNKNOWN:1", "2006-07-05") == "unknown"
    assert model.dated("EXAMPLE", "SEC_UNKNOWN:1", "2007-08-13") == "common"


def test_same_day_alias_evidence_is_not_used():
    model = Classifier([positive("CHAP", "05-JUL-2006", "1319048")], [])
    row = observation("CHAP1", "214820292338870148", "SEC_UNKNOWN:214820292338870148")
    assert model.apply(row, "combined")["security_type"] == "unknown"
    assert model.apply({**row, "session": "2006-07-06"}, "combined")["security_type"] == "common"
