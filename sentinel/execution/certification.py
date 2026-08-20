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
