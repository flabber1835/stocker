"""Issues #252/#253: source rows must stay inside their requested session envelope."""
from __future__ import annotations

import pytest

from sentinel.feed import (
    authority, coherence, recent_reconciliation, renormalize, session_envelope,
    sep_reconciliation, sharadar,
)


def _sep(session: str, ticker: str = "AAA") -> dict:
    return {
        "ticker": ticker,
        "date": session,
        "open": 10.0,
        "close": 10.0,
        "closeunadj": 10.0,
        "volume": 1000.0,
    }


def _sfp(session: str, ticker: str = "SPY") -> dict:
    return {
        "ticker": ticker,
        "date": session,
        "open": 10.0,
        "close": 10.0,
        "closeadj": 10.0,
        "closeunadj": 10.0,
    }


class _NoDatabase:
    """Proves envelope refusal precedes staging, comparison, and cursor effects."""

    def cursor(self, *_args, **_kwargs):
        raise AssertionError("database touched before source envelope validation")


def test_exact_inclusive_xnys_boundaries_are_accepted():
    rows = [_sep("2026-08-21"), _sep("2026-08-24", "BBB")]
    assert list(session_envelope.validate_rows(
        rows, source="SEP", date_from="2026-08-21", date_to="2026-08-24",
        operation="boundary-regression")) == rows


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ({"ticker": "AAA", "date": None}, "missing_session"),
        ({"ticker": "AAA", "date": "not-a-date"}, "malformed_session"),
        (_sep("2026-08-20"), "session_before_request"),
        (_sep("2026-08-25"), "session_after_request"),
        (_sep("2026-08-22"), "non_xnys_session"),
    ],
)
def test_invalid_session_refuses_with_bounded_deterministic_evidence(row, reason):
    with pytest.raises(session_envelope.SourceSessionEnvelopeViolation) as caught:
        list(session_envelope.validate_rows(
            [row], source="SEP", date_from="2026-08-21",
            date_to="2026-08-24", operation="annual-reconciliation"))
    evidence = caught.value.evidence.to_dict()
    assert evidence["schema"] == "sentinel.source-session-envelope/1"
    assert evidence["source"] == "SEP"
    assert evidence["operation"] == "annual-reconciliation"
    assert evidence["request_interval"] == ["2026-08-21", "2026-08-24"]
    assert evidence["row_number"] == 1
    assert evidence["reason"] == reason
    assert len(str(caught.value)) < 1000


def test_two_identical_off_window_sep_traversals_refuse_before_fingerprinting():
    calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        return [_sep("2026-08-20")]

    guarded = authority.StableSharadarFetch(
        fetch, after_session="2026-08-20", operation="daily-sep")
    with pytest.raises(
            session_envelope.SourceSessionEnvelopeViolation,
            match="session_before_request"):
        list(guarded(
            sharadar.SEP,
            {"date.gte": "2026-08-21", "date.lte": "2026-08-24"}))
    # The first traversal is rejected before it can become the first stable
    # fingerprint. Repetition cannot turn the same invalid row into authority.
    assert calls == 1


def test_failed_observation_retries_cleanly_without_partial_stability_state():
    calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        if calls == 1:
            return [_sep("2026-08-20")]
        return [_sep("2026-08-21"), _sep("2026-08-24", "BBB")]

    guarded = authority.StableSharadarFetch(
        fetch, after_session="2026-08-20", operation="retry-regression")
    params = {"date.gte": "2026-08-21", "date.lte": "2026-08-24"}
    with pytest.raises(session_envelope.SourceSessionEnvelopeViolation):
        list(guarded(sharadar.SEP, params))
    replay = list(guarded(sharadar.SEP, params))
    assert [row["date"] for row in replay] == ["2026-08-21", "2026-08-24"]
    assert calls == 3   # one refused traversal, then two agreeing valid ones


def test_primary_seed_sep_refuses_before_stability_or_candidate_mutation():
    calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        return [_sep("2026-08-22")]

    guarded = coherence.StableSharadarFetch(fetch, seed_mode=True)
    with pytest.raises(
            session_envelope.SourceSessionEnvelopeViolation,
            match="non_xnys_session"):
        list(guarded(
            sharadar.SEP,
            {"date.gte": "2026-08-21", "date.lte": "2026-08-24"}))
    assert calls == 1


def test_primary_sfp_reference_path_refuses_before_its_first_fingerprint():
    calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SFP
        calls += 1
        return [_sfp("2026-08-25")]

    guarded = coherence.StableSharadarFetch(fetch)
    with pytest.raises(
            session_envelope.SourceSessionEnvelopeViolation,
            match="session_after_request"):
        guarded(
            sharadar.SFP,
            {"ticker": "SPY,BIL", "date.gte": "2026-08-21",
             "date.lte": "2026-08-24"})
    assert calls == 1
    assert guarded._sfp_first is None


@pytest.mark.parametrize("off_session", ["2025-12-31", "2027-01-04"])
def test_annual_reconciliation_refuses_before_staging_or_local_comparison(
        off_session):
    calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        return [_sep(off_session)]

    with pytest.raises(session_envelope.SourceSessionEnvelopeViolation):
        sep_reconciliation._source_fingerprint(
            _NoDatabase(), fetch=fetch,
            start="2026-01-02", end="2026-12-31",
            observation_ceiling="2026-12-31")
    assert calls == 1


def test_recent_complete_export_refuses_future_row_before_staging(
        monkeypatch):
    monkeypatch.setattr(
        recent_reconciliation.snapshot_export, "fetch_complete_sep",
        lambda *, start, end: ([_sep("2026-08-25")], {"source": "test"}))

    with pytest.raises(session_envelope.SourceSessionEnvelopeViolation,
            match="session_after_request"):
        sep_reconciliation._source_fingerprint(
            _NoDatabase(), fetch=recent_reconciliation._export_fetch,
            start="2026-08-21", end="2026-08-24",
            observation_ceiling="2026-08-24")


def test_renormalization_refuses_stable_off_window_history_before_replay():
    calls = 0

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        return [_sep("2026-08-20")]

    with pytest.raises(
            session_envelope.SourceSessionEnvelopeViolation,
            match="session_before_request"):
        list(renormalize._stable_sep(fetch, "2026-08-21", "2026-08-24"))
    assert calls == 1


def test_valid_sep_stability_protocol_is_unchanged_after_envelope_validation():
    calls = 0
    rows = [_sep("2026-08-21"), _sep("2026-08-24", "BBB")]

    def fetch(table, params=None, **_kwargs):
        nonlocal calls
        assert table == sharadar.SEP
        calls += 1
        return list(rows)

    guarded = authority.StableSharadarFetch(
        fetch, after_session="2026-08-20", operation="renormalization")
    replay = list(guarded(
        sharadar.SEP,
        {"date.gte": "2026-08-21", "date.lte": "2026-08-24"}))
    assert replay == rows
    assert calls == 2
