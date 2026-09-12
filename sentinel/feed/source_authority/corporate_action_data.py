"""Immutable reviewed exceptional corporate-action authority records.

These records are deliberately code-reviewed data, not a runtime-editable
configuration surface.  A source fact that can change historical strategy
economics must be reproducible from a commit, self-hashed, and tied to the exact
vendor event it adjudicates.
"""
from __future__ import annotations

# Events in this set are KNOWN DISPUTES.  Their ordinary Sharadar value is never
# allowed to pass merely because ACTIONS and SEP agree with each other.  Keeping
# the flag independent of the authority record makes a missing reviewed record a
# fail-closed state instead of silently restoring Sharadar authority.
DISPUTED_CASH_EVENTS = (
    {
        "event_id": "TRI:2026-05-04:dividend",
        "ticker": "TRI",
        "source_action_date": "2026-05-04",
        "effective_session": "2026-05-04",
        "source_action": "dividend",
    },
)

CASH_ADJUDICATION_AUTHORITIES = (
    {
        "schema": "sentinel.corporate-action-adjudication/2",
        "authority_id": "tri-2026-05-04-return-of-capital-v2",
        "event_id": "TRI:2026-05-04:dividend",
        "ticker": "TRI",
        "source_action_date": "2026-05-04",
        "effective_session": "2026-05-04",
        "source_action": "dividend",
        "security_mapping": "sharadar-ticker-at-effective-session",
        "stale_source_amount": "1.36",
        "final_cash_amount": "1.435518",
        "cash_entitlement_basis": "RAW_PRE_CONSOLIDATION_SHARE",
        "new_shares_per_old_share": "0.984560",
        "currency": "USD",
        "primary_source_kind": "issuer-final-terms",
        "source_url": (
            "https://ir.thomsonreuters.com/news-releases/news-release-details/"
            "thomson-reuters-announces-cash-distribution-share-and-share"
        ),
        "source_published_at": "2026-05-01T16:30:00-04:00",
        "source_evidence_text": (
            "Participating shareholders to receive cash distribution of "
            "US$1.435518 per common share; "
            "1 pre-consolidated share for 0.984560 post-consolidated shares"
        ),
        "source_content_sha256": (
            "c46672f72bed7fb703d633bb900ec7f960e633bc48e41db5fb6c4805c0741794"
        ),
        "corroborating_sources": [
            "https://www.sec.gov/Archives/edgar/data/1075124/"
            "000119312526201824/d139216dex991.htm",
            "https://m.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-296",
        ],
        "source_priority": (
            "issuer-final-terms>sec-filing>exchange-final-notice>sharadar"
        ),
        "record_sha256": (
            "7e8db148df1a136973871e800131aea7a6c127f1cb6afbd323109ea39b6e3df0"
        ),
    },
)

__all__ = ["CASH_ADJUDICATION_AUTHORITIES", "DISPUTED_CASH_EVENTS"]
