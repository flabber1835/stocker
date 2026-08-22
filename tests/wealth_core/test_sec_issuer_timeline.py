from datetime import date

import pytest

from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimelineBuilder,
    Feed,
    FeedError,
    SecurityMeta,
    VendorBar,
)
from stock_strategy_shared.wealth_core.issuer_identity import (
    SecIssuerEvidence,
    SecIssuerResolver,
)
from stock_strategy_shared.wealth_core.sec_issuer_timeline import (
    SecIssuerMetadataTimeline,
)


def _evidence(ticker: str, cik: str, accession: str) -> SecIssuerEvidence:
    return SecIssuerEvidence(
        ticker=ticker,
        issuer_cik=cik,
        filing_date=date(2025, 1, 6),
        accession_number=accession,
        document_type="4",
        archive="2025q1_form345.zip",
        source_member="SUBMISSION.tsv",
        source_row=1,
    )


def _timeline(*metas: SecurityMeta):
    builder = DecisionMetadataTimelineBuilder(["2025-01-07"])
    builder.add_snapshot("2025-01-07", {m.security_id: m for m in metas})
    return builder.finish()


def _bar(security_id: str, ticker: str) -> VendorBar:
    return VendorBar(
        session="2025-01-07",
        security_id=security_id,
        ticker=ticker,
        raw_close=20.0,
        raw_open=20.0,
        volume=1_000_000,
    )


def test_feed_uses_sec_cik_not_present_day_relatedtickers():
    a = SecurityMeta(
        security_id="1",
        ticker="AAA",
        category="Domestic Common Stock",
        permaticker="1001",
        related_tickers=("FUTURE_A",),
        first_session="2020-01-01",
    )
    b = SecurityMeta(
        security_id="2",
        ticker="BBB",
        category="Domestic Common Stock Secondary Class",
        permaticker="1002",
        related_tickers=("FUTURE_B",),
        first_session="2020-01-01",
    )
    resolver = SecIssuerResolver(
        [_evidence("AAA", "123", "aaa"), _evidence("BBB", "123", "bbb")]
    )
    timeline = SecIssuerMetadataTimeline(_timeline(a, b), resolver)

    out = Feed({}, metadata_timeline=timeline).advance(
        "2025-01-07", [_bar("1", "AAA"), _bar("2", "BBB")]
    )
    issuer_by_security = {bar.security_id: bar.issuer_id for bar in out.bars}
    assert issuer_by_security == {"1": "CIK:0000000123", "2": "CIK:0000000123"}


def test_unresolved_sec_identity_uses_permaticker_not_relatedtickers():
    meta = SecurityMeta(
        security_id="1",
        ticker="AAA",
        permaticker="1001",
        related_tickers=("FUTURE_A",),
        first_session="2020-01-01",
    )
    timeline = SecIssuerMetadataTimeline(_timeline(meta), SecIssuerResolver([]))

    effective = timeline.metadata_for("2025-01-07", "1")
    assert effective is not None
    assert effective.issuer_key() == ("P:1001", "PERMATICKER_PIT_FALLBACK")
    assert effective.related_tickers == ("FUTURE_A",)


def test_unresolved_without_permaticker_fails_closed_at_timeline_boundary():
    meta = SecurityMeta(
        security_id="1",
        ticker="AAA",
        permaticker=None,
        related_tickers=("FUTURE_A",),
        first_session="2020-01-01",
    )
    timeline = SecIssuerMetadataTimeline(_timeline(meta), SecIssuerResolver([]))

    with pytest.raises(FeedError, match="SEC PIT issuer identity unresolved"):
        timeline.metadata_for("2025-01-07", "1")


def test_canonical_row_hashes_pit_authority_and_provenance_not_relations():
    meta = SecurityMeta(
        security_id="1",
        ticker="AAA",
        category="Domestic Common Stock",
        permaticker="1001",
        related_tickers=("FUTURE_A",),
        first_session="2020-01-01",
    )
    timeline = SecIssuerMetadataTimeline(
        _timeline(meta), SecIssuerResolver([_evidence("AAA", "123", "aaa-accession")])
    )

    row = timeline.canonical_row("2025-01-07", "1")
    rendered = repr(row)
    assert "CIK:0000000123" in rendered
    assert "aaa-accession" in rendered
    assert "2025q1_form345.zip" in rendered
    assert "FUTURE_A" not in rendered
