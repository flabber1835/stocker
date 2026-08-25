"""Sharadar coherence facade with structural TICKERS authority.

The retained implementation remains byte-for-byte reviewable in
:mod:`sentinel.feed._coherence_impl`; this public membrane canonicalizes and
validates TICKERS before the implementation can retain its first fingerprint.
"""
from __future__ import annotations

from sentinel.feed import _coherence_impl as _base
from sentinel.feed import tickers_authority

for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)

_legacy_assert_tickers_metadata = _base.assert_tickers_metadata


def assert_tickers_metadata(rows):
    canonical = tickers_authority.validate(rows)
    return _legacy_assert_tickers_metadata(canonical)


# StableSharadarFetch resolves this name in its defining module at call time.
# Patch that one global as well as exporting the public facade, so seed, daily,
# identity rebuild, and every direct validator share exactly one boundary.
_base.assert_tickers_metadata = assert_tickers_metadata

TickersStructureEvidence = tickers_authority.TickersStructureEvidence
TickersStructureInvalid = tickers_authority.TickersStructureInvalid
