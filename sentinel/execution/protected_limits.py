"""Historical RAW references and immutable paper LIMIT/DAY BUY sizing.

These references are never executable quotes. Source rows are read again under
the exact authenticated plan publication; current funding is a separate gate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import os
import re
from types import MappingProxyType
from typing import Mapping

from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.target_reprojection import TargetProjectionRefused


PROTECTED_MODE = "PROTECTED_LIMIT_DAY_V1"
REFERENCE_SOURCE = "AUTHENTICATED_PRIOR_CLOSED_RAW_V1"
POLICY_SCHEMA = "sentinel.protected-limit-policy/1"
REFERENCE_SCHEMA = "sentinel.prior-close-references/1"
HEADROOM = Decimal("1.00")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class ProtectedReferenceUnavailable(TargetProjectionRefused):
    """Only this BUY lacks usable historical price/allocation evidence."""


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _positive(value, label):
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise TargetProjectionRefused(f"{label} must be positive finite Decimal")
    return value


@dataclass(frozen=True)
class ProtectedLimitPolicy:
    cap_bps: int

    def __post_init__(self):
        if type(self.cap_bps) is not int or not 0 <= self.cap_bps <= 500:
            raise TargetProjectionRefused("protected BUY cap must be an integer from 0 through 500")

    @classmethod
    def from_env(cls):
        selected = os.environ.get("SENTINEL_PAPER_BUY_POLICY", "").strip()
        if not selected:
            if os.environ.get("SENTINEL_PAPER_BUY_CAP_BPS", "").strip():
                raise TargetProjectionRefused("protected BUY cap requires its explicit policy")
            return None
        if selected != PROTECTED_MODE:
            raise TargetProjectionRefused("unknown paper BUY policy")
        raw = os.environ.get("SENTINEL_PAPER_BUY_CAP_BPS", "").strip()
        if not re.fullmatch(r"0|[1-9][0-9]*", raw):
            raise TargetProjectionRefused("protected BUY policy requires an explicit integer cap")
        try:
            return cls(int(raw))
        except ValueError as exc:
            raise TargetProjectionRefused("protected BUY cap is not usable") from exc

    def to_dict(self):
        return {"schema": POLICY_SCHEMA, "profile": PROTECTED_MODE,
            "cap_bps": self.cap_bps, "cap_ceiling_bps": 500, "reference_recipe": REFERENCE_SOURCE,
            "quantity_rounding": "WHOLE_SHARES_DOWN", "tick_rule": "USD_1_CENT_OR_SUBDOLLAR_1E4_DOWN_V1",
            "fixed_target_limit": "REFERENCE_CAP_AND_ALLOCATED_BUDGET_LESS_HEADROOM_V1",
            "time_in_force": "day", "order_class": "simple", "extended_hours": False,
            "start_delay_seconds": 60, "new_submit_cutoff_seconds": 600,
            "buy_cash_headroom": "1.00"}

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise TargetProjectionRefused("protected BUY policy has an invalid shape")
        value = cls(raw.get("cap_bps"))
        if raw != value.to_dict():
            raise TargetProjectionRefused("protected BUY policy terms are unsupported")
        return value

    def fingerprint(self):
        return _digest(self.to_dict())


@dataclass(frozen=True)
class PriorCloseReferences:
    plan_fingerprint: str
    decision_session: date
    effective_session: date
    publication_fingerprint: str
    candidate_id: str
    snapshot_id: str
    manifest_sha256: str
    source_provider: str
    prices: Mapping[str, Decimal]
    symbols: Mapping[str, str]
    unit_factors: Mapping[str, str]
    action_evidence_sha256: str
    provider_asset_ids: Mapping[str, str]

    def __post_init__(self):
        from sentinel.feed import calendar
        if (type(self.decision_session) is not date or type(self.effective_session) is not date
                or str(self.effective_session) != calendar.next_session(self.decision_session)):
            raise TargetProjectionRefused("prior RAW reference sessions are invalid")
        for name in ("plan_fingerprint", "publication_fingerprint", "snapshot_id",
                     "manifest_sha256", "action_evidence_sha256"):
            if not isinstance(getattr(self, name), str) or not _HEX.fullmatch(getattr(self, name)):
                raise TargetProjectionRefused(f"prior RAW reference {name} is invalid")
        if (type(self.candidate_id) is not str or not self.candidate_id
                or type(self.source_provider) is not str or not self.source_provider):
            raise TargetProjectionRefused("prior RAW references lack source identity")
        symbols = dict(self.symbols)
        if (not symbols or any(type(sid) is not str or not sid or type(symbol) is not str
                              or not symbol for sid, symbol in symbols.items())
                or len(set(symbols.values())) != len(symbols)):
            raise TargetProjectionRefused("prior RAW reference symbols are ambiguous")
        prices, factors, assets = dict(self.prices), dict(self.unit_factors), dict(self.provider_asset_ids)
        if set(prices) - set(symbols) or set(factors) != set(symbols) or set(assets) - set(symbols):
            raise TargetProjectionRefused("prior RAW reference identities disagree")
        for sid, price in prices.items():
            _positive(price, f"prior RAW reference {sid}")
        for value in factors.values():
            try:
                factor = Fraction(value)
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                raise TargetProjectionRefused("prior RAW share factor is invalid") from exc
            if type(value) is not str or factor <= 0 or str(factor) != value:
                raise TargetProjectionRefused("prior RAW share factor is not canonical")
        if (any(type(value) is not str or not value for value in assets.values())
                or len(set(assets.values())) != len(assets)):
            raise TargetProjectionRefused("prior RAW native source identities are ambiguous")
        if self.source_provider == "ALPACA_OPENFIGI" and set(assets) != set(symbols) - {"SENTINEL:BIL"}:
            raise TargetProjectionRefused("Alpaca/OpenFIGI stock references require complete source-native identities")
        for name, values in (("prices", prices), ("symbols", symbols),
                             ("unit_factors", factors), ("provider_asset_ids", assets)):
            object.__setattr__(self, name, MappingProxyType(values))

    def to_dict(self):
        return {"schema": REFERENCE_SCHEMA, "source": REFERENCE_SOURCE,
            "plan_fingerprint": self.plan_fingerprint,
            "decision_session": str(self.decision_session), "effective_session": str(self.effective_session),
            "publication_fingerprint": self.publication_fingerprint,
            "candidate_id": self.candidate_id, "snapshot_id": self.snapshot_id,
            "manifest_sha256": self.manifest_sha256, "source_provider": self.source_provider,
            "prices": {sid: decimal_text(value) for sid, value in sorted(self.prices.items())},
            "symbols": dict(sorted(self.symbols.items())), "unit_factors": dict(sorted(self.unit_factors.items())),
            "action_evidence_sha256": self.action_evidence_sha256,
            "provider_asset_ids": dict(sorted(self.provider_asset_ids.items()))}

    @classmethod
    def from_dict(cls, raw):
        expected = {"schema", "source", "plan_fingerprint", "decision_session", "effective_session",
            "publication_fingerprint", "candidate_id", "snapshot_id", "manifest_sha256", "source_provider",
            "prices", "symbols", "unit_factors", "action_evidence_sha256", "provider_asset_ids"}
        if (not isinstance(raw, dict) or set(raw) != expected or raw["schema"] != REFERENCE_SCHEMA
                or raw["source"] != REFERENCE_SOURCE):
            raise TargetProjectionRefused("prior RAW references have an unsupported shape")
        try:
            if not isinstance(raw["prices"], dict) or any(type(value) is not str for value in raw["prices"].values()):
                raise ValueError("serialized RAW values must be decimal strings")
            return cls(raw["plan_fingerprint"], date.fromisoformat(raw["decision_session"]),
                date.fromisoformat(raw["effective_session"]), raw["publication_fingerprint"],
                raw["candidate_id"], raw["snapshot_id"], raw["manifest_sha256"], raw["source_provider"],
                {sid: Decimal(value) for sid, value in raw["prices"].items()}, raw["symbols"],
                raw["unit_factors"], raw["action_evidence_sha256"], raw["provider_asset_ids"])
        except (TypeError, ValueError, ArithmeticError, AttributeError) as exc:
            raise TargetProjectionRefused("prior RAW references are corrupt") from exc

    def fingerprint(self):
        return _digest(self.to_dict())


def _action_identity(projection):
    return _digest({"multipliers": {sid: decimal_text(value) for sid, value in
        sorted(projection.action_multipliers.items())}, "evidence": list(projection.action_evidence)})


def _factor(projection, sid):
    from sentinel.execution import target_reprojection as units
    multiplier = projection.action_multipliers.get(sid, Decimal(1))
    _positive(multiplier, "effective share multiplier")
    events = [item for item in projection.action_evidence if item.get("security_id") == sid]
    if not events:
        if multiplier != 1:
            raise TargetProjectionRefused("non-unit effective shares require durable action evidence")
        return Fraction(multiplier)
    published, exact = Fraction(1), Fraction(1)
    for item in events:
        if not item.get("source_row_id"):
            raise TargetProjectionRefused("effective share evidence lacks source identity")
        approximate, rational = units._evidence_factor(item)
        published *= approximate
        exact *= rational
    if not units._fractions_close(Fraction(multiplier), published, units._RATIO_REPRESENTATION_TOLERANCE):
        raise TargetProjectionRefused("effective share evidence differs from projection")
    return exact


def _wanted(plan, projection):
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    return ({sid for sid, qty in projection.target_basket.items() if qty > 0}
            | {item.security_id for item in plan.opening_intents} | {DEFENSIVE_SECURITY_ID})


def build_references(conn, *, plan, projection, policy=None):
    """Read exact RAW rows again, after authenticating the plan publication."""
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID, publication_fingerprint
    from sentinel.execution import feed_inputs
    from sentinel.feed.rolling_contract import digest
    wanted = _wanted(plan, projection)
    with feed_inputs.pinned(conn, commit=False) as pub:
        if (not feed_inputs.is_rolling(pub) or pub.version != plan.data_version
                or publication_fingerprint(pub) != plan.publication_fingerprint
                or str(pub.window_end) != str(plan.decision_session)
                or projection.plan_fingerprint != plan.fingerprint()
                or projection.through_session != plan.effective_session):
            raise TargetProjectionRefused("prior RAW reference publication differs from plan")
        refs = feed_inputs.references(conn, pub)
        resolver = feed_inputs.opening_resolver(conn, session=str(plan.effective_session))
        symbols = {}
        for sid in sorted(wanted):
            symbol = ("BIL" if sid == DEFENSIVE_SECURITY_ID else
                      resolver.ticker_for_security(sid, str(plan.effective_session)))
            if not symbol or (sid != DEFENSIVE_SECURITY_ID
                    and resolver.resolve(symbol, str(plan.effective_session)) != sid):
                raise TargetProjectionRefused("prior RAW reference has no unique effective identity")
            symbols[sid] = str(symbol)
        prices, seen = {}, set()
        with conn.cursor() as cur:
            cur.execute("SELECT security_id,ticker,close_unadjusted FROM sentinel_snapshot_bars "
                "WHERE candidate_id=%s AND session=%s AND security_id=ANY(%s)",
                (refs.candidate_id, str(plan.decision_session), sorted(wanted - {DEFENSIVE_SECURITY_ID})))
            for sid, ticker, close in cur.fetchall():
                sid = str(sid)
                if sid not in wanted or sid in seen or refs.resolver.resolve(str(ticker), str(plan.decision_session)) != sid:
                    raise TargetProjectionRefused("prior RAW source row identity is ambiguous")
                seen.add(sid)
                if close is not None:
                    prices[sid] = _positive(Decimal(str(close)), "prior RAW source close")
            cur.execute("SELECT bil_close_unadjusted FROM sentinel_snapshot_benchmarks "
                        "WHERE candidate_id=%s AND session=%s",
                        (refs.candidate_id, str(plan.decision_session)))
            rows = cur.fetchall()
        if len(rows) > 1:
            raise TargetProjectionRefused("prior RAW BIL source row is ambiguous")
        if rows and rows[0][0] is not None:
            prices[DEFENSIVE_SECURITY_ID] = _positive(Decimal(str(rows[0][0])), "prior RAW BIL close")
        source = feed_inputs.resolver(conn, pub, session=str(plan.effective_session))
        native = {sid: asset for sid, asset in source.provider_asset_ids.items() if sid in wanted}
        return PriorCloseReferences(plan.fingerprint(), plan.decision_session, plan.effective_session,
            publication_fingerprint(pub), refs.candidate_id, refs.manifest.snapshot_id,
            digest(refs.manifest.model_dump(mode="json")), refs.manifest.provider, prices, symbols,
            {sid: str(_factor(projection, sid)) for sid in wanted}, _action_identity(projection), native)


def limit_for(references, sid, policy):
    price = references.prices.get(sid)
    if price is None:
        return None
    adjusted = Fraction(price) / Fraction(references.unit_factors[sid])
    capped = adjusted * Fraction(10000 + policy.cap_bps, 10000)
    tick = Fraction(1, 100) if capped >= 1 else Fraction(1, 10000)
    limit = exact_decimal((capped // tick) * tick)
    return _positive(limit, "protected BUY limit")


def _projection_limits(projection, references, policy, *, account_nav, target_exposure, opening):
    """Full-target maxima; fixed quantities keep their allocated dollar budget."""
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    limits = {sid: limit_for(references, sid, policy) for sid in opening
              if sid in references.prices}
    fixed = []
    for sid, quantity in sorted(projection.target_basket.items()):
        if sid in opening or quantity <= 0:
            continue
        raw_cap = limit_for(references, sid, policy)
        kind = "BIL" if sid == DEFENSIVE_SECURITY_ID else "CORE"
        budget = ((1 - Fraction(target_exposure)) * Fraction(account_nav) if kind == "BIL"
                  else None if sid not in references.prices else
                  Fraction(quantity) * Fraction(references.prices[sid]) / Fraction(references.unit_factors[sid]))
        limit = None
        if raw_cap is not None and budget is not None and budget > Fraction(HEADROOM):
            affordable = min(Fraction(raw_cap), (budget - Fraction(HEADROOM)) / Fraction(quantity))
            tick = Fraction(1, 100) if affordable >= 1 else Fraction(1, 10000)
            rounded = (affordable // tick) * tick
            if rounded > 0:
                limit = exact_decimal(rounded)
                limits[sid] = limit
        fixed.append({"security_id": sid, "kind": kind, "target_quantity": decimal_text(quantity),
            "budget": None if budget is None else str(budget),
            "raw_cap": None if raw_cap is None else decimal_text(raw_cap),
            "limit": None if limit is None else decimal_text(limit),
            "status": "REFERENCE_UNAVAILABLE" if raw_cap is None else (
                "BUDGET_UNAVAILABLE" if limit is None else "READY")})
    return limits, fixed


def resolve_protected(state, plan, projection, references, policy):
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID, shadow_target, _shadow_equity
    if (not isinstance(references, PriorCloseReferences) or not isinstance(policy, ProtectedLimitPolicy)
            or state.state_hash != plan.shadow_snapshot_hash
            or projection.plan_fingerprint != plan.fingerprint()
            or projection.through_session != plan.effective_session
            or references.plan_fingerprint != plan.fingerprint()
            or references.publication_fingerprint != plan.publication_fingerprint
            or references.decision_session != plan.decision_session
            or references.effective_session != plan.effective_session
            or set(references.symbols) != _wanted(plan, projection)
            or references.action_evidence_sha256 != _action_identity(projection)
            or dict(references.unit_factors) != {sid: str(_factor(projection, sid)) for sid in references.symbols}):
        raise TargetProjectionRefused("protected sizing differs from canonical plan/reference authority")
    if (not plan.target_exposure.is_finite() or not Decimal(0) <= plan.target_exposure <= Decimal(1)
            or not plan.account_nav.is_finite() or plan.account_nav < 0):
        raise TargetProjectionRefused("protected sizing requires long-only account scaling")
    target = shadow_target(state)
    if target.opening_intents != plan.opening_intents:
        raise TargetProjectionRefused("protected opening intents differ from canonical dollar reservations")
    basket = dict(projection.target_basket)
    opening = {item.security_id for item in plan.opening_intents}
    for sid in opening:
        if basket.get(sid) != 0 or target.held_shares.get(sid, Decimal(0)) != 0 or sid in target.pending_close_shares:
            raise TargetProjectionRefused("protected opening entry must be a distinct unheld zero-quantity intent")
    core_budget = Fraction(plan.target_exposure) * Fraction(plan.account_nav)
    held = Fraction(0)
    missing_core = []
    for sid, qty in basket.items():
        if not qty.is_finite() or qty < 0:
            raise TargetProjectionRefused("protected target quantities must be nonnegative finite Decimal")
        if sid in opening or sid == DEFENSIVE_SECURITY_ID or qty == 0:
            continue
        if sid not in references.prices:
            missing_core.append(sid)
            continue
        held += Fraction(qty) * Fraction(references.prices[sid]) / Fraction(references.unit_factors[sid])
    if not missing_core and held > core_budget:
        raise TargetProjectionRefused("non-opening Core target exceeds its reference allocation")
    available = None if missing_core else core_budget - held
    scale = core_budget / Fraction(_shadow_equity(state))
    limits, fixed = _projection_limits(projection, references, policy,
        account_nav=plan.account_nav, target_exposure=plan.target_exposure, opening=opening)
    entries = []
    for intent in plan.opening_intents:
        if available is None:
            basket[intent.security_id] = Decimal(0)
            entries.append({**intent.to_dict(), "budget": None, "account_shares": "0",
                "status": "CORE_REFERENCE_UNAVAILABLE", "maximum_spend": "0"})
            continue
        budget = min(scale * Fraction(intent.intended_dollars), available)
        available -= budget
        limit = limits.get(intent.security_id)
        quantity = (0 if limit is None else max(Fraction(0), budget - Fraction(HEADROOM)) // Fraction(limit))
        basket[intent.security_id] = Decimal(quantity)
        entries.append({**intent.to_dict(), "budget": str(budget), "account_shares": str(quantity),
            "status": "REFERENCE_UNAVAILABLE" if limit is None else ("SIZED" if quantity else "BELOW_WHOLE_SHARE"),
            "maximum_spend": str(Fraction(quantity) * Fraction(limit) + Fraction(HEADROOM)) if quantity else "0"})
    return replace(projection, target_basket=basket, opening_sizing={"mode": PROTECTED_MODE,
        "policy": policy.to_dict(), "policy_sha256": policy.fingerprint(),
        "references": references.to_dict(), "reference_sha256": references.fingerprint(),
        "limits": {sid: decimal_text(limit) for sid, limit in sorted(limits.items())},
        "intents": [item.to_dict() for item in plan.opening_intents], "entries": entries,
        "fixed_legs": fixed, "account_nav": decimal_text(plan.account_nav),
        "target_exposure": decimal_text(plan.target_exposure),
        "allocation_status": "CORE_REFERENCE_UNAVAILABLE" if missing_core else "READY",
        "missing_core_reference_ids": sorted(missing_core),
        "core_budget": str(core_budget), "nonopening_core_reference_value": None if missing_core else str(held),
        "shadow_equity": decimal_text(_shadow_equity(state)),
        "account_scale": str(scale), "unallocated_core_budget": None if available is None else str(available)})


def _validate_allocation(projection, references, policy, plan=None):
    """Recompute stored allocation arithmetic; source/state authority is external."""
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    from sentinel.execution.plan import OpeningIntent
    evidence = projection.opening_sizing
    try:
        intents = tuple(OpeningIntent.from_dict(item) for item in evidence["intents"])
        core_budget = Fraction(evidence["core_budget"])
        account_nav = Fraction(evidence["account_nav"])
        target_exposure = Fraction(evidence["target_exposure"])
        shadow_equity = Fraction(evidence["shadow_equity"])
        scale = Fraction(evidence["account_scale"])
        if (account_nav < 0 or not 0 <= target_exposure <= 1
                or core_budget != account_nav * target_exposure
                or core_budget < 0 or shadow_equity <= 0 or scale != core_budget / shadow_equity
                or len({item.security_id for item in intents}) != len(intents)
                or len({item.slot_id for item in intents}) != len(intents)
                or [item.slot_id for item in intents] != sorted(item.slot_id for item in intents)):
            raise ValueError("allocation scalars/intents disagree")
        if plan is not None and (intents != plan.opening_intents
                or account_nav != Fraction(plan.account_nav)
                or target_exposure != Fraction(plan.target_exposure)):
            raise ValueError("allocation differs from immutable plan")
        opening = {item.security_id for item in intents}
        expected_limits, fixed = _projection_limits(projection, references, policy,
            account_nav=account_nav, target_exposure=target_exposure, opening=opening)
        if (evidence["fixed_legs"] != fixed or evidence["limits"] != {
                sid: decimal_text(limit) for sid, limit in sorted(expected_limits.items())}):
            raise ValueError("limits differ from their allocated historical reference")
        held, missing_core = Fraction(0), []
        for sid, qty in projection.target_basket.items():
            if not isinstance(qty, Decimal) or not qty.is_finite() or qty < 0:
                raise ValueError("invalid target quantity")
            if sid in opening or sid == DEFENSIVE_SECURITY_ID or qty == 0:
                continue
            if sid not in references.prices:
                missing_core.append(sid)
                continue
            held += Fraction(qty) * Fraction(references.prices[sid]) / Fraction(references.unit_factors[sid])
        if evidence["missing_core_reference_ids"] != sorted(missing_core):
            raise ValueError("missing Core references differ")
        if missing_core:
            rows = [{**intent.to_dict(), "budget": None, "account_shares": "0",
                "status": "CORE_REFERENCE_UNAVAILABLE", "maximum_spend": "0"} for intent in intents]
            if (evidence["allocation_status"] != "CORE_REFERENCE_UNAVAILABLE"
                    or evidence["nonopening_core_reference_value"] is not None
                    or evidence["unallocated_core_budget"] is not None
                    or evidence["entries"] != rows
                    or any(projection.target_basket.get(item.security_id) != 0 for item in intents)):
                raise ValueError("unavailable allocation invented a value")
            return
        if evidence["allocation_status"] != "READY":
            raise ValueError("available allocation has another status")
        if held > core_budget or Fraction(evidence["nonopening_core_reference_value"]) != held:
            raise ValueError("nonopening Core allocation differs")
        available, rows = core_budget - held, []
        for intent in intents:
            budget = min(scale * Fraction(intent.intended_dollars), available)
            available -= budget
            limit = limit_for(references, intent.security_id, policy)
            quantity = 0 if limit is None else max(Fraction(0), budget - Fraction(HEADROOM)) // Fraction(limit)
            if projection.target_basket.get(intent.security_id) != Decimal(quantity):
                raise ValueError("opening quantity differs from reserved budget")
            rows.append({**intent.to_dict(), "budget": str(budget), "account_shares": str(quantity),
                "status": "REFERENCE_UNAVAILABLE" if limit is None else ("SIZED" if quantity else "BELOW_WHOLE_SHARE"),
                "maximum_spend": str(Fraction(quantity) * Fraction(limit) + Fraction(HEADROOM)) if quantity else "0"})
        if rows != evidence["entries"] or Fraction(evidence["unallocated_core_budget"]) != available:
            raise ValueError("reserved opening allocation differs")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise TargetProjectionRefused("protected BUY allocation is inconsistent") from exc


def validate_projection(projection, *, require_current_policy=False):
    evidence = projection.opening_sizing
    if not isinstance(evidence, dict) or evidence.get("mode") != PROTECTED_MODE:
        raise TargetProjectionRefused("protected BUY projection is absent")
    policy = ProtectedLimitPolicy.from_dict(evidence.get("policy"))
    references = PriorCloseReferences.from_dict(evidence.get("references"))
    if (evidence.get("policy_sha256") != policy.fingerprint()
            or evidence.get("reference_sha256") != references.fingerprint()
            or projection.plan_fingerprint != references.plan_fingerprint
            or projection.through_session != references.effective_session
            or references.action_evidence_sha256 != _action_identity(projection)
            or dict(references.unit_factors) != {sid: str(_factor(projection, sid)) for sid in references.symbols}):
        raise TargetProjectionRefused("protected BUY projection commitment differs")
    _validate_allocation(projection, references, policy)
    if require_current_policy and ProtectedLimitPolicy.from_env() != policy:
        raise TargetProjectionRefused("protected BUY policy differs from current configuration")
    return policy, references


def revalidate_references(conn, *, plan, projection):
    """Fresh row/source comparison for the compact pre-submit authority path."""
    policy, stored = validate_projection(projection, require_current_policy=True)
    _validate_allocation(projection, stored, policy, plan)
    fresh = build_references(conn, plan=plan, projection=projection, policy=policy)
    if fresh != stored:
        raise TargetProjectionRefused("protected BUY source references changed")
    return fresh


def validate_allocation(projection, *, plan, canonical_shadow_equity):
    """Bind the denominator to the detached scalar from the canonical proof."""
    policy, references = validate_projection(projection, require_current_policy=True)
    _positive(canonical_shadow_equity, "canonical shadow equity")
    if Fraction(projection.opening_sizing["shadow_equity"]) != Fraction(canonical_shadow_equity):
        raise TargetProjectionRefused("protected allocation differs from canonical shadow equity")
    _validate_allocation(projection, references, policy, plan)


def unavailable_opening_intents(projection):
    """Unresolved zero quantities remain incomplete execution, not zero intent."""
    evidence = None if projection is None else projection.opening_sizing
    if evidence is None:
        return {}
    from sentinel.execution.opening_sizing import FINAL_MODE, UNAVAILABLE_MODE, ZERO_MODE
    if isinstance(evidence, dict) and evidence.get("mode") in {FINAL_MODE, UNAVAILABLE_MODE, ZERO_MODE}:
        return {}
    validate_projection(projection)
    if Fraction(evidence["core_budget"]) == 0:
        return {}
    return {item["security_id"]: item["status"] for item in evidence["entries"]
            if item["status"] == "CORE_REFERENCE_UNAVAILABLE"
            or item["status"] == "REFERENCE_UNAVAILABLE" and Fraction(item["budget"]) > Fraction(HEADROOM)}


def order_terms_for(projection, sid):
    from sentinel.execution.contract import OrderTerms
    validate_projection(projection, require_current_policy=True)
    if projection.opening_sizing["allocation_status"] == "CORE_REFERENCE_UNAVAILABLE":
        raise ProtectedReferenceUnavailable("Core allocation lacks an authenticated RAW reference")
    value = projection.opening_sizing["limits"].get(sid)
    if value is None:
        raise ProtectedReferenceUnavailable("protected BUY lacks an authenticated price limit")
    return OrderTerms(order_type="limit", limit_price=Decimal(value))
