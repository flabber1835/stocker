"""Historical corrections cannot relabel an already processed economic path."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel.core.history import (
    SCHEMA, HistoryReconstructionRequired, require_history_compatible,
)
from sentinel.feed import maintenance_impl
from sentinel.feed.history_mutations import publication_proof
from test_production_state import _fresh, _published, _advance


def proof(version=8, changes=None, baseline=7):
    return {"schema": SCHEMA, "baseline_version": baseline,
            "publication_version": version,
            "changes": changes if changes is not None else [[8, "2026-08-10"]]}


def test_corrected_history_refuses_next_day_before_state_mutation():
    config, fresh = _fresh()
    prior = _advance(fresh, _published(), config)
    original = deepcopy(prior.to_dict())
    # Each source class feeds the same immutable publication boundary; source
    # classification itself is exercised by the SQL and ACTIONS tests below.
    published = replace(_published("2026-08-11", version=8), history_proof=proof())
    with pytest.raises(HistoryReconstructionRequired, match="RECONSTRUCTION_REQUIRED"):
        _advance(prior, published, config)
    assert prior.to_dict() == original
    assert prior.data_version == 7


def test_forward_only_extension_advances_and_restart_is_identical():
    config, fresh = _fresh()
    prior = _advance(fresh, _published(), config)
    published = replace(_published("2026-08-11", version=8),
                        history_proof=proof(changes=[[8, "2026-08-11"]]))
    result = _advance(prior, published, config)
    assert result.data_version == 8
    assert result.last_processed_session == "2026-08-11"
    from sentinel.core.session import SessionState
    assert _advance(SessionState.from_dict(prior.to_dict()), published, config).to_dict() == result.to_dict()


@pytest.mark.parametrize("value", [None, {}, proof(baseline=8),
    proof(version=9), proof(changes=[[8, "invalid"]]),
    proof(changes=[[8, "2026-08-10"], [8, "2026-08-11"]])])
def test_missing_or_malformed_history_proof_refuses(value):
    with pytest.raises(HistoryReconstructionRequired):
        require_history_compatible(prior_version=7, last_processed_session="2026-08-10",
                                   version=8, proof=value)


def test_later_publication_retains_earlier_reconstruction_obligation():
    require_history_compatible(prior_version=8, last_processed_session="2026-08-10",
                               version=10, proof=proof(version=10))
    with pytest.raises(HistoryReconstructionRequired):
        require_history_compatible(prior_version=7, last_processed_session="2026-08-10",
                                   version=10, proof=proof(version=10))


@pytest.mark.parametrize("action", sorted(maintenance_impl.TERMINAL_ACTIONS))
@pytest.mark.parametrize("mutation", ["added", "removed", "changed"])
def test_every_target_terminal_source_mutation_has_a_replay_boundary(monkeypatch, action, mutation):
    from sentinel.feed.action_source import distinct_rows
    row = {"ticker": "AAA", "date": "2026-08-10", "action": action, "value": 1}
    before = [] if mutation == "added" else [row]
    after = [] if mutation == "removed" else [{**row, "value": 2} if mutation == "changed" else row]
    prior = {identity: value for identity, _payload, value in distinct_rows(before)}
    monkeypatch.setattr(maintenance_impl, "_active_action_rows", lambda _: prior)
    assert maintenance_impl._action_change_dates(object(), after) == ["2026-08-10"]


class MutationConnection:
    def __init__(self, changed=None, action=None):
        self.changed, self.action, self.value = changed, action, None
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, params=()):
        self.value = self.changed if "sentinel_history_mutations" in sql else self.action
    def fetchone(self): return (self.value,)


def test_publication_carries_failed_attempt_history_and_cannot_accept_caller_authority():
    previous = SimpleNamespace(version=8, evidence={"strategy_history": proof()})
    result = publication_proof(MutationConnection("2026-08-09"), previous=previous,
                               version=10, run_id="retry", evidence={})
    assert result["changes"] == [[8, "2026-08-10"], [10, "2026-08-09"]]
    with pytest.raises(ValueError, match="caller may not supply"):
        publication_proof(MutationConnection(), previous=previous, version=10,
                          run_id="retry", evidence={"strategy_history": {}})


def test_terminal_only_publication_records_affected_history():
    previous = SimpleNamespace(version=7, evidence={})
    result = publication_proof(MutationConnection(action="2026-08-07"), previous=previous,
                               version=8, run_id="terminal", evidence={})
    assert result["changes"] == [[8, "2026-08-07"]]
