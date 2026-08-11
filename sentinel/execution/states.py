"""Two state machines: what a COMMAND is doing, and what the RUNTIME may do.

Both are pure. Neither imports a broker, a database or a clock — the whole point
is that every hostile path (timeout, partial fill, cancel race, supersession,
crash) can be driven in a unit test without a network.

## Why UNKNOWN has to exist

Stocker recorded an uncertain POST as FAILED. A timeout is not a rejection: the
order may be resting at the broker right now. Calling that FAILED licences a
retry, and the retry opens a second position.

```text
REJECTED    the broker SAID SO. There is no inferred rejection
UNKNOWN     we do not know, and we will find out by ASKING, not by assuming
```

## Why the runtime kernel is in-process

Stocker asked another container over HTTP whether it could submit. That bought
nothing — the answer is a pure function of state Sentinel already holds — and it
added a network hop to the most safety-critical decision in the system. The
permission table below runs immediately before durable command creation.
"""
from __future__ import annotations

from enum import Enum
from typing import Mapping


class IllegalTransition(RuntimeError):
    """A command was asked to move somewhere it may not go.

    Raised, never logged-and-continued. Each forbidden edge in the table below
    corresponds to a way real money goes missing, so a caller reaching one has a
    logic error that must surface now rather than as a broker surprise later.
    """


class CommandState(str, Enum):
    PLANNED = "PLANNED"
    SEND_PENDING = "SEND_PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNKNOWN = "UNKNOWN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


S = CommandState

#: Terminal. Economically settled; nothing further happens to this command.
TERMINAL = frozenset({S.FILLED, S.CANCELLED, S.REJECTED, S.SUPERSEDED})

#: States in which the broker may still act on this command, so it may still
#: change a position. This is the set that BLOCKS an overlapping command for the
#: same security — including UNKNOWN, which is the whole reason the set is not
#: simply "not terminal".
IN_FLIGHT = frozenset({S.SEND_PENDING, S.ACKNOWLEDGED, S.UNKNOWN,
                       S.PARTIALLY_FILLED, S.CANCEL_PENDING})

_TRANSITIONS: Mapping[CommandState, frozenset] = {
    # A planned command is durable but has touched nothing, so it is the ONLY
    # state a supersession may consume. A working order has to be cancelled and
    # CONFIRMED cancelled; declaring it superseded would leave a live order
    # nobody is tracking.
    S.PLANNED: frozenset({S.SEND_PENDING, S.SUPERSEDED}),

    # Written BEFORE the network call, so a crash here is recoverable: restart
    # recomputes the key and asks. Every unclear outcome lands in UNKNOWN.
    S.SEND_PENDING: frozenset({S.ACKNOWLEDGED, S.REJECTED, S.UNKNOWN}),

    S.ACKNOWLEDGED: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCEL_PENDING,
                               S.CANCELLED, S.REJECTED, S.UNKNOWN}),

    # UNKNOWN resolves ONLY by observation, and it can resolve to anything the
    # broker turns out to be holding — including CANCELLED, which here means
    # "a COMPLETE observation shows no such order and no fill attributable to
    # it", i.e. the command never landed. It may NOT go to SUPERSEDED: replacing
    # intent whose outcome is undetermined is how you end up holding two.
    S.UNKNOWN: frozenset({S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.FILLED,
                          S.CANCELLED, S.REJECTED}),

    # Self-edge is legitimate and load-bearing: each new partial is a distinct
    # economic event that moves the remaining delta.
    S.PARTIALLY_FILLED: frozenset({S.PARTIALLY_FILLED, S.FILLED,
                                   S.CANCEL_PENDING, S.CANCELLED, S.UNKNOWN}),

    # A cancel request races the fill it is trying to prevent, and the fill can
    # win. Both outcomes are legal from here.
    S.CANCEL_PENDING: frozenset({S.CANCELLED, S.FILLED, S.PARTIALLY_FILLED,
                                 S.UNKNOWN}),

    S.FILLED: frozenset(),
    S.CANCELLED: frozenset(),
    S.REJECTED: frozenset(),
    S.SUPERSEDED: frozenset(),
}


def can_transition(current: CommandState, nxt: CommandState) -> bool:
    return nxt in _TRANSITIONS[current]


def assert_transition(current: CommandState, nxt: CommandState) -> CommandState:
    if not can_transition(current, nxt):
        raise IllegalTransition(
            f"{current.value} -> {nxt.value} is not a legal command transition. "
            + _why_not(current, nxt))
    return nxt


def _why_not(current: CommandState, nxt: CommandState) -> str:
    """Name the hazard, not just the rule. A caller hitting this is about to do
    something that loses money, and the message is where they find out why."""
    if current is S.UNKNOWN and nxt is S.SUPERSEDED:
        return ("A command whose outcome is UNDETERMINED cannot be superseded — "
                "it may be resting at the broker right now, and replacing it "
                "would put two live orders on one intent. Resolve it against a "
                "COMPLETE observation first.")
    if current in TERMINAL:
        return (f"{current.value} is terminal. If new intent exists, it needs a "
                f"new command with a NEW identity (CommandIdentity.superseding), "
                f"not a resurrection of this one.")
    if nxt is S.SUPERSEDED:
        return ("Only a PLANNED command may be superseded. Anything already sent "
                "must be cancelled and CONFIRMED cancelled by observation; "
                "declaring it superseded abandons a live order.")
    if nxt is S.REJECTED:
        return ("REJECTED means the broker said so. An unclear outcome is "
                "UNKNOWN — inferring a rejection from a timeout is what licences "
                "the retry that opens a second position.")
    return "See docs/sentinel-execution-contract.md §3."


def is_terminal(state: CommandState) -> bool:
    return state in TERMINAL


def blocks_overlapping(state: CommandState) -> bool:
    """May a NEW command be created for the same security while this one is in
    `state`? Answered in the negative sense the caller actually needs."""
    return state in IN_FLIGHT


# ---------------------------------------------------------------------------
# The runtime permission kernel
# ---------------------------------------------------------------------------

class RuntimeState(str, Enum):
    RUNNING = "RUNNING"
    RECONCILING = "RECONCILING"
    DATA_DEGRADED = "DATA_DEGRADED"
    BROKER_DEGRADED = "BROKER_DEGRADED"
    FOREIGN_ACTIVITY = "FOREIGN_ACTIVITY"
    INTEGRITY_HALTED = "INTEGRITY_HALTED"
    OPERATOR_PAUSED = "OPERATOR_PAUSED"


class Action(str, Enum):
    RECONCILE = "RECONCILE"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    INCREASE_EXPOSURE = "INCREASE_EXPOSURE"
    ADVANCE_STRATEGY = "ADVANCE_STRATEGY"


R, A = RuntimeState, Action

#: The asymmetry between the two exposure directions is the substance of this
#: table, and it is deliberate everywhere it appears: selling late is dangerous,
#: buying late is opportunity cost. Every degraded state that permits anything
#: permits REDUCE and withholds INCREASE.
_PERMISSIONS: Mapping[RuntimeState, frozenset] = {
    R.RUNNING: frozenset({A.RECONCILE, A.REDUCE_EXPOSURE, A.INCREASE_EXPOSURE,
                          A.ADVANCE_STRATEGY}),

    # Mid-reconcile the book is not yet known, so NOTHING is submitted. The
    # shadow still advances: being unable to act is not a reason to stop
    # knowing, and a controller that skipped sessions would lose its event
    # memory.
    R.RECONCILING: frozenset({A.RECONCILE, A.ADVANCE_STRATEGY}),

    R.DATA_DEGRADED: frozenset({A.RECONCILE, A.REDUCE_EXPOSURE,
                                A.ADVANCE_STRATEGY}),

    # No broker, no commands — and no reconciliation either, because
    # reconciliation IS a broker read. Only the deterministic side continues.
    R.BROKER_DEGRADED: frozenset({A.ADVANCE_STRATEGY}),

    # Someone may have de-risked by hand. Do not fight them by buying back to
    # target; do not block them from getting further out.
    R.FOREIGN_ACTIVITY: frozenset({A.RECONCILE, A.REDUCE_EXPOSURE,
                                   A.ADVANCE_STRATEGY}),

    # The state hash, schema or binding is wrong. Advancing the strategy would
    # write more state on top of state we cannot vouch for.
    R.INTEGRITY_HALTED: frozenset(),

    R.OPERATOR_PAUSED: frozenset({A.RECONCILE, A.ADVANCE_STRATEGY}),
}


class ActionNotPermitted(RuntimeError):
    """The runtime state forbids this action."""


def permits(state: RuntimeState, action: Action) -> bool:
    return action in _PERMISSIONS[state]


def require(state: RuntimeState, action: Action) -> None:
    if not permits(state, action):
        raise ActionNotPermitted(
            f"{action.value} is not permitted in {state.value}. "
            f"Permitted here: "
            f"{sorted(a.value for a in _PERMISSIONS[state]) or 'nothing'}.")


def exposure_action(delta_is_increase: bool) -> Action:
    """Map a signed exposure change onto the permission it needs.

    A helper rather than an inline conditional at each call site, because
    getting it backwards silently inverts the safety asymmetry — a bug that
    would let a degraded appliance buy and refuse to sell.
    """
    return Action.INCREASE_EXPOSURE if delta_is_increase else Action.REDUCE_EXPOSURE
