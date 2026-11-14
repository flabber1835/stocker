"""Current corporate-action restrictions; no negative-evidence certificate.

The action lookup and broker observation remain the evidence. Restrictions
are recomputed, never acknowledged away or latched from historical incidents.
"""
from __future__ import annotations

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


def material_restrictions(actions, symbols: Mapping[str, str]) -> dict[str, str]:
    """Map known unsupported events onto the current economic identities."""
    finder = getattr(actions, "material_events_for", None)
    if not callable(finder):
        return {}
    result = {}
    for event in finder(security_ids=symbols, symbols=symbols.values()):
        for sid, symbol in symbols.items():
            if (event.security_id == sid
                    or str(event.ticker).upper() == str(symbol).upper()):
                result[sid] = (
                    f"CORPORATE_ACTION_PENDING: {event.action} "
                    f"{event.session} source={event.source_row_id}")
    return dict(sorted(result.items()))


def position_restrictions(*, actions, commands, observation,
                          expected_raw, expected) -> dict[str, str]:
    held = observation.positions_by_security()
    active = {sid for sid, quantity in expected.items() if quantity != 0}
    active.update(sid for sid, quantity in held.items() if quantity != 0)
    active.update(order.instrument.security_id for order in observation.orders
                  if order.is_working)
    symbols = {command.security_id: command.instrument.symbol
               for command in commands if command.security_id in active}
    symbols.update({position.instrument.security_id: position.instrument.symbol
                    for position in observation.positions
                    if position.instrument.security_id in active})
    symbols.update({order.instrument.security_id: order.instrument.symbol
                    for order in observation.orders if order.is_working})
    result = material_restrictions(actions, symbols)
    for sid in active:
        raw = expected_raw.get(sid, Decimal(0))
        aged = expected.get(sid, Decimal(0))
        # Recognize only an unchanged, attributable position. An arbitrary
        # difference is still foreign activity, even on a split day.
        if raw > 0 and aged != raw and held.get(sid, Decimal(0)) == raw:
            result[sid] = "CORPORATE_ACTION_PENDING: broker quantity is still in prior share units"
    return dict(sorted(result.items()))


def entitlement_matches_observation(entitlement, held, prior, increment):
    """Recognize plausible unit-transition evidence without assigning it as shares."""
    if entitlement <= 0 or held < 0:
        return False
    if prior > 0 and held == prior:
        return True
    lot = Fraction(increment)
    floor = (entitlement // lot) * lot
    return Fraction(held) in {floor, floor + lot}
