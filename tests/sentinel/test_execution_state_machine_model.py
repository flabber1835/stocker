"""Independent model-based certification of Sentinel execution state.

The oracle below names public states and actions.  It deliberately does not
import the production transition or permission tables: equality with a second
reference to the same object would certify only that Python returned it twice.
"""
from __future__ import annotations

import random
import sys
from collections import deque
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres, drop_public_tables  # noqa: E402

from sentinel import binding, schema  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.commands import Command  # noqa: E402
from sentinel.execution.contract import BrokerInstrument, Side  # noqa: E402
from sentinel.execution.identity import (  # noqa: E402
    CommandIdentity,
    DeploymentIdentity,
)
from sentinel.execution.states import (  # noqa: E402
    Action,
    ActionNotPermitted,
    CommandState,
    IllegalTransition,
    RuntimeState,
    assert_transition,
    blocks_overlapping,
    can_transition,
    is_terminal,
    permits,
    require,
)
from sentinel.feed import store as feed_store  # noqa: E402


D = Decimal
QUANTITY = D("100")
DEPLOYMENT = DeploymentIdentity("model-nas", "sim", "MODEL-ACCOUNT", 1)

# Independent transcription of docs/sentinel-execution-contract.md section 3.
# Strings keep this oracle structurally separate from the production table.
MODEL_TRANSITIONS = {
    "PLANNED": {"SEND_PENDING", "SUPERSEDED"},
    "SEND_PENDING": {"ACKNOWLEDGED", "REJECTED", "UNKNOWN"},
    "ACKNOWLEDGED": {
        "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED",
        "REJECTED", "UNKNOWN",
    },
    "UNKNOWN": {
        "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED",
        "REJECTED",
    },
    "PARTIALLY_FILLED": {
        "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED",
        "UNKNOWN",
    },
    "CANCEL_PENDING": {
        "CANCELLED", "FILLED", "PARTIALLY_FILLED", "UNKNOWN",
    },
    "FILLED": set(),
    "CANCELLED": set(),
    "REJECTED": set(),
    "SUPERSEDED": set(),
}

MODEL_PERMISSIONS = {
    "RUNNING": {
        "RECONCILE", "REDUCE_EXPOSURE", "INCREASE_EXPOSURE",
        "ADVANCE_STRATEGY",
    },
    "RECONCILING": {"RECONCILE", "ADVANCE_STRATEGY"},
    "DATA_DEGRADED": {
        "RECONCILE", "REDUCE_EXPOSURE", "ADVANCE_STRATEGY",
    },
    "BROKER_DEGRADED": {"ADVANCE_STRATEGY"},
    "FOREIGN_ACTIVITY": {
        "RECONCILE", "REDUCE_EXPOSURE", "ADVANCE_STRATEGY",
    },
    "INTEGRITY_HALTED": set(),
    "OPERATOR_PAUSED": {"RECONCILE", "ADVANCE_STRATEGY"},
}

MODEL_TERMINAL = {"FILLED", "CANCELLED", "REJECTED", "SUPERSEDED"}
MODEL_IN_FLIGHT = {
    "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN", "PARTIALLY_FILLED",
    "CANCEL_PENDING",
}


def _new_command(lifecycle: int, *, security_id: str = "SEC-MODEL") -> Command:
    instrument = BrokerInstrument(
        security_id=security_id,
        symbol=security_id.removeprefix("SEC-"),
        broker_id=f"model-{security_id}",
    )
    identity = CommandIdentity(
        deployment=DEPLOYMENT,
        plan_id=f"model-plan-{lifecycle}",
        security_id=security_id,
        revision=lifecycle,
    )
    return Command(
        identity=identity,
        instrument=instrument,
        side=Side.BUY,
        quantity=QUANTITY,
    )


def _changes(command: Command, nxt: CommandState) -> dict[str, object]:
    if nxt is CommandState.PARTIALLY_FILLED:
        filled = min(command.quantity - D(1), command.filled_quantity + D(1))
        return {
            "filled_quantity": filled,
            "filled_average_price": D("100"),
        }
    if nxt is CommandState.FILLED:
        return {
            "filled_quantity": command.quantity,
            "filled_average_price": D("100"),
        }
    return {}


def _assert_model_invariants(command: Command) -> None:
    state = command.state.value
    assert (state in MODEL_TERMINAL) is is_terminal(command.state)
    assert (state in MODEL_IN_FLIGHT) is blocks_overlapping(command.state)
    assert D(0) <= command.filled_quantity <= command.quantity
    if command.state is CommandState.FILLED:
        assert command.filled_quantity == command.quantity
    if state in MODEL_TERMINAL:
        for candidate in CommandState:
            assert not can_transition(command.state, candidate)
            with pytest.raises(IllegalTransition):
                command.transition(candidate)


def test_command_transition_guard_matches_every_independent_model_edge():
    assert {state.value for state in CommandState} == set(MODEL_TRANSITIONS)
    for current in CommandState:
        for nxt in CommandState:
            expected = nxt.value in MODEL_TRANSITIONS[current.value]
            assert can_transition(current, nxt) is expected
            if expected:
                assert assert_transition(current, nxt) is nxt
            else:
                with pytest.raises(IllegalTransition):
                    assert_transition(current, nxt)


def test_runtime_permission_guard_matches_every_independent_model_cell():
    assert {state.value for state in RuntimeState} == set(MODEL_PERMISSIONS)
    for state in RuntimeState:
        for action in Action:
            expected = action.value in MODEL_PERMISSIONS[state.value]
            assert permits(state, action) is expected
            if expected:
                assert require(state, action) is None
            else:
                with pytest.raises(ActionNotPermitted):
                    require(state, action)


@pytest.mark.parametrize("seed", range(16), ids=lambda seed: f"model-seed-{seed}")
def test_generated_valid_and_invalid_command_paths_preserve_the_model(seed):
    rng = random.Random(seed)
    lifecycle = 0
    command = _new_command(lifecycle)
    seen_keys = {command.client_key}
    model_state = "PLANNED"
    model_filled = D(0)

    for step in range(256):
        if model_state in MODEL_TERMINAL and step % 2 == 0:
            prior_key = command.client_key
            lifecycle += 1
            command = _new_command(lifecycle)
            assert command.client_key != prior_key
            assert command.client_key not in seen_keys
            seen_keys.add(command.client_key)
            model_state = "PLANNED"
            model_filled = D(0)

        candidate = rng.choice(tuple(CommandState))
        legal = candidate.value in MODEL_TRANSITIONS[model_state]
        before = command
        if not legal:
            with pytest.raises(IllegalTransition):
                command.transition(candidate)
            assert command == before
        else:
            command = command.transition(candidate, **_changes(command, candidate))
            model_state = candidate.value
            if candidate is CommandState.PARTIALLY_FILLED:
                model_filled = min(QUANTITY - D(1), model_filled + D(1))
            elif candidate is CommandState.FILLED:
                model_filled = QUANTITY

        assert command.state.value == model_state
        assert command.filled_quantity == model_filled
        _assert_model_invariants(command)


def _shortest_path(target: str) -> tuple[str, ...]:
    queue = deque([("PLANNED",)])
    visited = {"PLANNED"}
    while queue:
        path = queue.popleft()
        current = path[-1]
        if current == target:
            return path
        for nxt in sorted(MODEL_TRANSITIONS[current]):
            if nxt not in visited:
                visited.add(nxt)
                queue.append(path + (nxt,))
    raise AssertionError(f"model state {target} is unreachable from PLANNED")


def _edge_cover_traces() -> tuple[tuple[str, ...], ...]:
    traces = []
    for source, targets in sorted(MODEL_TRANSITIONS.items()):
        for target in sorted(targets):
            traces.append(_shortest_path(source) + (target,))
    return tuple(traces)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


def test_every_legal_edge_survives_persistence_and_connection_restart(pg):
    conn = feed_store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    feed_store.require_feed_schema(conn)
    binding.bind(
        conn,
        deployment_id=DEPLOYMENT.deployment_id,
        broker=DEPLOYMENT.broker,
        broker_account_id=DEPLOYMENT.broker_account_id,
    )
    try:
        for trace_index, trace in enumerate(_edge_cover_traces()):
            security_id = f"SEC-MODEL-{trace_index}"
            command = _new_command(trace_index, security_id=security_id)
            journal.save_command(conn, command)

            expected_states = ["PLANNED"]
            expected_filled = D(0)
            for target_name in trace[1:]:
                previous = command.state
                target = CommandState(target_name)
                command = command.transition(target, **_changes(command, target))
                journal.save_command(conn, command, previous=previous)

                conn.close()
                conn = feed_store.connect(pg.sync_dsn)
                loaded = journal.load_commands(
                    conn, DEPLOYMENT, plan_id=command.identity.plan_id)
                assert len(loaded) == 1
                command = loaded[0]

                expected_states.append(target_name)
                if target is CommandState.PARTIALLY_FILLED:
                    expected_filled = min(QUANTITY - D(1), expected_filled + D(1))
                elif target is CommandState.FILLED:
                    expected_filled = QUANTITY
                assert command.state.value == target_name
                assert command.filled_quantity == expected_filled
                _assert_model_invariants(command)

                in_flight = {
                    item.client_key
                    for item in journal.in_flight_commands(conn, DEPLOYMENT)
                }
                assert (command.client_key in in_flight) is (
                    target_name in MODEL_IN_FLIGHT)

            history = journal.command_history(conn, command.client_key)
            assert [event["to"] for event in history] == expected_states
            assert [event["from"] for event in history] == [None] + expected_states[:-1]
    finally:
        conn.close()
