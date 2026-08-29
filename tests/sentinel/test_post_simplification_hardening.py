"""Regression checks for canonical ownership after the simplification merges."""
from __future__ import annotations

import pathlib

from sentinel.execution import authority_gate
from sentinel.execution.guarded import (
    BrokerOperation,
    ManualExecutionGrant,
    PaperPreparationGrant,
)
from sentinel.feed import publication


REPO = pathlib.Path(__file__).parents[2]


def test_every_non_mutating_broker_operation_has_authority_classification():
    expected_reads = set(BrokerOperation) - {
        BrokerOperation.SUBMIT,
        BrokerOperation.CANCEL,
    }
    assert authority_gate._READ_OPERATIONS == expected_reads


def test_market_clock_is_authorized_for_prepare_and_execute_reads():
    prepare = PaperPreparationGrant(
        expected_account="paper-account",
        decision_session=__import__("datetime").date(2026, 8, 29),
    )
    execute = ManualExecutionGrant(
        confirm_paper_account="paper-account",
        confirm_plan_id="plan",
        confirm_effective_session=__import__("datetime").date(2026, 8, 29),
        confirm_submit_paper_orders=True,
    )
    assert authority_gate._authority_operation(
        prepare, BrokerOperation.MARKET_CLOCK) == "PREPARE_READ"
    assert authority_gate._authority_operation(
        execute, BrokerOperation.MARKET_CLOCK) == "EXECUTE_READ"


def test_publication_cannot_be_redirected_through_hidden_implementation(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(publication, "_publish_atomic", lambda *a, **k: sentinel)
    monkeypatch.setattr(
        publication._core, "publish",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("hidden implementation must not own public publication")),
    )
    assert publication.publish(object()) is sentinel


def test_duplicate_ingest_orchestration_module_is_removed():
    assert not (REPO / "sentinel" / "feed" / "ingest_authority_impl.py").exists()


def test_maintenance_impl_exposes_no_public_sep_reconciliation_entrypoint():
    from sentinel.feed import maintenance_impl

    assert not hasattr(maintenance_impl, "reconcile_sep_mutations")
