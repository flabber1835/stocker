"""Regression contract for the flattened feed/PIT module architecture."""
from __future__ import annotations

import importlib
import pathlib


FEED = pathlib.Path(__file__).parents[2] / "sentinel" / "feed"


def test_public_feed_modules_install_no_custom_module_classes():
    for name in (
        "ingest.py", "maintenance.py", "publication.py", "staging.py",
        "sep_reconciliation.py", "seed_coherence.py",
    ):
        text = (FEED / name).read_text(encoding="utf-8")
        assert "sys.modules[__name__].__class__" not in text, name
        assert "types.ModuleType" not in text, name


def test_ingest_import_does_not_replace_run_or_identity_lifecycle():
    from sentinel.feed import identity_rebuild, store
    import sentinel.feed.ingest as ingest

    original = (
        store.IngestRun.__init__, store.IngestRun.finish,
        identity_rebuild.record_plan, identity_rebuild.publish_completed_run,
    )
    importlib.reload(ingest)
    assert original == (
        store.IngestRun.__init__, store.IngestRun.finish,
        identity_rebuild.record_plan, identity_rebuild.publish_completed_run,
    )


def test_public_facade_imports_do_not_replace_implementation_callables():
    from sentinel.feed import (
        _publication_impl, maintenance_impl, sep_reconciliation_impl,
        staging_impl,
    )

    originals = {
        "publication": _publication_impl.publish,
        "maintenance_validator": maintenance_impl._validate_sep_mutation_rows,
        "sep_fingerprint": sep_reconciliation_impl._source_fingerprint,
        "sep_year": sep_reconciliation_impl.reconcile_year,
        "staged": staging_impl.staged,
    }
    for module_name in (
        "sentinel.feed.publication", "sentinel.feed.maintenance",
        "sentinel.feed.sep_reconciliation", "sentinel.feed.staging",
    ):
        importlib.reload(importlib.import_module(module_name))

    assert _publication_impl.publish is originals["publication"]
    assert maintenance_impl._validate_sep_mutation_rows is originals["maintenance_validator"]
    assert sep_reconciliation_impl._source_fingerprint is originals["sep_fingerprint"]
    assert sep_reconciliation_impl.reconcile_year is originals["sep_year"]
    assert staging_impl.staged is originals["staged"]


def test_public_monkeypatch_does_not_propagate_to_hidden_implementation(monkeypatch):
    from sentinel.feed import maintenance, maintenance_impl, staging, staging_impl

    hidden_staged = staging_impl.staged
    hidden_validator = maintenance_impl._validate_sep_mutation_rows
    monkeypatch.setattr(staging, "staged", object())
    monkeypatch.setattr(maintenance, "validate_sep_mutation_rows", object())
    assert staging_impl.staged is hidden_staged
    assert maintenance_impl._validate_sep_mutation_rows is hidden_validator


def test_canonical_entrypoints_are_owned_by_public_modules():
    from sentinel.feed import ingest, maintenance, publication, sep_reconciliation, staging

    assert ingest.seed.__module__ == "sentinel.feed.ingest"
    assert ingest.daily.__module__ == "sentinel.feed.ingest"
    assert maintenance._reconcile_sep_mutations_core.__module__ == "sentinel.feed.maintenance"
    assert publication.publish.__module__ == "sentinel.feed.publication"
    assert sep_reconciliation.reconcile_year.__module__ == "sentinel.feed.sep_reconciliation"
    assert staging.staged.__module__ == "sentinel.feed.staging"
