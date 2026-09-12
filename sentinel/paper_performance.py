"""Permanent negative authority for unsupported Alpaca paper cash economics.

This module never changes broker balances or canonical strategy accounting.
The immutable account-scoped marker survives cycle and takeover-epoch changes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
from typing import Mapping

PREFIX = "paper-performance-invalid:v1:"
SCHEMA = "sentinel.paper-performance-invalid/1"
REASON = "ALPACA_PAPER_PERFORMANCE_INVALID"


def _account(binding: Mapping | None) -> dict | None:
    if not isinstance(binding, Mapping) or binding.get("broker") != "alpaca":
        return None
    account_id = binding.get("broker_account_id")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("paper performance requires an exact broker account")
    return {"broker": "alpaca", "broker_account_id": account_id}


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def cursor(binding: Mapping) -> str | None:
    identity = _account(binding)
    return PREFIX + _hash(identity) if identity is not None else None


def load(conn, binding: Mapping | None) -> dict | None:
    from sentinel.trial import _stored, TrialEvidenceRefused

    name = cursor(binding)
    if name is None:
        return None
    stored = _stored(conn, name)
    if stored is None:
        return None
    session, marker = stored
    body = {key: value for key, value in marker.items() if key != "evidence_sha256"}
    if (marker.get("schema") != SCHEMA or marker.get("account") != _account(binding)
            or marker.get("first_affected_session") != session.isoformat()
            or marker.get("performance_valid") is not False
            or marker.get("evidence_sha256") != _hash(body)
            or not marker.get("canonical_entitlements")):
        raise TrialEvidenceRefused("durable paper performance quarantine is malformed")
    return marker


def project(verification: Mapping, marker: Mapping | None) -> dict:
    result = deepcopy(dict(verification))
    if marker is None:
        return result
    if result.get("session", "") < marker["first_affected_session"]:
        return result
    if _account(result.get("binding")) != marker["account"]:
        raise ValueError("paper performance quarantine belongs to another account")
    if (result.get("performance", {}).get("performance_valid") is False
            and result.get("paper_performance_quarantine") == marker):
        return result
    result["verdict"] = "NOT_VERIFIED"
    result["reason_codes"] = sorted(set(result.get("reason_codes", ())) | {REASON})
    performance = result.setdefault("performance", {})
    performance.update({
        "performance_valid": False,
        "invalid_since": marker["first_affected_session"],
        "quarantine_sha256": marker["evidence_sha256"],
        "strategy_pl": None, "daily_return": None,
        "cumulative_factor": None, "total_return": None,
    })
    result["paper_performance_quarantine"] = dict(marker)
    if "evidence_sha256" in result:
        result["stored_verification_sha256"] = result.pop("evidence_sha256")
        result["projection_kind"] = "permanent-paper-performance-quarantine/v1"
        result["evidence_sha256"] = _hash(result)
    return result


def record_and_project(conn, verification: Mapping) -> dict:
    """Persist negative authority even while a cycle's close proof is pending."""
    from sentinel.trial import _insert_immutable

    binding = verification.get("binding")
    identity = _account(binding)
    if identity is None:
        return dict(verification)
    marker = load(conn, binding)
    entitlements = (verification.get("paper_limitations") or {}).get("expected_dividends")
    if marker is None and entitlements:
        first = min(str(item["accrued_session"]) for item in entitlements)
        marker = {
            "schema": SCHEMA, "account": identity, "binding": dict(binding),
            "first_affected_session": first, "performance_valid": False,
            "canonical_entitlements": deepcopy(entitlements),
            "publication": deepcopy(verification.get("publication")),
            "observed_broker_account": deepcopy(
                (verification.get("account_evidence") or {}).get("account")),
            "broker_cash_evidence": deepcopy(verification.get("cash")),
            "synthetic_adjustment": None,
        }
        marker["evidence_sha256"] = _hash(marker)
        marker = _insert_immutable(
            conn, name=cursor(binding), session=date.fromisoformat(first), state=marker)
    return project(verification, marker)


def scan_entitlements(conn, *, binding: Mapping, through: date, account) -> dict | None:
    """Detect missed-cycle entitlements from account-bound dated fill evidence.

    Called by PAPER preparation under the published corpus pin, before account
    sizing. The first marker ends further scans for this account permanently.
    """
    from sentinel.trial import (
        _expected_effective_equity_dividends, _expected_defensive_dividends,
        _cash_rows, TrialEvidenceRefused,
    )
    from sentinel.core.terminal import DIVIDEND_ACTIONS
    from sentinel.feed import calendar
    from sentinel.execution.reconcile import corpus_action_lookup

    if _account(binding) is None:
        return None
    marker = load(conn, binding)
    if marker is not None:
        return marker
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.security_id,c.side,f.quantity,f.filled_at"
            " FROM sentinel_fills f JOIN sentinel_commands c ON c.client_key=f.client_key"
            " AND c.broker_order_id=f.broker_order_id"
            " WHERE c.broker=%s AND c.broker_account_id=%s ORDER BY f.filled_at,f.fill_key",
            (binding["broker"], binding["broker_account_id"]))
        fills = cur.fetchall()
    if not fills:
        return None
    if any(stamp is None for _sid, _side, _quantity, stamp in fills):
        raise TrialEvidenceRefused("paper dividend ownership has undated broker fills")
    first = min(stamp.date() for _sid, _side, _quantity, stamp in fills)
    if first > through:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT session FROM sentinel_active_actions"
            " WHERE session BETWEEN %s AND %s AND LOWER(action)=ANY(%s) ORDER BY session",
            (first, through, sorted(DIVIDEND_ACTIONS)))
        days = sorted({calendar.session_on_or_after(str(row[0])) for row in cur.fetchall()})
    for day in days:
        if day > through.isoformat():
            continue
        opened, _ = calendar.session_window(date.fromisoformat(day))
        pre_open = {}
        actions = corpus_action_lookup(conn, start=first, end=date.fromisoformat(day))
        for sid, side, quantity, stamp in fills:
            if stamp >= opened:
                continue
            if side not in {"BUY", "SELL"}:
                raise TrialEvidenceRefused("paper dividend ownership has an invalid fill side")
            amount = Decimal(str(quantity)) * actions(str(sid), stamp.date())
            if not amount.is_finite() or amount < 0:
                raise TrialEvidenceRefused("paper dividend ownership has invalid fill quantities")
            pre_open[str(sid)] = pre_open.get(str(sid), Decimal(0)) + (
                amount if side == "BUY" else -amount)
        if any(quantity < 0 for quantity in pre_open.values()):
            raise TrialEvidenceRefused("paper dividend ownership cannot reconstruct pre-open shares")
        expected = _expected_effective_equity_dividends(
            conn, date.fromisoformat(day), pre_open, [])
        expected += _expected_defensive_dividends(
            conn, date.fromisoformat(day), pre_open, [])
        if expected:
            from sentinel.feed import publication
            cash_rows, external, internal = _cash_rows(conn, date.fromisoformat(day))
            result = record_and_project(conn, {
                "binding": dict(binding), "session": day,
                "publication": publication.require_current(conn).to_dict(),
                "paper_limitations": {"expected_dividends": expected},
                "account_evidence": {"account": {
                    "cash": str(account.cash), "equity": str(account.equity)}},
                "cash": {"rows": cash_rows, "external": str(external),
                         "internal": str(internal)},
            })
            return result["paper_performance_quarantine"]
    return None
