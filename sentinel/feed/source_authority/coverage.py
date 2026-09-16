"""Bounded exact observed-vs-expected historical SEP membership proof."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from sentinel.feed import calendar, sharadar
from .dates import SourceAuthorityRefused, _canonical_key
from .collisions import bar_witness, require_no_collisions
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
        identity = getattr(getattr(resolver, "__self__", None), "projection", None)
        self.required_native = ({item["permaticker"] for item in identity.applied_alias_rejections}
                                if identity is not None else set())
        self.exceptions = dict(exceptions)
        self._dir = tempfile.TemporaryDirectory(prefix="sentinel-seed-coverage-")
        self._db = sqlite3.connect(Path(self._dir.name) / "coverage.sqlite3")
        self._db.execute("PRAGMA journal_mode=OFF")
        self._db.execute("PRAGMA synchronous=OFF")
        self._db.executescript("""
            CREATE TABLE observed (
                session TEXT NOT NULL, permaticker TEXT NOT NULL,
                ticker TEXT NOT NULL, category TEXT NOT NULL,
                eligible INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(session,permaticker)) WITHOUT ROWID;
            CREATE TABLE identity_collisions (
                session TEXT NOT NULL, permaticker TEXT NOT NULL,
                ticker TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(session,permaticker,ticker)) WITHOUT ROWID;
            CREATE TABLE unresolved_risk (
                session TEXT NOT NULL, ticker TEXT NOT NULL,
                PRIMARY KEY(session,ticker)) WITHOUT ROWID;
            CREATE TABLE unresolved_source (
                session TEXT NOT NULL, ticker TEXT NOT NULL,
                PRIMARY KEY(session,ticker)) WITHOUT ROWID;
            CREATE INDEX observed_identity_session
                ON observed(permaticker,session);
        """)

    def add(self, row: Mapping) -> bool:
        ticker, session = _canonical_key(sharadar.SEP, row)
        permaticker = self.resolve(ticker, session)
        if permaticker is None:
            self._db.execute(
                "INSERT OR IGNORE INTO unresolved_source(session,ticker)"
                " VALUES (?,?)", (session, ticker))
            if self.projection.unresolved_could_be_common(ticker, session):
                self._db.execute(
                    "INSERT OR IGNORE INTO unresolved_risk(session,ticker)"
                    " VALUES (?,?)", (session, ticker))
            return False
        identity = str(permaticker)
        if identity in self.required_native:
            from sentinel.feed.source_aliases import _valid_prices
            if not _valid_prices([row]):
                raise SourceAuthorityRefused(
                    f"rejected-alias native price/volume is invalid: {identity}/{ticker}/{session}")
        listing = self.projection.listing_for(identity, ticker, session)
        if listing is None:
            self._db.execute(
                "INSERT OR IGNORE INTO unresolved_risk(session,ticker)"
                " VALUES (?,?)", (session, ticker))
            return False
        try:
            self._db.execute(
                "INSERT INTO observed"
                " (session,permaticker,ticker,category,eligible,payload)"
                " VALUES (?,?,?,?,?,?)",
                (session, identity, ticker, listing.category,
                 int(listing.common_equity), bar_witness(row)))
        except sqlite3.IntegrityError as exc:
            prior = self._db.execute(
                "SELECT ticker,payload FROM observed WHERE session=? AND permaticker=?",
                (session, identity)).fetchone()
            if prior is None or prior[0] == ticker:
                raise SourceAuthorityRefused(
                    f"SEP seed repeats source key {ticker}/{session}") from exc
            self._db.execute("INSERT OR IGNORE INTO identity_collisions VALUES (?,?,?,?)",
                             (session, identity, *prior))
            try:
                self._db.execute("INSERT INTO identity_collisions VALUES (?,?,?,?)",
                                 (session, identity, ticker, bar_witness(row)))
            except sqlite3.IntegrityError as duplicate:
                raise SourceAuthorityRefused(
                    f"SEP seed repeats source key {ticker}/{session}") from duplicate
            # Capture is private until require_complete succeeds. Retain all
            # distinct witnesses instead of hiding later collisions behind one.
        return True

    def require_no_collisions(self, *, date_from: str, date_to: str) -> None:
        require_no_collisions(self._db, projection=self.projection, resolve=self.resolve,
                              date_from=date_from, date_to=date_to)

    def require_complete(self, *, date_from: str, date_to: str) -> dict:
        self.require_no_collisions(date_from=date_from, date_to=date_to)
        sessions = list(calendar.sessions_in_range(date_from, date_to))
        if not sessions:
            raise SourceAuthorityRefused(
                f"seed coverage interval {date_from}..{date_to} has no sessions")

        aggregate_expected_ineligible: dict[str, int] = {}
        aggregate_received_ineligible: dict[str, int] = {}
        aggregate_missing_ineligible: dict[str, int] = {}
        aggregate_expected_eligible = 0
        aggregate_received_eligible = 0
        aggregate_reviewed_exceptions = 0

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
            evidence = self._failure_evidence(
                session=session, active=active, expected=expected,
                missing=missing, extra=extra, unresolved=unresolved,
                accepted=accepted)
            if missing or extra or unresolved:
                identity = getattr(getattr(self.resolve, "__self__", None), "projection", None)
                if identity is not None:
                    evidence["identity_diagnostics"] = identity.explain(
                        symbols=evidence["unresolved_source_tickers"], identities=missing)
                raise SourceAuthorityRefused(
                    "Sharadar SEP seed eligible-set coverage refused: "
                    # Stable insertion order puts the failed session and keys
                    # before the GO boundary's bounded diagnostic truncation.
                    + json.dumps(evidence, separators=(",", ":")))

            aggregate_expected_eligible += int(evidence["expected_eligible"])
            aggregate_received_eligible += int(evidence["received_eligible"])
            aggregate_reviewed_exceptions += len(accepted)
            for category, count in evidence[
                    "expected_ineligible_by_category"].items():
                aggregate_expected_ineligible[category] = (
                    aggregate_expected_ineligible.get(category, 0) + int(count))
            for category, count in evidence[
                    "received_ineligible_by_category"].items():
                aggregate_received_ineligible[category] = (
                    aggregate_received_ineligible.get(category, 0) + int(count))
            for category, count in evidence[
                    "missing_ineligible_by_category"].items():
                aggregate_missing_ineligible[category] = (
                    aggregate_missing_ineligible.get(category, 0) + int(count))

        return {
            "schema": "sentinel.seed-source-coverage/1",
            "interval": [str(date_from), str(date_to)],
            "source_projection_digest": self.projection.source_digest,
            "sessions_checked": len(sessions),
            "expected_eligible_total": aggregate_expected_eligible,
            "received_eligible_total": aggregate_received_eligible,
            "missing_eligible_total": 0,
            "unexpected_eligible_total": 0,
            "unresolved_eligible_risk_total": 0,
            "reviewed_exceptions_applied_total": aggregate_reviewed_exceptions,
            "expected_ineligible_by_category": dict(sorted(
                aggregate_expected_ineligible.items())),
            "received_ineligible_by_category": dict(sorted(
                aggregate_received_ineligible.items())),
            "missing_ineligible_by_category": dict(sorted(
                aggregate_missing_ineligible.items())),
        }

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
            "expected_eligible": len(expected),
            "received_eligible": observed_eligible,
            "missing_eligible_total": len(missing),
            "missing_eligible": keys(list(missing)),
            "unresolved_source_tickers": [str(row[0]) for row in self._db.execute(
                "SELECT ticker FROM unresolved_source WHERE session=?"
                " ORDER BY ticker LIMIT 16", (session,)).fetchall()],
            "unexpected_eligible_total": len(extra),
            "unexpected_eligible": keys(list(extra)),
            "unresolved_eligible_risk_total": len(unresolved),
            "unresolved_eligible_risk": list(unresolved[:16]),
            "reviewed_exceptions_applied": list(sorted(accepted))[:16],
            "expected_ineligible_by_category": dict(sorted(
                expected_ineligible.items())),
            "received_ineligible_by_category": observed_ineligible,
            "missing_ineligible_by_category": missing_ineligible,
            "source_projection_digest": self.projection.source_digest,
        }

    def observed_keys(self):
        """Independent source membership, after require_complete, for a seal.

        Includes resolved ineligible observations too: normalization may not
        silently discard a source key just because it is outside today's book.
        """
        yield from self._db.execute(
            "SELECT session,permaticker FROM observed ORDER BY session,permaticker")

    def close(self) -> None:
        self._db.close()
        self._dir.cleanup()


__all__ = ["SeedCoverageAccumulator"]
