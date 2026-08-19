"""Sharadar cross-table coherence and historical-seed authority.

Issue #177 established that a successful table traversal is not publication
proof. This module adds the remaining source contracts without changing that
boundary: TICKERS and SFP are corroborated across protected SEP, and historical
seed chunks are validated session-by-session before any row can reach the
candidate ingest.

The authoritative design, field list, and historical calibration live in
``docs/sharadar-publication-authority.md``.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import pickle
import statistics
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from sentinel.feed import authority, calendar, universe

TICKERS_AUTHORITY_FIELDS = (
    "table",
    "permaticker",
    "ticker",
    "category",
    "relatedtickers",
    "firstpricedate",
    "lastpricedate",
    "sector",
    "isdelisted",
)
SFP_AUTHORITY_FIELDS = ("date", "ticker", "closeadj")

# Calibrated from the retained TICKERS table=SEP bulk snapshot. Fields that were
# complete in ground truth are exact rather than sharing a generic 99% escape
# hatch: one missing category can change eligibility for exactly one priced
# security and must not be hidden by 21k healthy rows. Ticker has one known
# blank row in the retained source; sector has a legitimate sparse tail.
TICKERS_METADATA_MINIMUMS = (
    ("permaticker", "permanent identity", 1.0),
    ("ticker", "ticker", 0.9999),
    ("category", "category", 1.0),
    ("firstpricedate", "firstpricedate", 1.0),
    ("lastpricedate", "lastpricedate", 1.0),
    ("isdelisted", "isdelisted", 1.0),
    ("sector", "sector", 0.99),
)
MIN_SEED_IDENTITY_COVERAGE = 0.99
MIN_SEED_SIGNAL_COVERAGE = 0.99
MIN_SEED_RAW_CLOSE_COVERAGE = 0.99
MIN_SEED_RAW_OPEN_COVERAGE = 0.99
MIN_SEED_VOLUME_COVERAGE = 0.98
MIN_SEED_SESSION_ROWS = 4_000
MIN_SEED_LOCAL_POPULATION_RATIO = 0.90
SEED_POPULATION_NEIGHBOURS = 10
_MASK_256 = (1 << 256) - 1


class TickerMetadataIncomplete(RuntimeError):
    """The SEP-relevant TICKERS metadata domain is materially incomplete."""


class SeedHistoryIncomplete(RuntimeError):
    """Historical SEP evidence is inconsistent with a complete seed source."""


@dataclass(frozen=True)
class SeedSessionCounts:
    rows: int = 0
    identity: int = 0
    signal_close: int = 0
    raw_close: int = 0
    raw_open: int = 0
    volume: int = 0

    def add(self, row: Mapping, *, resolved: bool) -> "SeedSessionCounts":
        signal = _positive(row.get("close"))
        raw = _positive(row.get("closeunadj"))
        open_ = _positive(row.get("open"))
        volume = _nonnegative(row.get("volume"))
        return SeedSessionCounts(
            rows=self.rows + 1,
            identity=self.identity + int(resolved),
            signal_close=self.signal_close + int(signal),
            raw_close=self.raw_close + int(raw),
            raw_open=self.raw_open + int(open_ and signal and raw),
            volume=self.volume + int(volume),
        )


class _Fingerprint:
    """Order-independent multiset fingerprint matching issue #177 semantics."""

    def __init__(self) -> None:
        self.rows = 0
        self._a = 0
        self._b = 0

    def add(self, payload: bytes) -> None:
        self.rows += 1
        a = int.from_bytes(hashlib.sha256(b"\x00" + payload).digest(), "big")
        b = int.from_bytes(hashlib.sha256(b"\x01" + payload).digest(), "big")
        self._a = (self._a + a) & _MASK_256
        self._b = (self._b + b) & _MASK_256

    def digest(self) -> str:
        evidence = (
            self.rows.to_bytes(16, "big")
            + self._a.to_bytes(32, "big")
            + self._b.to_bytes(32, "big")
        )
        return hashlib.sha256(evidence).hexdigest()


def _canonical(value):
    if value is None:
        return None
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not number.is_finite():
            return str(value)
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    return str(value)


def _positive(value) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _nonnegative(value) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0


def _present(value) -> bool:
    """True for an observed value, including boolean False."""
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    return bool(str(value).strip())


def _payload(row: Mapping, fields) -> bytes:
    values = {}
    for field in fields:
        if field == "relatedtickers":
            # Formatting and token order are not behavioral, but NULL versus an
            # observed empty set is: NULL carries prior authority while blank
            # clears old issuer siblings. Preserve that distinction in the
            # source-generation fingerprint.
            raw = row.get("relatedtickers")
            values[field] = (None if raw is None else list(
                universe.parse_related_tickers(raw)))
        else:
            values[field] = _canonical(row.get(field))
    return json.dumps(values, sort_keys=True, separators=(",", ":")).encode(
        "utf-8")


def _observe(table: str, rows: Iterable[Mapping], fields
             ) -> authority.SourceObservation:
    fingerprint = _Fingerprint()
    for row in rows:
        fingerprint.add(_payload(row, fields))
    return authority.SourceObservation(
        table=table, rows=fingerprint.rows, digest=fingerprint.digest())


def observe_tickers(rows: Iterable[Mapping]) -> authority.SourceObservation:
    return _observe("TICKERS", rows, TICKERS_AUTHORITY_FIELDS)


def observe_sfp(rows: Iterable[Mapping]) -> authority.SourceObservation:
    return _observe("SFP", rows, SFP_AUTHORITY_FIELDS)


def _sep_ticker_rows(rows: Iterable[Mapping]) -> list[Mapping]:
    # Source partition is itself authority. If ``table`` disappears, no row is
    # silently assumed to be SEP; the validator below refuses the snapshot.
    return [row for row in rows
            if str(row.get("table") or "").strip().upper() == "SEP"]


def assert_tickers_metadata(rows: Iterable[Mapping]) -> list[Mapping]:
    """Require calibrated SEP metadata domains on a TICKERS snapshot.

    ``relatedtickers`` has no non-null floor: blank is affirmative evidence that
    no siblings are known. Exact ground-truth fields are required exactly;
    ticker and sector retain only their measured legitimate sparse tails.
    """
    rows = list(rows)
    relevant = _sep_ticker_rows(rows)
    if not relevant:
        raise TickerMetadataIncomplete(
            "Sharadar TICKERS exposed no table=SEP rows; source partition "
            "authority is missing or incomplete")

    total = len(relevant)
    for field, label, minimum in TICKERS_METADATA_MINIMUMS:
        present = sum(_present(row.get(field)) for row in relevant)
        share = present / total
        if share < minimum:
            raise TickerMetadataIncomplete(
                f"Sharadar TICKERS SEP {label} is present on "
                f"{present:,}/{total:,} rows ({share:.4%}); source authority "
                f"requires at least {minimum:.2%}")
    return relevant


def assert_seed_history(sessions: Mapping[str, SeedSessionCounts], *,
                        date_from: str, date_to: str) -> None:
    """Validate one full historical SEP chunk before any row is replayed."""
    if not sessions:
        raise SeedHistoryIncomplete(
            f"Sharadar SEP seed {date_from}..{date_to} returned no sessions")

    expected = list(calendar.sessions_in_range(date_from, date_to))
    missing = [session for session in expected if session not in sessions]
    if missing:
        sample = ", ".join(missing[:5])
        raise SeedHistoryIncomplete(
            f"Sharadar SEP seed {date_from}..{date_to} is missing "
            f"{len(missing)} exchange session(s): {sample}")

    domains = (
        ("permanent identity", "identity", MIN_SEED_IDENTITY_COVERAGE),
        ("signal close", "signal_close", MIN_SEED_SIGNAL_COVERAGE),
        ("raw close (closeunadj)", "raw_close", MIN_SEED_RAW_CLOSE_COVERAGE),
        ("reconstructable raw open", "raw_open", MIN_SEED_RAW_OPEN_COVERAGE),
        ("volume", "volume", MIN_SEED_VOLUME_COVERAGE),
    )
    for session in expected:
        counts = sessions[session]
        if counts.rows < MIN_SEED_SESSION_ROWS:
            raise SeedHistoryIncomplete(
                f"Sharadar SEP seed {session} contains only {counts.rows:,} "
                f"rows; calibrated full-source floor is "
                f"{MIN_SEED_SESSION_ROWS:,}")
        for label, attr, minimum in domains:
            present = int(getattr(counts, attr))
            share = present / counts.rows
            if share < minimum:
                raise SeedHistoryIncomplete(
                    f"Sharadar SEP seed {session} {label} is present/resolved "
                    f"on {present:,}/{counts.rows:,} rows ({share:.1%}); "
                    f"requires at least {minimum:.0%}")

    # Population is not stationary over 28 years. Compare each session with a
    # local two-sided window rather than with a global or recent-only baseline.
    populations = [sessions[session].rows for session in expected]
    for i, session in enumerate(expected):
        lo = max(0, i - SEED_POPULATION_NEIGHBOURS)
        hi = min(len(expected), i + SEED_POPULATION_NEIGHBOURS + 1)
        neighbours = populations[lo:i] + populations[i + 1:hi]
        if not neighbours:
            continue
        median = statistics.median(neighbours)
        ratio = populations[i] / median if median else 1.0
        if ratio < MIN_SEED_LOCAL_POPULATION_RATIO:
            raise SeedHistoryIncomplete(
                f"Sharadar SEP seed {session} population {populations[i]:,} "
                f"is {ratio:.1%} of its local median {median:,.1f}; calibrated "
                f"source floor is {MIN_SEED_LOCAL_POPULATION_RATIO:.0%}")


class StableSharadarFetch(authority.StableSharadarFetch):
    """Issue-177 stability plus TICKERS/SFP bracketing and seed validation."""

    def __init__(self, fetch, *, protect_sep=None,
                 corroborate_reference=None,
                 after_session: str | None = None,
                 seed_mode: bool = False):
        # Daily has one protected window, so all source corroboration happens
        # there. A seed passes an explicit final-chunk predicate: every SEP year
        # is stable on its own while TICKERS/ACTIONS/SFP remain bracketed across
        # the full multi-year join.
        reference = corroborate_reference
        if reference is None:
            reference = protect_sep or (lambda _params: True)
        super().__init__(
            fetch, protect_sep=protect_sep,
            corroborate_actions=reference,
            after_session=after_session)
        self._corroborate_reference = reference
        self._seed_mode = bool(seed_mode)
        self._seed_resolver = None
        self._tickers_first = None
        self._tickers_params = None
        self._tickers_kwargs = None
        self._sfp_first = None
        self._sfp_params = None
        self._sfp_kwargs = None

    def __call__(self, table, params=None, **kwargs):
        from sentinel.feed import sharadar

        if table == sharadar.TICKERS:
            if self._tickers_first is not None:
                raise RuntimeError(
                    "TICKERS was requested again before corroboration")
            rows = list(self._fetch(table, params, **kwargs))
            relevant = assert_tickers_metadata(rows)
            # Sentinel's security universe is SEP. Other TICKERS product rows
            # can share the same (permaticker,ticker) but carry different
            # strategy metadata; letting them reach write_universe would make
            # vendor row order decide eligibility.
            self._tickers_first = observe_tickers(relevant)
            self._tickers_params = dict(params or {})
            self._tickers_kwargs = dict(kwargs)
            self._seed_resolver = universe.IdentityResolver(
                universe.listings_from_rows(relevant))
            return relevant

        if table == sharadar.SFP:
            if self._sfp_first is not None:
                raise RuntimeError("SFP was requested again before corroboration")
            rows = list(self._fetch(table, params, **kwargs))
            self._sfp_first = observe_sfp(rows)
            self._sfp_params = dict(params or {})
            self._sfp_kwargs = dict(kwargs)
            return rows

        params = params or {}
        rows = super().__call__(table, params, **kwargs)
        if table != sharadar.SEP:
            return rows

        if (self._protect_sep(params)
                and self._corroborate_reference(params)):
            # ``super`` has already completed both protected SEP traversals and
            # the delayed ACTIONS corroboration. TICKERS/SFP must now still be
            # byte-for-behavior identical to the observations that preceded SEP.
            self._require_reference_sources_stable()

        if not self._seed_mode:
            return rows
        return self._validated_seed_replay(rows, params)

    def _require_reference_sources_stable(self) -> None:
        from sentinel.feed import sharadar

        if self._tickers_first is not None:
            rows = list(self._fetch(
                sharadar.TICKERS, dict(self._tickers_params or {}),
                **dict(self._tickers_kwargs or {})))
            relevant = assert_tickers_metadata(rows)
            authority.require_stable(
                "TICKERS", self._tickers_first, observe_tickers(relevant))
            self._tickers_first = None
            self._tickers_params = None
            self._tickers_kwargs = None

        if self._sfp_first is not None:
            rows = list(self._fetch(
                sharadar.SFP, dict(self._sfp_params or {}),
                **dict(self._sfp_kwargs or {})))
            authority.require_stable("SFP", self._sfp_first, observe_sfp(rows))
            self._sfp_first = None
            self._sfp_params = None
            self._sfp_kwargs = None

    def _validated_seed_replay(self, rows, params):
        date_from = str(params.get("date.gte") or "")
        date_to = str(params.get("date.lte") or "")
        if not date_from or not date_to:
            raise SeedHistoryIncomplete(
                "seed SEP validation requires explicit date.gte/date.lte")
        if self._seed_resolver is None:
            raise SeedHistoryIncomplete(
                "seed SEP identity validation has no stable TICKERS resolver")
        resolver = self._seed_resolver.resolve

        spool = tempfile.TemporaryFile(mode="w+b")
        sessions: dict[str, SeedSessionCounts] = {}
        try:
            for row in rows:
                row = dict(row)
                session = str(row.get("date") or "")
                ticker = str(row.get("ticker") or "")
                resolved = bool(session and ticker and resolver(ticker, session))
                if session:
                    sessions[session] = sessions.get(
                        session, SeedSessionCounts()).add(
                            row, resolved=resolved)
                pickle.dump(row, spool, protocol=pickle.HIGHEST_PROTOCOL)
            assert_seed_history(
                sessions, date_from=date_from, date_to=date_to)
            spool.seek(0)
        except Exception:
            spool.close()
            raise

        def replay():
            try:
                while True:
                    try:
                        yield pickle.load(spool)
                    except EOFError:
                        return
            finally:
                spool.close()

        return replay()