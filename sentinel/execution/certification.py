"""Which broker adapters are certified, and what "certified" means here.

An adapter is not usable because it exists and imports cleanly. It is usable when
a conformance suite has demonstrated that its transport maps onto the execution
contract — and that demonstration is per adapter, because the messy realities
differ even though the contract does not.

```text
contract conformance   proved ONCE, against the simulator (broker-independent)
adapter conformance    proved PER ADAPTER: does this transport map correctly?
```

## IBKR is deliberately NOT certified

The adapter in `shared/stock_strategy_shared/broker/ibkr.py` is useful prototype
work and is not fit for this contract. Three defects, all structural rather than
incidental:

```text
close_position mints a fresh uuid4 per attempt   two identities for one intent,
                                                 which IS the duplicate-order bug
get_clock is reconstructed as Mon-Fri 09:30-16:00 with NO holiday calendar
submit auto-confirms broker "question" prompts in a bounded loop
```

The third is the one that would be tempting to keep. An unknown warning from a
broker must never be acknowledged because it happened to arrive in the shape the
code recognises as a confirmation — that is a machine agreeing to something
nobody read.

Listing IBKR here as UNCERTIFIED, with reasons, is better than omitting it: an
absent entry reads as "nobody has looked", and this has been looked at.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import threading
import weakref
from typing import Mapping


class AdapterNotCertified(RuntimeError):
    """A broker was selected that has not passed its conformance suite.

    Fail closed, at STARTUP rather than at the first order. An appliance that
    discovers this when it tries to sell is an appliance that cannot sell.
    """


@dataclass(frozen=True)
class AdapterCertification:
    name: str
    certified: bool
    reasons: tuple = ()
    notes: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "certified": self.certified,
                "reasons": list(self.reasons), "notes": self.notes}


@dataclass(frozen=True)
class CertifiedAdapterIdentity:
    """Composition-issued identity bound to one exact adapter instance."""

    name: str
    implementation: str
    source_sha256: str
    mode: str
    capabilities: tuple[str, ...]
    conformance_suite: str
    _seal: object

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "implementation": self.implementation,
            "source_sha256": self.source_sha256,
            "mode": self.mode,
            "capabilities": list(self.capabilities),
            "conformance_suite": self.conformance_suite,
        }


REGISTRY: Mapping[str, AdapterCertification] = {
    "simulator": AdapterCertification(
        name="simulator", certified=True,
        notes="the conformance ORACLE for the contract; never trades real money"),

    "alpaca": AdapterCertification(
        name="alpaca", certified=True,
        notes=(
            "paper only — sentinel/config.py refuses api.alpaca.markets with no "
            "override. Certified for deterministic client keys, single-order "
            "cancel, DAY market orders addressed by durable Alpaca asset_id, "
            "account-bound observations, and bounded Activity-SSE financial "
            "reconciliation with broker-native event identity. Open-order REST "
            "pagination is NOT certified as a proof that an unknown stale-restore "
            "order was not omitted; physical PostgreSQL incarnation/takeover "
            "fencing plus DAY-order expiry supplies that restore boundary. "
            "Recent fill history is intentionally not advertised as a complete "
            "accounting ledger because trade corrections/busts are explicit "
            "refusals. Account REST payload timing is not treated as freshness; "
            "cash authority is corroborated against the bounded Activity SSE. "
            "The adapter contains a quarantined Portfolio History 1D wire "
            "reader for real-paper acceptance testing, but historical close "
            "valuation remains explicitly UNcertified and its capability bit "
            "is false: timestamp units, left-label/session mapping, and source "
            "finality have not yet been validated. A complete account-wide "
            "fill interval with native activity identity and a fixed inclusive "
            "upper boundary is also UNcertified and its independent capability "
            "bit is false; recent-fill recovery is not negative-space proof. "
            "Fractional quantities and market-on-open remain uncertified.")),

    "ibkr": AdapterCertification(
        name="ibkr", certified=False,
        reasons=(
            "NO IMPLEMENTATION EXISTS. The prototype adapter was DELETED in the "
            "legacy eradication; it spoke the retired dict/tuple BrokerAdapter "
            "surface, not the typed execution contract",
            "it minted a fresh uuid4 per close attempt, so a timeout-and-retry "
            "produced TWO identities for one economic intent — the "
            "duplicate-position failure this contract exists to prevent",
            "it reconstructed the session as Mon-Fri 09:30-16:00 with NO "
            "holiday calendar, reporting a market open on Thanksgiving and on "
            "every early close",
            "it auto-confirmed broker 'question' prompts in a bounded loop; an "
            "unknown warning must never be acknowledged because it arrived in "
            "the shape the code recognises as a confirmation",
        ),
        notes="Recoverable from the stocker-legacy-2026-08 branch, and that is "
              "the right place for it: those three defects are properties of a "
              "design built against the old surface, so IBKR support means a "
              "NEW ExecutionBroker plus its own mapping conformance suite. "
              "Reviving the prototype would import the defects with it. The "
              "contract state machine is not re-litigated per adapter."),
}


_SEAL = object()
_ISSUED_LOCK = threading.Lock()
_ISSUED: dict[int, tuple[weakref.ReferenceType, CertifiedAdapterIdentity]] = {}

_IMPLEMENTATIONS = {
    "alpaca": frozenset({
        "sentinel.execution.alpaca.AlpacaExecutionBroker",
        "sentinel.execution.alpaca.HardenedAlpacaExecutionBroker",
        "sentinel.execution.alpaca.FinancialGradeAlpacaExecutionBroker",
        "sentinel.execution.alpaca_asset_id.AssetIdAlpacaExecutionBroker",
    }),
    "simulator": frozenset({
        "sentinel.execution.simulator.SimulatedBroker",
    }),
}

_CERTIFIED_CAPABILITIES = {
    "alpaca": frozenset({
        "order_submitter", "order_status_resolver", "open_order_observer",
        "broker_clock_provider", "recovery_aware", "evidence_producing",
        "instrument_identity", "pre_submit_instrument_revalidation",
        "account_bound_observation",
    }),
    "simulator": frozenset({
        "order_submitter", "order_status_resolver", "open_order_observer",
        "recovery_aware", "evidence_producing", "instrument_identity",
        "account_bound_observation",
    }),
}

_CONFORMANCE_SUITES = {
    "alpaca": "sentinel.alpaca-paper-conformance/1",
    "simulator": "sentinel.execution-contract-oracle/1",
}


def _implementation(value) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _source_sha256(value) -> str:
    try:
        source = inspect.getsource(type(value)).encode("utf-8")
    except (OSError, TypeError) as exc:
        raise AdapterNotCertified(
            f"adapter implementation source is unavailable: {exc}") from exc
    return hashlib.sha256(source).hexdigest()


def _store_identity(value, identity: CertifiedAdapterIdentity) -> None:
    key = id(value)

    def discard(reference) -> None:
        with _ISSUED_LOCK:
            current = _ISSUED.get(key)
            if current is not None and current[0] is reference:
                _ISSUED.pop(key, None)

    reference = weakref.ref(value, discard)
    with _ISSUED_LOCK:
        _ISSUED[key] = (reference, identity)


def certify_adapter(value, *, name: str,
                    mode: str) -> CertifiedAdapterIdentity:
    """Issue identity only for an exact implementation in the registry."""
    require_certified(name)
    implementation = _implementation(value)
    if implementation not in _IMPLEMENTATIONS.get(name, ()):
        raise AdapterNotCertified(
            f"implementation {implementation!r} cannot claim the {name!r} "
            "adapter certification")
    if name == "alpaca" and mode != "ALPACA_PAPER":
        raise AdapterNotCertified(
            "Alpaca certification is scoped to ALPACA_PAPER")
    identity = CertifiedAdapterIdentity(
        name=name,
        implementation=implementation,
        source_sha256=_source_sha256(value),
        mode=mode,
        capabilities=tuple(sorted(_CERTIFIED_CAPABILITIES[name])),
        conformance_suite=_CONFORMANCE_SUITES[name],
        _seal=_SEAL)
    _store_identity(value, identity)
    return identity


def certify_wrapper(wrapper, inner, *, wrapper_kind: str
                    ) -> CertifiedAdapterIdentity:
    """Bind a canonical wrapper to the already certified inner instance."""
    inner_identity = require_certified_adapter(inner)
    implementation = _implementation(wrapper)
    capabilities = set(inner_identity.capabilities)
    if wrapper_kind == "generation-fenced-execution":
        capabilities.add("generation_fenced")
    identity = CertifiedAdapterIdentity(
        name=inner_identity.name,
        implementation=implementation,
        source_sha256=_source_sha256(wrapper),
        mode=inner_identity.mode,
        capabilities=tuple(sorted(capabilities)),
        conformance_suite=(
            f"{inner_identity.conformance_suite}+wrapper:{wrapper_kind}"),
        _seal=_SEAL)
    _store_identity(wrapper, identity)
    return identity


def require_certified_adapter(value, *, expected: str | None = None
                              ) -> CertifiedAdapterIdentity:
    with _ISSUED_LOCK:
        retained = _ISSUED.get(id(value))
    if retained is None or retained[0]() is not value:
        raise AdapterNotCertified(
            f"adapter instance {_implementation(value)!r} has no composition-"
            "issued certification identity")
    identity = retained[1]
    if identity._seal is not _SEAL:
        raise AdapterNotCertified("adapter certification seal is invalid")
    if expected is not None and identity.name != expected:
        raise AdapterNotCertified(
            f"adapter is certified as {identity.name!r}, expected {expected!r}")
    return identity


def require_certified(name: str) -> AdapterCertification:
    """Startup gate. Raises unless this adapter has passed conformance."""
    entry = REGISTRY.get(name)
    if entry is None:
        raise AdapterNotCertified(
            f"broker adapter {name!r} is not in the certification registry. An "
            f"unlisted adapter is not an untested one, it is an unknown one, "
            f"and the safe reading of unknown is refusal.")
    if not entry.certified:
        bullets = "\n  - ".join(entry.reasons)
        raise AdapterNotCertified(
            f"broker adapter {name!r} is NOT certified:\n  - {bullets}\n"
            f"{entry.notes}")
    return entry


def certified_names() -> tuple:
    return tuple(sorted(n for n, e in REGISTRY.items() if e.certified))
