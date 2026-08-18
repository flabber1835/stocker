"""Vendor-publication authority for Sharadar source snapshots.

A successful HTTP traversal is transport evidence, not publication evidence.
Sharadar's tables can be observed while a vendor generation is still moving, so
Sentinel requires two complete observations with the same order-independent
content fingerprint before source absence is allowed to become local authority.

The price-domain checks here are deliberately about the *frontier session*, not
about strategy eligibility and not about historical density.  A healthy 126-day
history must never dilute a broken current decision day into a PASS.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from sentinel.feed import action_source

MIN_FRONTIER_DOMAIN_COVERAGE = 0.90
_MASK_256 = (1 << 256) - 1


class VendorPublicationUnstable(RuntimeError):
    """Two complete traversals disagree, so the vendor generation is ambiguous."""


class FrontierDomainIncomplete(RuntimeError):
    """The newest strategy-critical SEP domain is materially incomplete."""


@dataclass(frozen=True)
class DomainCounts:
    rows: int = 0
    signal_close: int = 0
    raw_close: int = 0
    raw_open: int = 0
    volume: int = 0

    def add(self, row: Mapping) -> "DomainCounts":
        signal = _positive(row.get("close"))
        raw = _positive(row.get("closeunadj"))
        open_ = _positive(row.get("open"))
        volume = _positive(row.get("volume"))
        return DomainCounts(
            rows=self.rows + 1,
            signal_close=self.signal_close + int(signal),
            raw_close=self.raw_close + int(raw),
            # The as-traded open is reconstructed from all three values.  An
            # adjusted open alone is not an executable price domain.
            raw_open=self.raw_open + int(open_ and signal and raw),
            volume=self.volume + int(volume),
        )


@dataclass(frozen=True)
class SourceObservation:
    table: str
    rows: int
    digest: str
    sessions: Mapping[str, DomainCounts] = field(default_factory=dict)


class _CommutativeFingerprint:
    """Bounded-memory, order-independent multiset fingerprint.

    Cursor pagination has no ordering contract, so hashing rows in arrival order
    would reject two identical snapshots merely because the API returned a page
    differently.  Two domain-separated SHA-256 row hashes are accumulated modulo
    2**256, then bound together with the exact row count. Duplicate multiplicity
    is therefore evidence too, while memory stays constant for multi-million-row
    SEP windows.
    """

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
            d = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not d.is_finite():
            return str(value)
        if d == 0:
            return "0"
        return format(d.normalize(), "f")
    return str(value)


def _positive(value) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _sep_payload(row: Mapping) -> bytes:
    # Deliberately excludes SEP.closeadj: Sentinel reads none of that forbidden
    # total-return domain.  Completeness/key-set evidence and every domain that
    # can affect today's decision are included.
    payload = {
        "date": _canonical(row.get("date")),
        "ticker": _canonical(row.get("ticker")),
        "close": _canonical(row.get("close")),
        "closeunadj": _canonical(row.get("closeunadj")),
        "open": _canonical(row.get("open")),
        "volume": _canonical(row.get("volume")),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def observe_sep(rows: Iterable[Mapping]) -> SourceObservation:
    fingerprint = _CommutativeFingerprint()
    sessions: dict[str, DomainCounts] = {}
    for row in rows:
        fingerprint.add(_sep_payload(row))
        session = str(row.get("date") or "")
        if session:
            sessions[session] = sessions.get(session, DomainCounts()).add(row)
    return SourceObservation(
        table="SEP", rows=fingerprint.rows, digest=fingerprint.digest(),
        sessions=sessions)


def observe_actions(rows: Iterable[Mapping]) -> SourceObservation:
    fingerprint = _CommutativeFingerprint()
    for row in rows:
        payload = action_source.payload_bytes(action_source.canonical_payload(row))
        fingerprint.add(payload)
    return SourceObservation(
        table="ACTIONS", rows=fingerprint.rows, digest=fingerprint.digest())


def require_stable(table: str, first: SourceObservation,
                   second: SourceObservation) -> None:
    """Refuse one successful-looking traversal as proof of completeness."""
    expected = str(table).upper()
    if first.table != expected or second.table != expected:
        raise ValueError(
            f"stability evidence table mismatch: expected {expected}, "
            f"got {first.table}/{second.table}")
    if first.rows == second.rows and first.digest == second.digest:
        return
    raise VendorPublicationUnstable(
        f"Sharadar {expected} publication is not stable across two complete "
        f"observations: rows {first.rows:,}->{second.rows:,}, "
        f"fingerprint {first.digest[:16]}->{second.digest[:16]}. Refusing to "
        f"treat absence, removal, or the candidate corpus as authoritative.")


def assert_frontier_domains(
    observation: SourceObservation,
    *,
    after_session: str | None = None,
    minimum: float = MIN_FRONTIER_DOMAIN_COVERAGE,
) -> None:
    """Prove each newly exposed decision session has its critical SEP domains.

    `after_session` is the pre-ingest *published* frontier on daily runs.  Every
    vendor session newer than it is checked independently, so several missed
    days cannot hide one another.  A seed has no prior authority boundary and
    checks its newest observed session.
    """
    if observation.table != "SEP":
        raise ValueError("frontier price-domain evidence must come from SEP")
    if not (0 < minimum <= 1):
        raise ValueError("frontier domain coverage minimum must be in (0, 1]")

    available = sorted(observation.sessions)
    if after_session is None:
        targets = available[-1:] if available else []
    else:
        targets = [session for session in available if session > after_session]
    if not targets:
        return

    domains = (
        ("signal close", "signal_close"),
        ("raw close (closeunadj)", "raw_close"),
        ("raw open", "raw_open"),
        ("volume", "volume"),
    )
    for session in targets:
        counts = observation.sessions[session]
        if counts.rows <= 0:
            raise FrontierDomainIncomplete(
                f"Sharadar SEP {session} has no rows to establish a frontier")
        for label, attr in domains:
            present = int(getattr(counts, attr))
            share = present / counts.rows
            if share < minimum:
                raise FrontierDomainIncomplete(
                    f"Sharadar SEP frontier {session} {label} is present on "
                    f"{present:,}/{counts.rows:,} rows ({share:.1%}); authority "
                    f"requires at least {minimum:.0%}. Historical coverage may "
                    f"not dilute a broken current decision session into PASS.")


class StableSharadarFetch:
    """A fetch adapter that turns transport success into publication evidence.

    The first ACTIONS traversal is allowed to enter the candidate run so price
    normalisation can cross-check splits exactly as before, but it is not local
    authority: those observations remain invisible until the run publishes.  A
    second complete ACTIONS observation is deliberately delayed until after the
    first protected SEP traversal.  If the key/content set moved, the run fails
    before any protected SEP row can be replayed and before publication can make
    the candidate ACTIONS lifecycle visible.

    SEP itself is not materialised in RAM: its second observation is spooled to
    a temporary file, validated in full, and only then replayed to the ingest.
    This preserves the bounded-memory property of the existing bulk path.
    """

    def __init__(self, fetch, *, protect_sep=None, after_session: str | None = None):
        self._fetch = fetch
        self._protect_sep = protect_sep or (lambda _params: True)
        self._after_session = after_session
        self._actions_first: SourceObservation | None = None
        self._actions_params: dict | None = None
        self._actions_kwargs: dict | None = None

    def __call__(self, table, params=None, **kwargs):
        from sentinel.feed import sharadar

        if table == sharadar.ACTIONS:
            if self._actions_first is not None:
                raise RuntimeError(
                    "ACTIONS was requested again before its first candidate "
                    "snapshot could be corroborated")
            rows = list(self._fetch(table, params, **kwargs))
            self._actions_first = observe_actions(rows)
            self._actions_params = dict(params or {})
            self._actions_kwargs = dict(kwargs)
            return rows

        if table == sharadar.SEP and self._protect_sep(params or {}):
            return self._stable_sep(table, params, **kwargs)

        return self._fetch(table, params, **kwargs)

    def _require_actions_stable(self) -> None:
        from sentinel.feed import sharadar

        if self._actions_first is None:
            return
        rows = list(self._fetch(
            sharadar.ACTIONS,
            dict(self._actions_params or {}),
            **dict(self._actions_kwargs or {})))
        second = observe_actions(rows)
        require_stable(sharadar.ACTIONS, self._actions_first, second)
        self._actions_first = None
        self._actions_params = None
        self._actions_kwargs = None

    def _stable_sep(self, table, params, **kwargs):
        import pickle
        import tempfile

        # This complete first SEP traversal separates the two ACTIONS snapshots
        # in time and preserves the long-standing TICKERS -> ACTIONS -> SFP -> SEP
        # orchestration. It is evidence only; no row is returned to the ingest.
        first = observe_sep(self._fetch(table, params, **kwargs))
        self._require_actions_stable()

        spool = tempfile.TemporaryFile(mode="w+b")
        fingerprint = _CommutativeFingerprint()
        sessions: dict[str, DomainCounts] = {}
        try:
            for row in self._fetch(table, params, **kwargs):
                fingerprint.add(_sep_payload(row))
                session = str(row.get("date") or "")
                if session:
                    sessions[session] = sessions.get(
                        session, DomainCounts()).add(row)
                pickle.dump(dict(row), spool, protocol=pickle.HIGHEST_PROTOCOL)
            second = SourceObservation(
                table="SEP", rows=fingerprint.rows,
                digest=fingerprint.digest(), sessions=sessions)
            require_stable("SEP", first, second)
            assert_frontier_domains(second, after_session=self._after_session)
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
