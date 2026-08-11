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
        notes="paper only — sentinel/config.py refuses api.alpaca.markets with "
              "no override. Certified for: derived client keys, single-order "
              "cancel, paginated-or-truncated observation, exact-quantity "
              "exits. NOT certified for fractional quantities or "
              "market-on-open, and the capability flags say so."),

    "ibkr": AdapterCertification(
        name="ibkr", certified=False,
        reasons=(
            "close_position() mints a fresh uuid4 per attempt, so a "
            "timeout-and-retry produces TWO identities for one economic "
            "intent — the duplicate-position failure the contract exists to "
            "prevent",
            "get_clock() reconstructs the session as Mon-Fri 09:30-16:00 with "
            "NO holiday calendar, so it reports a market open on Thanksgiving "
            "and on every early close",
            "submit() auto-confirms broker 'question' prompts in a bounded "
            "loop; an unknown warning must never be acknowledged because it "
            "arrived in the shape the code recognises as a confirmation",
            "no ExecutionBroker implementation exists — the prototype speaks "
            "the retired dict/tuple BrokerAdapter surface",
        ),
        notes="Prototype only. Activation requires its own ExecutionBroker "
              "implementation plus a mapping conformance suite; the contract "
              "state machine is NOT re-litigated per adapter."),
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
