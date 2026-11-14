"""Exact execution-only reconciliation change; no action-input or financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

BASE_REVISION = "aed1a26c335281169c6d8067b1ce2e7de1632053"
MODULE = "sentinel.execution.reconcile"
BEFORE = "0a49d779f60888ff1d0e79d532f857e528789b7c17feeb8ac7816cba231693d9"
PROFILE_SHA256 = '10729fac8e3c42b2665d599822d8265ad6305dfc4027b36c79811be486671556'
PROFILE = Path(__file__).with_name("fractional-execution-source-transition.json")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("FRACTIONAL_SOURCE_DUPLICATE_KEY")
        result[key] = value
    return result


def _profile():
    raw = PROFILE.read_bytes()
    if PROFILE_SHA256 == "0" * 64 or _sha(raw) != PROFILE_SHA256:
        raise ValueError("FRACTIONAL_SOURCE_WITNESS_CHANGED")
    value = json.loads(raw, object_pairs_hook=_pairs)
    own, count = re.subn(rb"^PROFILE_SHA256 = '[a-f0-9]{64}'$",
        b"PROFILE_SHA256 = '" + b"0" * 64 + b"'", Path(__file__).read_bytes(), flags=re.M)
    if (count != 1 or set(value) != {"schema", "authority_effect", "base_revision",
                                   "module", "before", "after", "module_sha256", "decision"}
            or value["schema"] != "sentinel.fractional-execution-source-transition/1"
            or value["authority_effect"] != "NONE" or value["base_revision"] != BASE_REVISION
            or value["module"] != MODULE or value["before"] != BEFORE
            or not re.fullmatch("[a-f0-9]{64}", value["after"])
            or set(value["decision"]) != {"before", "after"}
            or any(not re.fullmatch("[a-f0-9]{64}", item) for item in value["decision"].values())
            or value["module_sha256"] != _sha(own)):
        raise ValueError("FRACTIONAL_SOURCE_WITNESS_INVALID")
    return value


def contribution(module, raw):
    actual = _sha(raw)
    if module != MODULE:
        return actual
    value = _profile()
    return value["before"] if actual == value["after"] else actual


def decision_predecessor(raw):
    """Undo only the sealed account-plan lot choice for historical comparison."""
    pair = _profile()["decision"]
    if _sha(raw) != pair["after"]:
        return raw
    changes = (
        (b'    from sentinel.execution.market_buy_policy import MarketBuyPolicy\n'
         b'    market_policy = MarketBuyPolicy.from_env()\n'
         b'    lot = Decimal("0.000000001") if market_policy is not None and market_policy.fractional else Decimal(1)\n', b''),
        (b'defensive_weight=defensive_weight, weight_denominator=shadow_equity, lot=lot)',
         b'defensive_weight=defensive_weight, weight_denominator=shadow_equity)'),
        (b'defensive_security=defensive_security, lot=lot)', b'defensive_security=defensive_security)'),
        (b'canonical_target=target, marks=current_marks, lot=lot)', b'canonical_target=target, marks=current_marks)'),
    )
    for current, previous in changes:
        if raw.count(current) != 1:
            raise ValueError("FRACTIONAL_DECISION_SOURCE_SHAPE_CHANGED")
        raw = raw.replace(current, previous)
    if _sha(raw) != pair["before"]:
        raise ValueError("FRACTIONAL_DECISION_PREDECESSOR_CHANGED")
    return raw


def decision_comparison_scope(scope, raw):
    """Private comparison only; the caller's actual source scope is untouched."""
    from dataclasses import replace
    from types import MappingProxyType
    if _sha(raw) != scope.current_files.get("core/decision.py"):
        return scope, raw
    previous = decision_predecessor(raw)
    if previous == raw:
        return scope, raw
    return replace(scope, current_files=MappingProxyType({
        **scope.current_files, "core/decision.py": _sha(previous)})), previous
