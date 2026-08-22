"""Session-effective SEC issuer authority for Wealth Core replay.

This is an overlay on the existing decision-metadata timeline. It deliberately
leaves the observed Sharadar metadata intact while replacing only the issuer
identity used by eligibility and bars. In SEC-PIT mode, present-day
``relatedtickers`` therefore cannot drive a historical issuer-family decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimeline,
    FeedError,
    SecurityMeta,
)
from stock_strategy_shared.wealth_core.issuer_identity import (
    IssuerResolution,
    SecIssuerResolver,
)


@dataclass(frozen=True)
class SecPitSecurityMeta(SecurityMeta):
    """SecurityMeta whose issuer key is an explicit PIT authority."""

    pit_issuer_key: str = ""
    pit_issuer_source: str = ""
    pit_issuer_evidence: IssuerResolution | None = None

    def issuer_key(self) -> tuple[str | None, str | None]:
        return self.pit_issuer_key, self.pit_issuer_source


class SecIssuerMetadataTimeline:
    """Decorate a metadata timeline with causal SEC issuer identity.

    The wrapper is intentionally duck-compatible with ``DecisionMetadataTimeline``
    so the existing Feed/run path remains unchanged. The canonical row excludes
    Sharadar ``related_tickers`` because that field is no longer path-driving in
    this mode; instead it records the effective issuer key and accession-level
    SEC provenance (or the explicit permaticker fallback).
    """

    def __init__(
        self,
        base: DecisionMetadataTimeline,
        resolver: SecIssuerResolver,
    ) -> None:
        self.base = base
        self.resolver = resolver
        self.sessions = base.sessions

    @property
    def security_ids(self) -> frozenset[str]:
        return self.base.security_ids

    def _overlay(self, session: str, meta: SecurityMeta) -> SecPitSecurityMeta:
        try:
            resolution = self.resolver.issuer_key_for(
                meta.ticker,
                session,
                permaticker=meta.permaticker,
                evidence_not_before=meta.first_session,
            )
        except ValueError as exc:
            raise FeedError(
                f"SEC PIT issuer identity unresolved for {meta.security_id!r} "
                f"({meta.ticker!r}) on {session}: {exc}"
            ) from exc

        return SecPitSecurityMeta(
            security_id=meta.security_id,
            ticker=meta.ticker,
            category=meta.category,
            permaticker=meta.permaticker,
            related_tickers=meta.related_tickers,
            first_session=meta.first_session,
            last_session=meta.last_session,
            exchange=meta.exchange,
            exchange_authoritative=meta.exchange_authoritative,
            pit_issuer_key=resolution.issuer_key,
            pit_issuer_source=resolution.source,
            pit_issuer_evidence=resolution.evidence,
        )

    def metadata_for(self, session: str, security_id: str) -> SecPitSecurityMeta | None:
        meta = self.base.metadata_for(session, security_id)
        return None if meta is None else self._overlay(session, meta)

    def session_map(self, session: str) -> dict[str, SecPitSecurityMeta]:
        # Delegate first so missing measured-session snapshots retain the base
        # fail-closed behavior.
        base_map = self.base.session_map(session)
        return {sid: self._overlay(session, meta) for sid, meta in base_map.items()}

    def canonical_row(self, session: str, security_id: str):
        meta = self.metadata_for(session, security_id)
        if meta is None:
            return [security_id, None]

        evidence = meta.pit_issuer_evidence
        issuer_authority = [
            meta.pit_issuer_key,
            meta.pit_issuer_source,
            None
            if evidence is None
            else [
                evidence.ticker,
                evidence.issuer_cik,
                evidence.filing_date.isoformat(),
                evidence.accession_number,
                evidence.document_type,
                evidence.archive,
                evidence.source_member,
                evidence.source_row,
            ],
        ]
        row = [
            security_id,
            meta.ticker,
            meta.category,
            meta.permaticker,
            issuer_authority,
            meta.first_session,
            meta.last_session,
        ]
        if meta.exchange_authoritative:
            row.extend([meta.exchange, True])
        return row

    def population_evidence(self) -> dict[str, int]:
        return self.base.population_evidence()


__all__ = ["SecIssuerMetadataTimeline", "SecPitSecurityMeta"]
