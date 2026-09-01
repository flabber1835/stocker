"""Strict financial-boundary validation for persisted Wealth Core state.

The canonical state dataclasses deliberately stay simple runtime containers.
Values that can change a future order, exit, cooldown, valuation, or terminal
settlement must be proven well-formed before ``PortfolioState.from_dict`` is
allowed to return them.  ``PortfolioState.from_dict`` calls this owner directly;
importing the package never mutates the state class.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


def _fail(where, detail):
    raise ValueError("persisted Wealth Core %s %s" % (where, detail))


def _text(value, where, allow_none=False, allow_empty=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        _fail(where, "must be text")
    if not allow_empty and not value.strip():
        _fail(where, "must be non-empty text")
    return value


def _finite(value, where, *, positive=False, non_negative=False):
    if isinstance(value, bool):
        _fail(where, "is not a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        _fail(where, "is not a finite number")
    if not math.isfinite(result):
        _fail(where, "must be finite")
    if positive and result <= 0:
        _fail(where, "must be finite and positive")
    if non_negative and result < 0:
        _fail(where, "must be finite and non-negative")
    return result


def _exact_int(value, where, *, minimum=0, maximum_exclusive=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(where, "must be an exact integer")
    if value < minimum:
        _fail(where, "must be >= %d" % minimum)
    if maximum_exclusive is not None and value >= maximum_exclusive:
        _fail(where, "must be < %d" % maximum_exclusive)
    return value


def _bool(value, where):
    if type(value) is not bool:
        _fail(where, "must be boolean")
    return value


def _index_key(value, where):
    if isinstance(value, bool):
        _fail(where, "is not an integer identity")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            result = int(stripped)
        except ValueError:
            _fail(where, "is not an integer identity")
        if stripped != str(result):
            _fail(where, "is not a canonical integer identity")
    else:
        _fail(where, "is not an integer identity")
    if result < 0:
        _fail(where, "must be non-negative")
    return result


def _mapping(value, where, *, absent_empty=False):
    if value is None and absent_empty:
        return {}
    if not isinstance(value, Mapping):
        _fail(where, "must be an object")
    return value


def _validate_slot(slot_id, raw, *, cooldown_sessions):
    raw = _mapping(raw, "slot %d" % slot_id)
    declared = _exact_int(raw.get("slot_id"), "slot %d slot_id" % slot_id)
    if declared != slot_id:
        _fail("slot %d" % slot_id, "key and slot_id disagree")

    occupied = raw.get("occupied_by")
    if occupied is not None:
        _text(occupied, "slot %d occupied_by" % slot_id)

    cooldown = raw.get("cooldown_sessions_elapsed")
    if cooldown is not None:
        _exact_int(
            cooldown,
            "slot %d cooldown_sessions_elapsed" % slot_id,
            maximum_exclusive=cooldown_sessions,
        )

    reservation = (
        raw.get("reserved_for"),
        raw.get("reserved_ticker"),
        raw.get("reserved_issuer"),
    )
    present = tuple(value is not None for value in reservation)
    if any(present) and not all(present):
        _fail("slot %d reservation" % slot_id,
              "must provide security, ticker, and issuer together")
    if all(present):
        _text(reservation[0], "slot %d reserved_for" % slot_id)
        _text(reservation[1], "slot %d reserved_ticker" % slot_id)
        _text(reservation[2], "slot %d reserved_issuer" % slot_id)

    if occupied is not None and any(present):
        _fail("slot %d" % slot_id,
              "cannot be both occupied and reserved")
    if cooldown is not None and (occupied is not None or any(present)):
        _fail("slot %d" % slot_id,
              "cannot cool down while occupied or reserved")

    return {
        "occupied_by": occupied,
        "cooldown": cooldown,
        "reserved_for": reservation[0],
        "reserved_ticker": reservation[1],
        "reserved_issuer": reservation[2],
    }


def _validate_episode(slot_id, raw):
    raw = _mapping(raw, "episode %d" % slot_id)
    required = (
        "security_id", "ticker", "issuer_id", "slot_id", "signal_date",
        "entry_date", "entry_raw_open", "entry_split_adjusted_price",
        "initial_shares", "current_shares",
    )
    missing = [name for name in required if name not in raw]
    if missing:
        _fail("episode %d" % slot_id,
              "is missing required fields: %s" % ", ".join(missing))

    security_id = _text(raw.get("security_id"),
                        "episode %d security_id" % slot_id)
    ticker = _text(raw.get("ticker"), "episode %d ticker" % slot_id)
    issuer_id = _text(raw.get("issuer_id"),
                      "episode %d issuer_id" % slot_id)
    declared = _exact_int(raw.get("slot_id"), "episode %d slot_id" % slot_id)
    if declared != slot_id:
        _fail("episode %d" % slot_id, "key and slot_id disagree")
    _text(raw.get("signal_date"), "episode %d signal_date" % slot_id)
    _text(raw.get("entry_date"), "episode %d entry_date" % slot_id)
    _finite(raw.get("entry_raw_open"),
            "episode %d entry_raw_open" % slot_id, positive=True)
    _finite(raw.get("entry_split_adjusted_price"),
            "episode %d entry_split_adjusted_price" % slot_id,
            positive=True)
    _finite(raw.get("initial_shares"),
            "episode %d initial_shares" % slot_id, positive=True)
    _finite(raw.get("current_shares"),
            "episode %d current_shares" % slot_id, positive=True)

    peak = raw.get("episode_peak_split_adjusted_close")
    if peak is not None:
        _finite(peak, "episode %d episode_peak_split_adjusted_close" % slot_id,
                positive=True)
    _exact_int(raw.get("market_sessions_held", 0),
               "episode %d market_sessions_held" % slot_id)
    _bool(raw.get("review_completed", False),
          "episode %d review_completed" % slot_id)
    _bool(raw.get("exit_pending", False),
          "episode %d exit_pending" % slot_id)
    exit_reason = raw.get("exit_reason")
    if exit_reason is not None:
        _text(exit_reason, "episode %d exit_reason" % slot_id)

    source_lots = raw.get("source_lots", [])
    if not isinstance(source_lots, list):
        _fail("episode %d source_lots" % slot_id, "must be a list")
    for index, lot in enumerate(source_lots):
        if not isinstance(lot, Mapping):
            _fail("episode %d source_lot %d" % (slot_id, index),
                  "must be an object")

    return {
        "security_id": security_id,
        "ticker": ticker,
        "issuer_id": issuer_id,
    }


def _validate_counter_map(raw, where, *, maximum_exclusive=None):
    raw = _mapping(raw, where, absent_empty=True)
    out = {}
    for key, value in raw.items():
        key = _text(key, "%s key" % where)
        out[key] = _exact_int(
            value, "%s[%s]" % (where, key),
            maximum_exclusive=maximum_exclusive)
    return out


def _validate_text_map(raw, where):
    raw = _mapping(raw, where, absent_empty=True)
    out = {}
    for key, value in raw.items():
        key = _text(key, "%s key" % where)
        out[key] = _text(value, "%s[%s]" % (where, key))
    return out


def _validate_pending_record(sec, raw, held_shares):
    raw = _mapping(raw, "terminal_pending_terms[%s]" % sec)
    if "terms" not in raw or "stale_at_event" not in raw:
        _fail("terminal_pending_terms[%s]" % sec,
              "must contain terms and stale_at_event")

    from stock_strategy_shared.wealth_core.settlement import MARK_RECENCY_SESSIONS
    from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

    stale = _exact_int(raw.get("stale_at_event"),
                       "terminal_pending_terms[%s].stale_at_event" % sec)
    if stale > MARK_RECENCY_SESSIONS:
        _fail("terminal_pending_terms[%s].stale_at_event" % sec,
              "exceeds the mark-recency bound that permits a carry")

    terms_raw = _mapping(raw.get("terms"),
                         "terminal_pending_terms[%s].terms" % sec)
    if "kind" not in terms_raw:
        _fail("terminal_pending_terms[%s].terms" % sec, "is missing kind")
    try:
        kind = TerminalKind(terms_raw.get("kind"))
    except (TypeError, ValueError):
        _fail("terminal_pending_terms[%s].terms.kind" % sec,
              "is not a known terminal kind")

    normalized = dict(terms_raw)
    normalized["kind"] = kind
    try:
        terms = TerminalTerms(**normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "persisted Wealth Core terminal_pending_terms[%s].terms is invalid: %s"
            % (sec, exc)) from exc

    _text(terms.session, "terminal_pending_terms[%s].terms.session" % sec)
    _text(terms.security_id,
          "terminal_pending_terms[%s].terms.security_id" % sec)
    if terms.security_id != sec:
        _fail("terminal_pending_terms[%s].terms" % sec,
              "security_id disagrees with its map key")
    _text(terms.reference,
          "terminal_pending_terms[%s].terms.reference" % sec,
          allow_empty=True)

    if terms.cash_per_share is not None:
        _finite(terms.cash_per_share,
                "terminal_pending_terms[%s].terms.cash_per_share" % sec,
                non_negative=True)
    if terms.exchange_ratio is not None:
        _finite(terms.exchange_ratio,
                "terminal_pending_terms[%s].terms.exchange_ratio" % sec,
                positive=True)
    if terms.cash_in_lieu_price_per_delivered_share is not None:
        _finite(
            terms.cash_in_lieu_price_per_delivered_share,
            "terminal_pending_terms[%s].terms.cash_in_lieu_price_per_delivered_share"
            % sec,
            non_negative=True)
    for name in ("delivered_security_id", "delivered_ticker",
                 "delivered_issuer_id"):
        value = getattr(terms, name)
        if value is not None:
            _text(value, "terminal_pending_terms[%s].terms.%s" % (sec, name))

    # Exercise the kind-specific arithmetic against the restored holding.  An
    # incomplete event is valid here; exceptions or non-finite arithmetic are not.
    try:
        terms.completeness(held_shares)
    except Exception as exc:
        raise ValueError(
            "persisted Wealth Core terminal_pending_terms[%s].terms cannot be "
            "evaluated against restored shares: %s" % (sec, exc)) from exc


def validate_payload(d, *, cooldown_sessions):
    if not isinstance(d, Mapping):
        _fail("state", "is not an object")

    raw_slots = _mapping(d.get("slots"), "slots")
    if not raw_slots:
        _fail("slots", "has no slot domain")
    slots = {}
    for raw_key, raw_slot in raw_slots.items():
        slot_id = _index_key(raw_key, "slot key")
        if slot_id in slots:
            _fail("slots", "contains colliding integer identities")
        slots[slot_id] = _validate_slot(
            slot_id, raw_slot, cooldown_sessions=cooldown_sessions)
    if sorted(slots) != list(range(len(slots))):
        _fail("slots", "are not a contiguous zero-based domain")

    raw_episodes = _mapping(
        d.get("episodes"), "episodes", absent_empty=True)
    episodes = {}
    for raw_key, raw_episode in raw_episodes.items():
        slot_id = _index_key(raw_key, "episode key")
        if slot_id in episodes:
            _fail("episodes", "contains colliding integer identities")
        if slot_id not in slots:
            _fail("episode %d" % slot_id, "references a nonexistent slot")
        episodes[slot_id] = _validate_episode(slot_id, raw_episode)

    for slot_id, slot in slots.items():
        episode = episodes.get(slot_id)
        occupied = slot["occupied_by"]
        if episode is None and occupied is not None:
            _fail("slot %d" % slot_id,
                  "claims an occupant but has no holding episode")
        if episode is not None and occupied != episode["security_id"]:
            _fail("slot %d" % slot_id,
                  "occupant disagrees with its holding episode")

    held = {episode["security_id"] for episode in episodes.values()}
    held_shares = {}
    for slot_id, raw_episode in raw_episodes.items():
        episode_id = _index_key(slot_id, "episode key")
        sec = episodes[episode_id]["security_id"]
        held_shares[sec] = held_shares.get(sec, 0.0) + float(
            raw_episode["current_shares"])

    reserved = [slot["reserved_for"] for slot in slots.values()
                if slot["reserved_for"] is not None]
    reserved_issuers = [slot["reserved_issuer"] for slot in slots.values()
                        if slot["reserved_issuer"] is not None]
    if len(reserved) != len(set(reserved)):
        _fail("slots", "contain duplicate security reservations")
    if len(reserved_issuers) != len(set(reserved_issuers)):
        _fail("slots", "contain duplicate issuer reservations")
    overlap = held.intersection(reserved)
    if overlap:
        _fail("slots", "reserve already-held securities: %s" % sorted(overlap))

    _validate_counter_map(
        d.get("security_cooldowns"), "security_cooldowns",
        maximum_exclusive=cooldown_sessions)

    unresolved = _validate_text_map(
        d.get("unresolved_terminals"), "unresolved_terminals")
    stale = _validate_counter_map(
        d.get("sessions_since_valid_mark"), "sessions_since_valid_mark")

    from stock_strategy_shared.wealth_core.settlement import C1_GRACE_SESSIONS
    pending = _validate_counter_map(
        d.get("terminal_pending_sessions"), "terminal_pending_sessions",
        maximum_exclusive=C1_GRACE_SESSIONS)
    pending_terms = _mapping(
        d.get("terminal_pending_terms"), "terminal_pending_terms",
        absent_empty=True)
    pending_term_keys = {
        _text(key, "terminal_pending_terms key") for key in pending_terms
    }
    if set(pending) != pending_term_keys:
        _fail("terminal pending state",
              "counter and stored-term keys disagree")

    for name, mapping in (("unresolved_terminals", unresolved),
                          ("sessions_since_valid_mark", stale),
                          ("terminal_pending_sessions", pending)):
        extras = set(mapping) - held
        if extras:
            _fail(name, "contains non-held securities: %s" % sorted(extras))
    overlap = set(unresolved).intersection(pending)
    if overlap:
        _fail("terminal state",
              "cannot be both unresolved and pending: %s" % sorted(overlap))

    for sec in sorted(pending):
        _validate_pending_record(sec, pending_terms[sec], held_shares[sec])

    carry_audit = _mapping(
        d.get("terminal_carry_audit"), "terminal_carry_audit",
        absent_empty=True)
    for sec, record in carry_audit.items():
        _text(sec, "terminal_carry_audit key")
        if sec not in held:
            _fail("terminal_carry_audit",
                  "contains non-held security %s" % sec)
        _mapping(record, "terminal_carry_audit[%s]" % sec)

    last_mark_session = _mapping(
        d.get("last_valid_mark_session"), "last_valid_mark_session",
        absent_empty=True)
    for sec, session in last_mark_session.items():
        _text(sec, "last_valid_mark_session key")
        if sec not in held:
            _fail("last_valid_mark_session",
                  "contains non-held security %s" % sec)
        _text(session, "last_valid_mark_session[%s]" % sec)


__all__ = ["validate_payload"]
