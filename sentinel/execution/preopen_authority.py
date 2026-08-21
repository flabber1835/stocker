"""Immutable pre-open authority for execution share units.

An execution plan is expressed in the share units known at its decision close.
A split effective at the following open can change those units before Sentinel
may submit an order.  This module defines the evidence shape needed to cross
that boundary without treating provider silence as "no split".

There is deliberately no production provider in this module.  A future adapter
must supply a complete publication with an externally justified cutoff.  Each
covered permanent security has an explicit attestation: either ``NO_EVENT``
with multiplier one, or one or more oriented events carrying stable event and
revision identities.  Missing coverage is never equivalent to multiplier one.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Iterable, Mapping, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for static type checking
    from sentinel.execution.plan import ExecutionPlan


KIND = "preopen-share-unit-authority/v1"
CURSOR_PREFIX = "preopen-share-unit-authority:v1:"
NO_EVENT = "NO_EVENT"
ORIENTED_EVENTS = "ORIENTED_EVENTS"
_DISPOSITIONS = frozenset({NO_EVENT, ORIENTED_EVENTS})
_RATIO_REPRESENTATION_TOLERANCE = Fraction(1, 10**12)


class PreOpenAuthorityRefused(RuntimeError):
    """Pre-open evidence is absent, stale, incomplete, or contradictory."""


def _canonical(value: Mapping) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _nonempty(value: object, *, where: str) -> str:
    if not isinstance(value, str):
        raise PreOpenAuthorityRefused(f"{where} must be a non-empty string")
    text = value.strip()
    if not text:
        raise PreOpenAuthorityRefused(f"{where} must be non-empty")
    return text


def _decimal(value: object, *, where: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PreOpenAuthorityRefused(f"{where} is not a Decimal") from exc
    if not result.is_finite() or result <= 0:
        raise PreOpenAuthorityRefused(
            f"{where} must be finite and strictly positive")
    return result


def _decimal_text(value: Decimal) -> str:
    """Canonical non-exponent spelling for an already-validated Decimal."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _aware_utc(value: datetime, *, where: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None \
            or value.utcoffset() is None:
        raise PreOpenAuthorityRefused(f"{where} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object, *, where: str) -> datetime:
    try:
        text = str(value)
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text)
    except (TypeError, ValueError) as exc:
        raise PreOpenAuthorityRefused(
            f"{where} is not an ISO timestamp") from exc
    return _aware_utc(parsed, where=where)


@dataclass(frozen=True)
class ShareUnitEvent:
    """One oriented provider event and the revision that supplied its terms."""

    event_id: str
    revision_id: str
    effective_session: date
    multiplier: Decimal
    canonical_numerator: Optional[int] = None
    canonical_denominator: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _nonempty(self.event_id, where="event id"))
        object.__setattr__(
            self, "revision_id",
            _nonempty(self.revision_id, where="event revision id"))
        if type(self.effective_session) is not date:
            raise PreOpenAuthorityRefused(
                "event effective session must be a date")
        object.__setattr__(
            self, "multiplier",
            _decimal(self.multiplier, where="event oriented multiplier"))
        numerator = self.canonical_numerator
        denominator = self.canonical_denominator
        if (numerator is None) != (denominator is None):
            raise PreOpenAuthorityRefused(
                "event rational multiplier must provide both numerator and "
                "denominator")
        if numerator is not None:
            if (isinstance(numerator, bool) or isinstance(denominator, bool)
                    or not isinstance(numerator, int)
                    or not isinstance(denominator, int)
                    or numerator <= 0 or denominator <= 0):
                raise PreOpenAuthorityRefused(
                    "event rational multiplier terms must be positive integers")
            published = Fraction(self.multiplier)
            exact = Fraction(numerator, denominator)
            scale = max(abs(published), abs(exact), Fraction(1, 10**30))
            if abs(published - exact) > (
                    _RATIO_REPRESENTATION_TOLERANCE * scale):
                raise PreOpenAuthorityRefused(
                    "event rational multiplier contradicts its oriented "
                    "Decimal multiplier")

    def payload(self) -> dict:
        return {
            "event_id": self.event_id,
            "revision_id": self.revision_id,
            "effective_session": self.effective_session.isoformat(),
            "multiplier": _decimal_text(self.multiplier),
            "canonical_numerator": self.canonical_numerator,
            "canonical_denominator": self.canonical_denominator,
        }


@dataclass(frozen=True)
class ShareUnitCoverage:
    """Explicit share-unit answer for exactly one permanent security."""

    security_id: str
    disposition: str
    multiplier: Decimal
    events: tuple[ShareUnitEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "security_id",
            _nonempty(self.security_id, where="covered security id"))
        disposition = str(self.disposition)
        if disposition not in _DISPOSITIONS:
            raise PreOpenAuthorityRefused(
                f"share-unit disposition {disposition!r} is unsupported")
        object.__setattr__(self, "disposition", disposition)
        multiplier = _decimal(
            self.multiplier, where=f"coverage multiplier {self.security_id}")
        object.__setattr__(self, "multiplier", multiplier)
        events = tuple(sorted(
            self.events,
            key=lambda event: (
                event.effective_session, event.event_id, event.revision_id)))
        if not all(isinstance(event, ShareUnitEvent) for event in events):
            raise PreOpenAuthorityRefused(
                f"coverage events for {self.security_id} are malformed")
        event_ids = {event.event_id for event in events}
        if len(event_ids) != len(events):
            raise PreOpenAuthorityRefused(
                f"coverage events for {self.security_id} repeat or revise one "
                "provider event inside a single publication")
        object.__setattr__(self, "events", events)

        if disposition == NO_EVENT:
            if multiplier != Decimal(1) or events:
                raise PreOpenAuthorityRefused(
                    f"NO_EVENT coverage for {self.security_id} requires an "
                    "explicit multiplier 1 and no event rows")
            return
        if not events:
            raise PreOpenAuthorityRefused(
                f"ORIENTED_EVENTS coverage for {self.security_id} requires "
                "durable event and revision identities")
        product = Decimal(1)
        for event in events:
            product *= event.multiplier
        if product != multiplier:
            raise PreOpenAuthorityRefused(
                f"coverage multiplier {multiplier} for {self.security_id} "
                f"does not equal its oriented event product {product}")

    @classmethod
    def no_event(cls, security_id: str) -> "ShareUnitCoverage":
        return cls(
            security_id=security_id, disposition=NO_EVENT,
            multiplier=Decimal(1), events=())

    @classmethod
    def oriented(
            cls, security_id: str, events: Iterable[ShareUnitEvent]
            ) -> "ShareUnitCoverage":
        event_tuple = tuple(events)
        multiplier = Decimal(1)
        for event in event_tuple:
            if not isinstance(event, ShareUnitEvent):
                raise PreOpenAuthorityRefused(
                    f"coverage events for {security_id} are malformed")
            multiplier *= event.multiplier
        return cls(
            security_id=security_id, disposition=ORIENTED_EVENTS,
            multiplier=multiplier, events=event_tuple)

    def payload(self) -> dict:
        return {
            "security_id": self.security_id,
            "disposition": self.disposition,
            "multiplier": _decimal_text(self.multiplier),
            "events": [event.payload() for event in self.events],
        }


@dataclass(frozen=True)
class PreOpenShareUnitAuthority:
    """One complete provider publication bound to one immutable plan."""

    plan_id: str
    plan_fingerprint: str
    effective_session: date
    provider: str
    publication_id: str
    as_of: datetime
    cutoff_at: datetime
    complete: bool
    coverage: tuple[ShareUnitCoverage, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", _nonempty(self.plan_id, where="plan id"))
        if not isinstance(self.plan_fingerprint, str):
            raise PreOpenAuthorityRefused(
                "plan fingerprint must be a lowercase SHA-256")
        fingerprint = self.plan_fingerprint
        if (len(fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in fingerprint)):
            raise PreOpenAuthorityRefused(
                "plan fingerprint must be a lowercase SHA-256")
        object.__setattr__(self, "plan_fingerprint", fingerprint)
        if type(self.effective_session) is not date:
            raise PreOpenAuthorityRefused("effective session must be a date")
        object.__setattr__(
            self, "provider", _nonempty(self.provider, where="provider"))
        object.__setattr__(
            self, "publication_id",
            _nonempty(self.publication_id, where="provider publication id"))
        as_of = _aware_utc(self.as_of, where="provider as-of")
        cutoff = _aware_utc(self.cutoff_at, where="provider cutoff")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "cutoff_at", cutoff)
        if as_of < cutoff:
            raise PreOpenAuthorityRefused(
                "provider publication predates its claimed completeness cutoff")
        if type(self.complete) is not bool:
            raise PreOpenAuthorityRefused(
                "provider completeness must be an explicit boolean")
        coverage = tuple(sorted(
            self.coverage, key=lambda item: item.security_id))
        if not all(isinstance(item, ShareUnitCoverage) for item in coverage):
            raise PreOpenAuthorityRefused("share-unit coverage is malformed")
        identities = [item.security_id for item in coverage]
        if len(set(identities)) != len(identities):
            raise PreOpenAuthorityRefused(
                "share-unit coverage repeats a permanent security id")
        for item in coverage:
            wrong = sorted({
                event.effective_session for event in item.events
                if event.effective_session != self.effective_session})
            if wrong:
                raise PreOpenAuthorityRefused(
                    f"share-unit event for {item.security_id} names the wrong "
                    f"effective session: {wrong}")
        object.__setattr__(self, "coverage", coverage)

    def _content_payload(self) -> dict:
        return {
            "kind": KIND,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "effective_session": self.effective_session.isoformat(),
            "provider": self.provider,
            "publication_id": self.publication_id,
            "as_of": _timestamp_text(self.as_of),
            "cutoff_at": _timestamp_text(self.cutoff_at),
            "complete": self.complete,
            "coverage": [item.payload() for item in self.coverage],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            _canonical(self._content_payload()).encode("ascii")).hexdigest()

    def payload(self) -> dict:
        return {**self._content_payload(), "authority_digest": self.digest}

    @classmethod
    def from_payload(
            cls, raw: Mapping, *, stored_session: date | str | None = None
            ) -> "PreOpenShareUnitAuthority":
        expected = {
            "kind", "plan_id", "plan_fingerprint", "effective_session",
            "provider", "publication_id", "as_of", "cutoff_at", "complete",
            "coverage", "authority_digest",
        }
        if (not isinstance(raw, Mapping) or set(raw) != expected
                or raw.get("kind") != KIND):
            raise PreOpenAuthorityRefused(
                "pre-open authority has an unknown state shape")
        if not isinstance(raw["coverage"], list):
            raise PreOpenAuthorityRefused(
                "pre-open authority coverage must be a list")
        try:
            effective = date.fromisoformat(str(raw["effective_session"]))
        except (TypeError, ValueError) as exc:
            raise PreOpenAuthorityRefused(
                "pre-open authority effective session is invalid") from exc
        if stored_session is not None:
            try:
                row_session = (
                    stored_session if isinstance(stored_session, date)
                    else date.fromisoformat(str(stored_session)))
            except (TypeError, ValueError) as exc:
                raise PreOpenAuthorityRefused(
                    "pre-open authority row session is invalid") from exc
            if row_session != effective:
                raise PreOpenAuthorityRefused(
                    "pre-open authority session disagrees with its durable row")

        coverage = []
        coverage_expected = {
            "security_id", "disposition", "multiplier", "events"}
        event_expected = {
            "event_id", "revision_id", "effective_session", "multiplier",
            "canonical_numerator", "canonical_denominator"}
        for item in raw["coverage"]:
            if (not isinstance(item, Mapping)
                    or set(item) != coverage_expected
                    or not isinstance(item["events"], list)):
                raise PreOpenAuthorityRefused(
                    "pre-open authority contains malformed security coverage")
            events = []
            for event in item["events"]:
                if not isinstance(event, Mapping) or set(event) != event_expected:
                    raise PreOpenAuthorityRefused(
                        "pre-open authority contains a malformed event")
                try:
                    event_session = date.fromisoformat(
                        str(event["effective_session"]))
                except (TypeError, ValueError) as exc:
                    raise PreOpenAuthorityRefused(
                        "pre-open authority event session is invalid") from exc
                events.append(ShareUnitEvent(
                    event_id=event["event_id"],
                    revision_id=event["revision_id"],
                    effective_session=event_session,
                    multiplier=_decimal(
                        event["multiplier"], where="stored event multiplier"),
                    canonical_numerator=event["canonical_numerator"],
                    canonical_denominator=event["canonical_denominator"]))
            coverage.append(ShareUnitCoverage(
                security_id=item["security_id"],
                disposition=item["disposition"],
                multiplier=_decimal(
                    item["multiplier"], where="stored coverage multiplier"),
                events=tuple(events)))
        authority = cls(
            plan_id=raw["plan_id"],
            plan_fingerprint=raw["plan_fingerprint"],
            effective_session=effective,
            provider=raw["provider"],
            publication_id=raw["publication_id"],
            as_of=_parse_timestamp(raw["as_of"], where="stored provider as-of"),
            cutoff_at=_parse_timestamp(
                raw["cutoff_at"], where="stored provider cutoff"),
            complete=raw["complete"],
            coverage=tuple(coverage))
        if raw["authority_digest"] != authority.digest:
            raise PreOpenAuthorityRefused(
                "pre-open authority digest does not match its content")
        return authority


def _required_identities(values: Iterable[str]) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise PreOpenAuthorityRefused(
            "required share-unit identities must be an iterable of strings")
    identities = [_nonempty(value, where="required security id")
                  for value in values]
    if len(set(identities)) != len(identities):
        raise PreOpenAuthorityRefused(
            "required share-unit identities contain duplicates")
    return set(identities)


def validate_authority(
        authority: PreOpenShareUnitAuthority, *, plan_id: str,
        plan_fingerprint: str, effective_session: date,
        required_security_ids: Iterable[str], required_cutoff_at: datetime,
        evaluated_at: datetime) -> dict[str, Decimal]:
    """Validate exact plan/session/identity coverage at one execution boundary."""
    if not isinstance(authority, PreOpenShareUnitAuthority):
        raise PreOpenAuthorityRefused("pre-open authority is absent or malformed")
    if authority.plan_id != plan_id:
        raise PreOpenAuthorityRefused("pre-open authority names another plan")
    if authority.plan_fingerprint != plan_fingerprint:
        raise PreOpenAuthorityRefused(
            "pre-open authority names different immutable plan economics")
    if authority.effective_session != effective_session:
        raise PreOpenAuthorityRefused(
            "pre-open authority names the wrong effective session")
    if not authority.complete:
        raise PreOpenAuthorityRefused(
            "pre-open provider publication is incomplete")

    required = _required_identities(required_security_ids)
    covered = {item.security_id for item in authority.coverage}
    if covered != required:
        missing = sorted(required - covered)
        extra = sorted(covered - required)
        raise PreOpenAuthorityRefused(
            "pre-open authority does not exactly cover the executable "
            f"security set: missing={missing}, extra={extra}")

    cutoff = _aware_utc(required_cutoff_at, where="required provider cutoff")
    now = _aware_utc(evaluated_at, where="authority evaluation time")
    if authority.as_of < cutoff:
        raise PreOpenAuthorityRefused(
            "pre-open authority is stale at the required provider cutoff")
    if authority.cutoff_at != cutoff:
        raise PreOpenAuthorityRefused(
            "pre-open authority names a different provider cutoff")
    if authority.as_of > now:
        raise PreOpenAuthorityRefused(
            "pre-open authority claims a future provider publication")
    return {item.security_id: item.multiplier for item in authority.coverage}


def validate_for_plan(
        authority: PreOpenShareUnitAuthority, *, plan: "ExecutionPlan",
        required_security_ids: Iterable[str], required_cutoff_at: datetime,
        evaluated_at: datetime) -> dict[str, Decimal]:
    return validate_authority(
        authority, plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(),
        effective_session=plan.effective_session,
        required_security_ids=required_security_ids,
        required_cutoff_at=required_cutoff_at, evaluated_at=evaluated_at)


def _ratios_close(left: Decimal, right: Decimal) -> bool:
    left_fraction = Fraction(left)
    right_fraction = Fraction(right)
    scale = max(
        abs(left_fraction), abs(right_fraction), Fraction(1, 10**30))
    return abs(left_fraction - right_fraction) <= (
        _RATIO_REPRESENTATION_TOLERANCE * scale)


def _action_verb(value: object) -> str:
    return "".join(character for character in str(value).lower()
                   if character.isalnum())


@dataclass(frozen=True)
class AuthorityActionOverlay:
    """Replace only the effective-session corpus scalar with authority.

    Historical corpus events remain part of reconciliation.  A matching
    effective-session corpus event is replaced, not multiplied a second time;
    a contradiction is a refusal.  A provider-oriented event may also resolve
    a same-identity scalar event that the corpus could not orient, but it never
    suppresses a ticker-only or non-scalar material event.
    """

    base: object
    authority: PreOpenShareUnitAuthority

    def __post_init__(self) -> None:
        start = getattr(self.base, "start", None)
        events = getattr(self.base, "events", None)
        if type(start) is not date or not isinstance(events, Mapping):
            raise PreOpenAuthorityRefused(
                "pre-open authority can overlay only a dated corpus action "
                "lookup with inspectable event boundaries")
        effective = self.authority.effective_session
        scalar_events = tuple(getattr(self.base, "scalar_events", ()))
        unresolved = tuple(getattr(self.base, "unresolved_events", ()))
        for coverage in self.authority.coverage:
            current = tuple(
                _decimal(multiplier, where="corpus scalar multiplier")
                for session, multiplier in events.get(coverage.security_id, ())
                if session == effective)
            current_evidence = tuple(
                event for event in scalar_events
                if (event.security_id == coverage.security_id
                    and event.session == effective))
            unresolved_scalar = tuple(
                event for event in unresolved
                if (event.security_id == coverage.security_id
                    and event.session == effective
                    and _action_verb(event.action)
                    in {"split", "adrratiosplit"}))
            if coverage.disposition == NO_EVENT:
                if current or current_evidence or unresolved_scalar:
                    raise PreOpenAuthorityRefused(
                        f"negative pre-open authority for "
                        f"{coverage.security_id} contradicts a corpus split "
                        f"on {effective}")
                continue
            if current:
                corpus_product = Decimal(1)
                for multiplier in current:
                    corpus_product *= multiplier
                if not _ratios_close(corpus_product, coverage.multiplier):
                    raise PreOpenAuthorityRefused(
                        f"pre-open multiplier {coverage.multiplier} for "
                        f"{coverage.security_id} contradicts corpus multiplier "
                        f"{corpus_product} on {effective}")

    @property
    def start(self) -> date:
        return self.base.start

    @property
    def events(self):
        """Expose the effective overlay to compatible diagnostic callers."""
        result = {
            security_id: tuple(values)
            for security_id, values in self.base.events.items()}
        effective = self.authority.effective_session
        for coverage in self.authority.coverage:
            prior = tuple(
                (session, multiplier)
                for session, multiplier in result.get(coverage.security_id, ())
                if session != effective)
            if coverage.multiplier != Decimal(1):
                prior += ((effective, coverage.multiplier),)
            result[coverage.security_id] = tuple(sorted(prior))
        return result

    def __call__(self, security_id: str,
                 since: Optional[date] = None) -> Decimal:
        covered = {
            item.security_id: item for item in self.authority.coverage}
        coverage = covered.get(str(security_id))
        if coverage is None:
            return self.base(security_id, since)
        lower = max(self.start, since) if since is not None else self.start
        ratio = Decimal(1)
        effective = self.authority.effective_session
        for session, value in self.base.events.get(str(security_id), ()):
            if session > lower and session != effective:
                ratio *= value
        if effective > lower:
            ratio *= coverage.multiplier
        return ratio

    def material_events_for(self, *, security_ids=(), symbols=()):
        finder = getattr(self.base, "material_events_for", None)
        if not callable(finder):
            return ()
        covered = {
            item.security_id: item for item in self.authority.coverage}
        effective = self.authority.effective_session
        result = []
        for event in finder(security_ids=security_ids, symbols=symbols):
            coverage = covered.get(event.security_id)
            provider_resolves_scalar = (
                coverage is not None
                and coverage.disposition == ORIENTED_EVENTS
                and event.session == effective
                and _action_verb(event.action) in {"split", "adrratiosplit"})
            if not provider_resolves_scalar:
                result.append(event)
        return tuple(result)

    def scalar_evidence_for(self, security_ids=()):
        requested = {str(value) for value in security_ids}
        covered = {
            item.security_id: item for item in self.authority.coverage}
        effective = self.authority.effective_session
        reader = getattr(self.base, "scalar_evidence_for", None)
        result = []
        if callable(reader):
            result.extend(
                event for event in reader(security_ids)
                if not (event.security_id in covered
                        and event.session == effective))

        # Import lazily so the evidence contract does not create a module cycle.
        from sentinel.execution.reconcile import CorporateActionEvent
        for coverage in self.authority.coverage:
            if (coverage.security_id not in requested
                    or coverage.multiplier == Decimal(1)):
                continue
            for event in coverage.events:
                result.append(CorporateActionEvent(
                    security_id=coverage.security_id,
                    ticker=coverage.security_id,
                    session=effective,
                    action="split",
                    value=event.multiplier,
                    contraticker=None,
                    source_row_id=(
                        f"{KIND}:{self.authority.digest}:"
                        f"{coverage.security_id}:{event.event_id}:"
                        f"{event.revision_id}"),
                    reason="complete pre-open provider share-unit authority",
                    canonical_multiplier=event.multiplier,
                    split_disposition="provider_oriented_multiplier",
                    evidence_kind=KIND,
                    publication_run_id=self.authority.publication_id,
                    canonical_numerator=event.canonical_numerator,
                    canonical_denominator=event.canonical_denominator))
        return tuple(result)


def overlay_actions(
        base, authority: PreOpenShareUnitAuthority) -> AuthorityActionOverlay:
    """Build a checked action view with one authoritative open boundary."""
    if not isinstance(authority, PreOpenShareUnitAuthority):
        raise PreOpenAuthorityRefused("pre-open authority is malformed")
    return AuthorityActionOverlay(base=base, authority=authority)


def _cursor_name(plan_id: str) -> str:
    return f"{CURSOR_PREFIX}{_nonempty(plan_id, where='plan id')}"


def _decode(raw: object, *, plan_id: str,
            stored_session: date | str) -> PreOpenShareUnitAuthority:
    try:
        state = raw if isinstance(raw, Mapping) else json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise PreOpenAuthorityRefused(
            f"pre-open authority for {plan_id} is not valid JSON") from exc
    authority = PreOpenShareUnitAuthority.from_payload(
        state, stored_session=stored_session)
    if authority.plan_id != plan_id:
        raise PreOpenAuthorityRefused(
            f"pre-open authority for {plan_id} names another plan")
    return authority


def load_authority(
        conn, *, plan_id: str) -> Optional[PreOpenShareUnitAuthority]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (_cursor_name(plan_id),))
        row = cur.fetchone()
    return None if row is None else _decode(
        row[1], plan_id=plan_id, stored_session=row[0])


def record_authority(
        conn, authority: PreOpenShareUnitAuthority, *, commit: bool = True
        ) -> PreOpenShareUnitAuthority:
    """Persist once; a retry may reproduce but never replace the attestation."""
    if not authority.complete:
        raise PreOpenAuthorityRefused(
            "an incomplete provider publication cannot become durable authority")
    existing = load_authority(conn, plan_id=authority.plan_id)
    if existing is not None:
        if existing != authority:
            raise PreOpenAuthorityRefused(
                f"pre-open authority for plan {authority.plan_id} is immutable")
        return existing
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO NOTHING",
            (_cursor_name(authority.plan_id),
             authority.effective_session.isoformat(),
             _canonical(authority.payload())))
    stored = load_authority(conn, plan_id=authority.plan_id)
    if stored != authority:
        raise PreOpenAuthorityRefused(
            f"concurrent pre-open authority for plan {authority.plan_id} "
            "recorded different evidence")
    if commit:
        conn.commit()
    return stored


def require_recorded_authority(
        conn, *, plan: "ExecutionPlan", required_security_ids: Iterable[str],
        required_cutoff_at: datetime, evaluated_at: datetime
        ) -> tuple[PreOpenShareUnitAuthority, dict[str, Decimal]]:
    authority = load_authority(conn, plan_id=plan.plan_id)
    if authority is None:
        raise PreOpenAuthorityRefused(
            f"pre-open share-unit authority for plan {plan.plan_id} is absent")
    multipliers = validate_for_plan(
        authority, plan=plan, required_security_ids=required_security_ids,
        required_cutoff_at=required_cutoff_at, evaluated_at=evaluated_at)
    return authority, multipliers


__all__ = [
    "AuthorityActionOverlay", "CURSOR_PREFIX", "KIND", "NO_EVENT",
    "ORIENTED_EVENTS",
    "PreOpenAuthorityRefused", "PreOpenShareUnitAuthority",
    "ShareUnitCoverage", "ShareUnitEvent", "load_authority",
    "overlay_actions", "record_authority", "require_recorded_authority",
    "validate_authority", "validate_for_plan",
]
