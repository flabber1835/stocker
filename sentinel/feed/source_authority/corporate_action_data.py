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
        "schema": "sentinel.corporate-action-adjudication/1",
        "authority_id": "tri-2026-05-04-return-of-capital-v1",
        "event_id": "TRI:2026-05-04:dividend",
        "ticker": "TRI",
        "source_action_date": "2026-05-04",
        "effective_session": "2026-05-04",
        "source_action": "dividend",
        "security_mapping": "sharadar-ticker-at-effective-session",
        "stale_source_amount": "1.36",
        "final_cash_amount": "1.435518",
        "currency": "USD",
        "primary_source_kind": "issuer-final-terms",
        "source_url": (
            "https://ir.thomsonreuters.com/news-releases/news-release-details/"
            "thomson-reuters-announces-cash-distribution-share-and-share"
        ),
        "source_published_at": "2026-05-01T16:30:00-04:00",
        "source_evidence_text": (
            "Participating shareholders to receive cash distribution of "
            "US$1.435518 per common share"
        ),
        "source_content_sha256": (
            "984deaf590f97905becab406a14eb66bce78db8275e66a7f0077202e27401d9d"
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
            "5d485827600bfd9d25a3a6c840921346204d1841decb41f9a17c93d8a92c63ee"
        ),
    },
)

__all__ = ["CASH_ADJUDICATION_AUTHORITIES", "DISPUTED_CASH_EVENTS"]
