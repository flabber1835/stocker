"""Current corporate-action restrictions; no negative-evidence certificate.

The action lookup and broker observation remain the evidence. Restrictions
are recomputed, never acknowledged away or latched from historical incidents.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, Inexact
from fractions import Fraction
from typing import Mapping

from sentinel.execution.numeric import exact_decimal


def decimal_or_rational(value: Fraction) -> Decimal | Fraction:
    """Preserve a share entitlement even when it has no finite decimal form."""
    try:
        return exact_decimal(value)
    except Inexact:
        return value


def material_events_for_security(actions, security_id: str, symbols=(), *, after: date | None = None):
    """Use ticker evidence only when an event lacks a permanent identity."""
    finder = getattr(actions, "material_events_for", None)
    if not callable(finder):
        return ()
    tickers = {str(symbol).upper() for symbol in symbols if symbol}
    return tuple(
        event for event in finder(security_ids=(security_id,), symbols=tuple(sorted(tickers)))
        if (after is None or event.session > after)
        and (event.security_id == security_id or (
            event.security_id is None and str(event.ticker).upper() in tickers)))


def _restriction(event) -> str:
    return f"CORPORATE_ACTION_PENDING: {event.action} {event.session} source={event.source_row_id}"


def material_restrictions(actions, symbols: Mapping[str, str], *, after: date | None = None) -> dict[str, str]:
    """Map known unsupported events onto one dated execution target."""
    result = {}
    for sid, symbol in sorted(symbols.items()):
        events = material_events_for_security(actions, sid, (symbol,), after=after)
        if events:
            result[sid] = _restriction(events[-1])
    return result


def _owned_or_working_on_event(actions, commands, security_id, session):
    from sentinel.execution.commands import is_legacy_migration
    from sentinel.execution.reconcile import CorpusActionLookup, expected_book_from_commands
    from sentinel.execution.states import IN_FLIGHT

    owned = tuple(command for command in commands if not is_legacy_migration(command))
    if any(command.state in IN_FLIGHT and (
            command.created_at is None or command.created_at.date() <= session) for command in owned):
        return True
    prior = tuple(command for command in owned if command.filled_quantity > 0 and (
        command.created_at is None or command.created_at.date() < session))
    if not prior:
        return False
    if any(command.created_at is None for command in prior):
        return True
    # The previous fills must be compared in the same units just before the event.
    # A closed historical position must not taint a later acquisition.
    events = tuple((day, ratio) for day, ratio in getattr(actions, "events", {}).get(security_id, ())
                   if day < session)
    reader = getattr(actions, "scalar_evidence_for", None)
    evidence = tuple(event for event in reader((security_id,)) if event.session < session) if callable(reader) else ()
    start = getattr(actions, "start", min(command.created_at.date() for command in prior))
    lookup = CorpusActionLookup(start=start, events={security_id: events}, scalar_events=evidence)
    return expected_book_from_commands(prior, actions=lookup).get(security_id, 0) > 0


def position_restrictions(*, actions, commands, observation, expected) -> dict[str, str]:
    active = {sid for sid, quantity in expected.items() if quantity != 0}
    from sentinel.execution.states import IN_FLIGHT
    active.update(command.security_id for command in commands if command.state in IN_FLIGHT)
    symbols: dict[str, set[str]] = {}
    own_commands: dict[str, list] = {}
    for command in commands:
        sid = command.security_id
        if sid in active:
            symbols.setdefault(sid, set()).add(command.instrument.symbol)
            own_commands.setdefault(sid, []).append(command)
    for position in observation.positions:
        sid = position.instrument.security_id
        if sid in active:
            symbols.setdefault(sid, set()).add(position.instrument.symbol)
    result = {}
    for sid, tickers in sorted(symbols.items()):
        for event in material_events_for_security(actions, sid, tickers):
            if _owned_or_working_on_event(actions, own_commands.get(sid, ()), sid, event.session):
                result[sid] = _restriction(event)
    return result


def entitlement_matches_observation(entitlement, held, prior, increment):
    """Recognize plausible unit-transition evidence without assigning it as shares."""
    if entitlement <= 0 or held < 0:
        return False
    if prior > 0 and held == prior:
        return True
    lot = Fraction(increment)
    floor = (entitlement // lot) * lot
    return Fraction(held) in {floor, floor + lot}


def matches_intermediate_split_units(actions, commands, security_id, observed) -> bool:
    """Recognize only an exact position produced by a dated scalar prefix."""
    from sentinel.execution.reconcile import CorpusActionLookup, expected_book_from_commands

    reader = getattr(actions, "scalar_evidence_for", None)
    start = getattr(actions, "start", None)
    if observed <= 0 or start is None or not callable(reader):
        return False
    evidence = tuple(event for event in reader((security_id,)) if event.session > start)
    sessions = sorted({event.session for event in evidence})
    if len(sessions) < 2:
        return False
    ratios = getattr(actions, "events", {}).get(security_id, ())
    owned = tuple(command for command in commands if command.security_id == security_id)
    for through in sessions[:-1]:
        prefix = CorpusActionLookup(start=start,
            events={security_id: tuple(item for item in ratios if item[0] <= through)},
            scalar_events=tuple(event for event in evidence if event.session <= through))
        if expected_book_from_commands(owned, actions=prefix).get(security_id, 0) == observed:
            return True
    return False
