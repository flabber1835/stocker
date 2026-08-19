"""Explicit Sharadar provider/transport boundary.

"Sharadar" names the data authority, not one wire protocol. Sentinel production
currently speaks Nasdaq Data Link Tables v3. Sharadar's newer direct API is a
different protocol and must get a separate adapter; changing a base URL on the
NDL implementation is intentionally not a supported migration path.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Protocol

from sentinel.feed import sharadar


class SharadarSource(Protocol):
    """Business-facing source contract above any delivery protocol."""

    provider: str
    protocol: str

    def fetch_table(self, table: str,
                    params: Mapping[str, str] | None = None) -> Iterable[dict]:
        ...


class NasdaqDataLinkSharadarSource:
    """Current production adapter: Nasdaq Data Link Tables API v3."""

    provider = "Sharadar"
    protocol = "nasdaq-data-link-tables-v3"

    def fetch_table(self, table: str,
                    params: Mapping[str, str] | None = None, **kwargs):
        return sharadar.fetch_table(table, params, **kwargs)


NASDAQ_DATA_LINK = NasdaqDataLinkSharadarSource()


__all__ = ["NASDAQ_DATA_LINK", "NasdaqDataLinkSharadarSource", "SharadarSource"]
