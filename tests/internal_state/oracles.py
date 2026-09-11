"""Independent equations and structural contracts; no production guard imports."""
from __future__ import annotations

from decimal import Decimal as D
from copy import deepcopy
import math

from .contract import check, digest

TRANSITIONS = {
    "PLANNED": {"SEND_PENDING", "SUPERSEDED"},
    "SEND_PENDING": {"ACKNOWLEDGED", "REJECTED", "UNKNOWN"},
    "ACKNOWLEDGED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "UNKNOWN"},
    "UNKNOWN": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "REJECTED"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "UNKNOWN"},
    "CANCEL_PENDING": {"CANCELLED", "FILLED", "PARTIALLY_FILLED", "UNKNOWN"},
    "FILLED": set(), "CANCELLED": set(), "REJECTED": set(), "SUPERSEDED": set(),
}
IN_FLIGHT = {"SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN", "PARTIALLY_FILLED", "CANCEL_PENDING"}


def broker_accounting(world):
    cash = D(world["initial_cash"]) + sum(map(D, world["movements"]), D(0))
    positions = {}
    for fill in world["fills"]:
        quantity = D(fill["sign"]) * D(fill["quantity"])
        cash -= quantity * D(fill["price"])
        symbol = fill["symbol"]
        positions[symbol] = positions.get(symbol, D(0)) + quantity
    check("broker_cash_conservation", cash, D(world["cash"]))
    actual = {k: D(v) for k, v in world["positions"].items() if D(v)}
    check("broker_share_conservation", {k: v for k, v in positions.items() if v}, actual)
    check("long_only_cash", True, cash >= 0)
    check("long_only_positions", True, all(v >= 0 for v in actual.values()))
    keys = [o["client_order_id"] for o in world["orders"].values()]
    check("one_broker_order_per_key", len(keys), len(set(keys)))
    for order in world["orders"].values():
        check("broker_fill_bounds", True, D(0) <= D(order["filled_qty"]) <= D(order["qty"]))


def canonical_state(raw, *, identity, cursor):
    check("strategy_identity", identity, raw["strategy_identity"])
    check("state_cursor_atomicity", cursor, raw["last_processed_session"])
    check("controller_cursor", cursor, raw["controller"]["last_session"])
    check("decision_cursor", cursor, raw["last_decision"]["session"])
    check("witness_cursor", cursor, raw["recent_leadership"]["last_session"])
    check("ldrc_cursor", cursor, raw["ldrc"]["last_session"])
    check("shadow_peak_nonnegative", True, raw["shadow_peak_nav"] >= 0)
    check("exposure_bounds", True, 0 <= raw["last_decision"]["target_core_exposure"] <= 1)
    check("wealth_core_slots", 25, len(raw["wealth_core"]["slots"]))
    occupied = [s["occupied_by"] for s in raw["wealth_core"]["slots"].values() if s["occupied_by"]]
    check("one_slot_per_episode", len(occupied), len(set(occupied)))
    portfolio = raw["wealth_core"]
    episodes = portfolio["episodes"]
    shares = {}
    for slot_id, episode in episodes.items():
        check("episode_slot_ownership", episode["security_id"], portfolio["slots"][str(slot_id)]["occupied_by"])
        check("positive_shadow_shares", True, D(str(episode["current_shares"])) > 0)
        check("nonnegative_episode_age", True, episode["market_sessions_held"] >= 0)
        shares[episode["security_id"]] = shares.get(episode["security_id"], D(0)) + D(str(episode["current_shares"]))
    for slot_id, slot in portfolio["slots"].items():
        check("occupied_slot_has_episode", bool(slot["occupied_by"]), str(slot_id) in episodes)
        if slot.get("reserved_for"):
            check("reservation_has_pending_entry", True, any(
                p["operation"] == "OPEN_SLOT_POSITION" and str(p["slot_id"]) == str(slot_id)
                and p["security_id"] == slot["reserved_for"] for p in raw["pending"]))
    for pending in raw["pending"]:
        check("pending_age_nonnegative", True, pending["sessions_waiting"] >= 0)
        if pending["operation"] == "OPEN_SLOT_POSITION":
            check("pending_entry_has_reservation", pending["security_id"],
                  portfolio["slots"][str(pending["slot_id"])]["reserved_for"])
    # Initial capital is a fixed input to this fixture. No broker event enters
    # the shadow equations. Arithmetic here does not call production ledgers.
    cash, ledger_shares = 100000.0, {}
    for event in raw["ledger"]["events"]:
        check("shadow_cash_event_continuity", True, abs(cash - event["cash_before"]) <= 1e-7)
        if event["event_type"] in {"BUY", "SELL"}:
            cash_delta = -float(event["shares_delta"]) * event["price"] - event["fees"]
            check("shadow_trade_conservation", True, abs(cash_delta - event["cash_delta"]) <= 1e-7)
        cash += event["cash_delta"]
        check("shadow_event_cash_after", True, abs(cash - event["cash_after"]) <= 1e-7)
        if event["security_id"]:
            sid = event["security_id"]
            ledger_shares[sid] = ledger_shares.get(sid, D(0)) + D(str(event["shares_delta"]))
    check("shadow_cash_conservation", True, abs(cash - portfolio["cash"]) <= 1e-7)
    check("shadow_share_conservation", {k: v for k, v in ledger_shares.items() if v}, shares)
    for series in raw["feed"]["series"].values():
        lengths = {len(series[k]) for k in ("sessions", "session_indices", "signal_closes", "raw_closes", "volumes")}
        check("aligned_feed_series", 1, len(lengths))
        dates = series["sessions"]
        check("bounded_restart_series", True, len(dates) <= 127)
        check("causal_feed_sessions", sorted(set(dates)), dates)
        check("no_future_observation", True, all(d <= cursor for d in dates))
    def finite(value):
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return not isinstance(value, float) or math.isfinite(value)
    check("finite_state", True, finite(raw))


def plan_commitment(raw, plan, cursor):
    check("plan_cursor_atomicity", cursor, plan["decision_session"])
    check("plan_state_commitment", digest(raw), plan["shadow_snapshot_hash"])
    check("plan_transition_commitment", digest(raw["last_decision"]), plan["sentinel_transition_hash"])
    check("plan_strategy_commitment", digest(raw["strategy_identity"]), plan["strategy_fingerprint"])
    check("plan_data_commitment", raw["data_version"], plan["data_version"])


def journal_contract(commands, histories, world, prior_economics, *, restored=False):
    live = {}
    orders = {o["client_order_id"]: o for o in world["orders"].values()}
    for command in commands:
        key, state = command["client_key"], command["state"]
        economics = {k: command[k] for k in ("identity", "instrument", "side", "quantity")}
        if key in prior_economics:
            expected = prior_economics[key]
            if (restored and command.get("recovered_key") == key and key in orders
                    and economics["identity"]["plan_id"] == "RECOVERED"
                    and expected["identity"]["plan_id"].startswith("sentinel-")):
                expected = deepcopy(expected)
                expected["identity"]["plan_id"] = "RECOVERED"
            check("immutable_command_economics", expected, economics)
        prior_economics[key] = economics
        quantity, filled = D(command["quantity"]), D(command["filled_quantity"])
        check("journal_fill_bounds", True, D(0) <= filled <= quantity)
        previous_fill = D(0)
        previous_state = None
        for event in histories[key]:
            src, target = event["from"], event["to"]
            if src is not None:
                check("legal_command_transition", True, target in TRANSITIONS[src])
                check("journal_transition_continuity", previous_state, src)
            if event["filled"] is not None:
                check("monotone_fill_evidence", True, D(event["filled"]) >= previous_fill)
                previous_fill = D(event["filled"])
            previous_state = target
        check("journal_current_state", state, previous_state)
        if state in IN_FLIGHT:
            security = command["identity"]["security_id"]
            live.setdefault(security, []).append(key)
        if key in orders:
            order = orders[key]
            check("durable_wire_quantity", quantity, D(order["qty"]))
            check("durable_wire_side", command["side"].lower(), order["side"])
            check("durable_wire_symbol", command["instrument"]["symbol"], order["symbol"])
            check("journal_cannot_invent_fills", True, filled <= D(order["filled_qty"]))
    check("one_inflight_per_security", True, all(len(v) <= 1 for v in live.values()))


def unchanged(name, before, after):
    check(name, digest(before), digest(after))
