from datetime import date

import pytest

from stock_strategy_shared.wealth_core.issuer_identity import (
    PERMATICKER_PIT_FALLBACK_SOURCE,
    SEC_CIK_SOURCE,
    SecIssuerEvidence,
    SecIssuerResolver,
)


def ev(
    ticker: str,
    cik: str,
    filing_date: str,
    accession: str,
    *,
    row: int = 1,
) -> SecIssuerEvidence:
    return SecIssuerEvidence(
        ticker=ticker,
        issuer_cik=cik,
        filing_date=date.fromisoformat(filing_date),
        accession_number=accession,
        document_type="4",
        archive="fixture.zip",
        source_member="SUBMISSION.tsv",
        source_row=row,
    )


def test_same_day_filing_is_not_causal_but_next_session_is():
    resolver = SecIssuerResolver([ev("ABC", "123", "2025-01-06", "a")])

    assert resolver.resolve("ABC", "2025-01-06") is None
    resolved = resolver.resolve("ABC", "2025-01-07")
    assert resolved is not None
    assert resolved.issuer_key == "CIK:0000000123"
    assert resolved.source == SEC_CIK_SOURCE


def test_future_filing_cannot_change_earlier_resolution():
    base = ev("ABC", "111", "2024-12-20", "old")
    future = ev("ABC", "222", "2025-02-03", "future")

    before = SecIssuerResolver([base]).resolve("ABC", "2025-01-15")
    after_adding_future = SecIssuerResolver([base, future]).resolve("ABC", "2025-01-15")
    assert before == after_adding_future
    assert before is not None
    assert before.issuer_cik == "0000000111"


def test_new_cik_supersedes_only_after_its_filing_date():
    resolver = SecIssuerResolver(
        [
            ev("ABC", "111", "2024-12-20", "old"),
            ev("ABC", "222", "2025-02-03", "new"),
        ]
    )

    assert resolver.resolve("ABC", "2025-02-03").issuer_cik == "0000000111"
    assert resolver.resolve("ABC", "2025-02-04").issuer_cik == "0000000222"


def test_conflicting_ciks_on_latest_date_fail_closed():
    resolver = SecIssuerResolver(
        [
            ev("ABC", "111", "2025-01-02", "a"),
            ev("ABC", "222", "2025-01-02", "b"),
        ]
    )
    assert resolver.resolve("ABC", "2025-01-03") is None


def test_latest_ambiguous_date_does_not_resurrect_stale_cik():
    resolver = SecIssuerResolver(
        [
            ev("ABC", "100", "2024-12-01", "old"),
            ev("ABC", "111", "2025-01-02", "a"),
            ev("ABC", "222", "2025-01-02", "b"),
        ]
    )
    assert resolver.resolve("ABC", "2025-01-03") is None


def test_interval_lower_bound_blocks_stale_ticker_reuse_evidence():
    resolver = SecIssuerResolver([ev("REUSE", "111", "2010-01-04", "old")])

    assert resolver.resolve("REUSE", "2025-01-10") is not None
    assert (
        resolver.resolve(
            "REUSE",
            "2025-01-10",
            evidence_not_before="2024-12-01",
        )
        is None
    )


def test_duplicate_same_cik_date_uses_deterministic_provenance():
    resolver = SecIssuerResolver(
        [
            ev("ABC", "111", "2025-01-02", "z-accession", row=50),
            ev("ABC", "111", "2025-01-02", "a-accession", row=99),
            ev("ABC", "111", "2025-01-02", "a-accession", row=3),
        ]
    )
    resolved = resolver.resolve("ABC", "2025-01-03")
    assert resolved is not None
    assert resolved.accession_number == "a-accession"
    assert resolved.source_row == 3


def test_goog_googl_share_dated_sec_cik_without_future_classes():
    alphabet_cik = "1652044"
    resolver = SecIssuerResolver(
        [
            ev("GOOG", alphabet_cik, "2025-04-01", "goog-2025"),
            ev("GOOGL", alphabet_cik, "2025-04-01", "googl-2025"),
            ev("GOOGM", alphabet_cik, "2026-06-03", "googm-2026"),
            ev("GOOGN", alphabet_cik, "2026-06-03", "googn-2026"),
        ]
    )

    goog = resolver.resolve("GOOG", "2025-04-02")
    googl = resolver.resolve("GOOGL", "2025-04-02")
    assert goog is not None and googl is not None
    assert goog.issuer_key == googl.issuer_key == "CIK:0001652044"
    assert resolver.resolve("GOOGM", "2025-04-02") is None
    assert resolver.resolve("GOOGN", "2025-04-02") is None


def test_future_evidence_for_same_ticker_does_not_rewrite_prior_cik():
    resolver = SecIssuerResolver(
        [
            ev("ABC", "111", "2025-01-02", "old"),
            ev("ABC", "999", "2026-06-03", "future-reorg"),
        ]
    )
    resolved = resolver.resolve("ABC", "2025-12-31")
    assert resolved is not None
    assert resolved.issuer_key == "CIK:0000000111"


def test_unresolved_uses_security_local_permaticker_not_related_tickers():
    resolver = SecIssuerResolver([])
    result = resolver.issuer_key_for("ABC", "2025-01-02", permaticker=12345)

    assert result.issuer_key == "P:12345"
    assert result.source == PERMATICKER_PIT_FALLBACK_SOURCE
    assert result.evidence is None


def test_csv_loader_requires_provenance_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("filing_date,issuer_cik,issuer_trading_symbol\n2025-01-01,1,ABC\n")

    with pytest.raises(ValueError, match="missing required columns"):
        SecIssuerResolver.from_csv(path)
