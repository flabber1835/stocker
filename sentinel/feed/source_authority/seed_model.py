"""Exact historical SEP eligible-set coverage from stable TICKERS."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from stock_strategy_shared.wealth_core.eligibility import is_common_equity
from .exception_data import _SEED_COVERAGE_EXCEPTION_ROWS
from .dates import SourceAuthorityRefused


@dataclass(frozen=True)
class SeedListing:
    permaticker: str
    ticker: str
    category: str
    first_session: str
    last_session: str

    @property
    def common_equity(self) -> bool:
        return is_common_equity(self.category)

    def covers(self, session: str) -> bool:
        return self.first_session <= session <= self.last_session


@dataclass(frozen=True)
class SeedCoverageException:
    session: str
    permaticker: str
    ticker: str
    category: str
    first_session: str
    first_observed: str
    reason: str


_EXCEPTION_REASON = (
    "reviewed Sharadar secondary-class unit source-onset sparsity around "
    "TICKERS firstpricedate"
)


def _exception(session, permaticker, ticker, category, first_session,
               first_observed):
    return SeedCoverageException(
        session=session, permaticker=str(permaticker), ticker=ticker,
        category=category, first_session=first_session,
        first_observed=first_observed, reason=_EXCEPTION_REASON)


_SEED_COVERAGE_EXCEPTIONS = tuple(
    _exception(*row) for row in _SEED_COVERAGE_EXCEPTION_ROWS
)
SEED_COVERAGE_EXCEPTIONS = MappingProxyType({
    (item.session, item.permaticker): item
    for item in _SEED_COVERAGE_EXCEPTIONS
})


class SeedListingProjection:
    """Stable TICKERS listing/category projection used as seed denominator."""

    def __init__(self, rows: Iterable[Mapping], *, source_digest: str):
        records = []
        for raw in rows:
            row = dict(raw)
            permaticker = str(row.get("permaticker") or "").strip()
            ticker = str(row.get("ticker") or "").strip().upper()
            category = str(row.get("category") or "").strip()
            first = str(row.get("firstpricedate") or "")[:10]
            last = str(row.get("lastpricedate") or "")[:10]
            if is_common_equity(category) and not (permaticker and ticker):
                raise SourceAuthorityRefused(
                    "stable TICKERS contains a common-equity row without exact "
                    "permanent identity/ticker")
            if not (permaticker and ticker and first and last):
                continue
            records.append(SeedListing(
                permaticker=permaticker, ticker=ticker, category=category,
                first_session=first, last_session=last))
        if not records:
            raise SourceAuthorityRefused(
                "stable TICKERS supplied no listing projection for seed coverage")
        self.records = tuple(sorted(
            records,
            key=lambda item: (
                item.first_session, item.last_session,
                item.permaticker, item.ticker, item.category)))
        by_ticker: dict[str, list[SeedListing]] = {}
        for item in self.records:
            by_ticker.setdefault(item.ticker, []).append(item)
        self.by_ticker = {key: tuple(value) for key, value in by_ticker.items()}
        self.source_digest = str(source_digest)

    def active(self, session: str) -> dict[str, SeedListing]:
        by_identity: dict[str, list[SeedListing]] = {}
        for item in self.records:
            if item.covers(session):
                by_identity.setdefault(item.permaticker, []).append(item)
        out = {}
        for permaticker, items in by_identity.items():
            categories = {item.category for item in items}
            eligibility = {item.common_equity for item in items}
            if len(categories) > 1 or len(eligibility) > 1:
                raise SourceAuthorityRefused(
                    f"stable TICKERS has conflicting active category authority "
                    f"for permaticker {permaticker} on {session}")
            out[permaticker] = min(items, key=lambda item: item.ticker)
        return out

    def listing_for(self, permaticker: str, ticker: str,
                    session: str) -> Optional[SeedListing]:
        matches = [item for item in self.by_ticker.get(ticker.upper(), ())
                   if item.permaticker == str(permaticker)
                   and item.covers(session)]
        if not matches:
            return None
        categories = {item.category for item in matches}
        if len(categories) != 1:
            raise SourceAuthorityRefused(
                f"stable TICKERS has conflicting category authority for "
                f"{ticker}/{permaticker} on {session}")
        return min(matches, key=lambda item: (
            item.first_session, item.last_session, item.ticker))

    def unresolved_could_be_common(self, ticker: str, session: str) -> bool:
        return any(item.common_equity and item.covers(session)
                   for item in self.by_ticker.get(ticker.upper(), ()))


def _exception_matches(exception: SeedCoverageException, *, session: str,
                       listing: SeedListing,
                       first_observed: Optional[str]) -> bool:
    return (
        exception.session == session
        and exception.permaticker == listing.permaticker
        and exception.ticker == listing.ticker
        and exception.category == listing.category
        and exception.first_session == listing.first_session
        and exception.first_observed == first_observed
        and exception.reason == _EXCEPTION_REASON
    )


__all__ = [
    "SEED_COVERAGE_EXCEPTIONS", "SeedCoverageException", "SeedListing",
    "SeedListingProjection", "_exception_matches",
]
