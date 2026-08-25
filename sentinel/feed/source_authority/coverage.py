"""Bounded exact observed-vs-expected historical SEP membership proof."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from sentinel.feed import calendar, sharadar
from .dates import SourceAuthorityRefused, _canonical_key
from .seed_model import (
    SEED_COVERAGE_EXCEPTIONS, SeedListing, SeedListingProjection,
    _exception_matches,
)


class SeedCoverageAccumulator:
    """Bounded exact observed-vs-expected canonical seed membership proof."""

    def __init__(self, projection: SeedListingProjection, resolver,
                 *, exceptions: Mapping = SEED_COVERAGE_EXCEPTIONS):
        self.projection = projection
        self.resolve = resolver
        self.exceptions = dict(exceptions)
        self._dir = tempfile.TemporaryDirectory(prefix="sentinel-seed-coverage-")
        self._db = sqlite3.connect(Path(self._dir.name) / "coverage.sqlite3")
        self._db.execute("PRAGMA journal_mode=OFF")
        self._db.execute("PRAGMA synchronous=OFF")
        self._db.executescript("""
            CREATE TABLE observed (
                session TEXT NOT NULL, permaticker TEXT NOT NULL,
                ticker TEXT NOT NULL, category TEXT NOT NULL,
                eligible INTEGER NOT NULL,
                PRIMARY KEY(session,permaticker)) WITHOUT ROWID;
            CREATE TABLE unresolved_risk (
                session TEXT NOT NULL, ticker TEXT NOT NULL,
                PRIMARY KEY(session,ticker)) WITHOUT ROWID;
            CREATE INDEX observed_identity_session
                ON observed(permaticker,session);
        """)

    def add(self, row: Mapping) -> bool:
        ticker, session = _canonical_key(sharadar.SEP, row)
        permaticker = self.resolve(ticker, session)
        if permaticker is None:
            if self.projection.unresolved_could_be_common(ticker, session):
                self._db.execute(
                    "INSERT OR IGNORE INTO unresolved_risk(session,ticker)"
                    " VALUES (?,?)", (session, ticker))
            return False
        identity = str(permaticker)
        listing = self.projection.listing_for(identity, ticker, session)
        if listing is None:
            self._db.execute(
                "INSERT OR IGNORE INTO unresolved_risk(session,ticker)"
                " VALUES (?,?)", (session, ticker))
            return False
        try:
            self._db.execute(
                "INSERT INTO observed"
                " (session,permaticker,ticker,category,eligible)"
                " VALUES (?,?,?,?,?)",
                (session, identity, ticker, listing.category,
                 int(listing.common_equity)))
        except sqlite3.IntegrityError as exc:
            prior = self._db.execute(
                "SELECT ticker FROM observed WHERE session=? AND permaticker=?",
                (session, identity)).fetchone()
            raise SourceAuthorityRefused(
                f"SEP seed resolves more than one ticker to canonical identity "
                f"{identity} on {session}: {prior[0] if prior else '?'} and "
                f"{ticker}") from exc
        return True

    def require_complete(self, *, date_from: str, date_to: str) -> None:
        sessions = list(calendar.sessions_in_range(date_from, date_to))
        if not sessions:
            raise SourceAuthorityRefused(
                f"seed coverage interval {date_from}..{date_to} has no sessions")
        for session in sessions:
            active = self.projection.active(session)
            expected = {key: item for key, item in active.items()
                        if item.common_equity}
            observed = {str(row[0]) for row in self._db.execute(
                "SELECT permaticker FROM observed"
                " WHERE session=? AND eligible=1 ORDER BY permaticker",
                (session,)).fetchall()}
            missing = sorted(set(expected).difference(observed))
            accepted = []
            for identity in list(missing):
                exception = self.exceptions.get((session, identity))
                if exception is None:
                    continue
                row = self._db.execute(
                    "SELECT MIN(session) FROM observed WHERE permaticker=?",
                    (identity,)).fetchone()
                first_observed = None if row is None else row[0]
                if _exception_matches(
                        exception, session=session, listing=expected[identity],
                        first_observed=first_observed):
                    missing.remove(identity)
                    accepted.append(identity)
            extra = sorted(observed.difference(expected))
            unresolved = [str(row[0]) for row in self._db.execute(
                "SELECT ticker FROM unresolved_risk WHERE session=?"
                " ORDER BY ticker LIMIT 16", (session,)).fetchall()]
            if missing or extra or unresolved:
                raise SourceAuthorityRefused(
                    "Sharadar SEP seed eligible-set coverage refused: "
                    + json.dumps(self._failure_evidence(
                        session=session, active=active, expected=expected,
                        missing=missing, extra=extra, unresolved=unresolved,
                        accepted=accepted),
                        sort_keys=True, separators=(",", ":")))

    def _failure_evidence(self, *, session: str,
                          active: Mapping[str, SeedListing],
                          expected: Mapping[str, SeedListing],
                          missing: Sequence[str], extra: Sequence[str],
                          unresolved: Sequence[str], accepted: Sequence[str]) -> dict:
        observed_eligible = int(self._db.execute(
            "SELECT COUNT(*) FROM observed WHERE session=? AND eligible=1",
            (session,)).fetchone()[0])
        observed_ineligible = {
            str(category): int(count)
            for category, count in self._db.execute(
                "SELECT category,COUNT(*) FROM observed"
                " WHERE session=? AND eligible=0 GROUP BY category"
                " ORDER BY category", (session,)).fetchall()}
        expected_ineligible: dict[str, int] = {}
        for item in active.values():
            if not item.common_equity:
                expected_ineligible[item.category] = (
                    expected_ineligible.get(item.category, 0) + 1)
        missing_ineligible = {
            category: count - observed_ineligible.get(category, 0)
            for category, count in sorted(expected_ineligible.items())
            if count > observed_ineligible.get(category, 0)}

        def keys(values):
            return [{"permaticker": identity,
                     "ticker": expected[identity].ticker
                               if identity in expected else None}
                    for identity in values[:16]]

        return {
            "session": session,
            "source_projection_digest": self.projection.source_digest,
            "expected_eligible": len(expected),
            "received_eligible": observed_eligible,
            "missing_eligible_total": len(missing),
            "missing_eligible": keys(list(missing)),
            "unexpected_eligible_total": len(extra),
            "unexpected_eligible": keys(list(extra)),
            "unresolved_eligible_risk_total": len(unresolved),
            "unresolved_eligible_risk": list(unresolved[:16]),
            "reviewed_exceptions_applied": list(sorted(accepted))[:16],
            "expected_ineligible_by_category": dict(sorted(
                expected_ineligible.items())),
            "received_ineligible_by_category": observed_ineligible,
            "missing_ineligible_by_category": missing_ineligible,
        }

    def close(self) -> None:
        self._db.close()
        self._dir.cleanup()


__all__ = ["SeedCoverageAccumulator"]
