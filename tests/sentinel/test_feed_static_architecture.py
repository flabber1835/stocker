"""Regression contract for the flattened feed/PIT module architecture."""
from __future__ import annotations

import importlib
import inspect
import os
import pathlib


REPO = pathlib.Path(os.environ.get(
    "SENTINEL_REPO_ROOT", pathlib.Path(__file__).parents[2]))
FEED = REPO / "sentinel" / "feed"


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


def test_reverse_import_order_keeps_implementation_callables_stable():
    from sentinel.feed import (
        _publication_impl, maintenance_impl, sep_reconciliation_impl,
        staging_impl,
    )

    originals = (
        _publication_impl.publish,
        maintenance_impl._validate_sep_mutation_rows,
        sep_reconciliation_impl._source_fingerprint,
        sep_reconciliation_impl.reconcile_year,
        staging_impl.staged,
    )
    modules = (
        "sentinel.feed.staging", "sentinel.feed.sep_reconciliation",
        "sentinel.feed.maintenance", "sentinel.feed.publication",
    )
    for module_name in modules:
        importlib.reload(importlib.import_module(module_name))
    assert originals == (
        _publication_impl.publish,
        maintenance_impl._validate_sep_mutation_rows,
        sep_reconciliation_impl._source_fingerprint,
        sep_reconciliation_impl.reconcile_year,
        staging_impl.staged,
    )


def test_public_monkeypatch_does_not_propagate_to_hidden_implementation(monkeypatch):
    from sentinel.feed import maintenance, maintenance_impl, staging, staging_impl

    hidden_staged = staging_impl.staged
    hidden_validator = maintenance_impl._validate_sep_mutation_rows
    monkeypatch.setattr(staging, "staged", object())
    monkeypatch.setattr(maintenance, "validate_sep_mutation_rows", object())
    assert staging_impl.staged is hidden_staged
    assert maintenance_impl._validate_sep_mutation_rows is hidden_validator


def test_seed_has_one_public_generation_path():
    from sentinel.feed import ingest

    source = inspect.getsource(ingest.seed)
    assert "_authority.seed(" not in source
    assert "_run_seed_generation(" in source
    assert ingest._ordinary_seed_generation.__module__ == "sentinel.feed.ingest"


def test_seed_coherence_keeps_success_reopen_private():
    from sentinel.feed import seed_coherence

    assert not hasattr(seed_coherence, "reopen_successful_run")
    assert "reopen_successful_run" not in seed_coherence.__all__


def test_canonical_entrypoints_are_owned_by_public_modules():
    from sentinel.feed import ingest, maintenance, publication, sep_reconciliation, staging

    assert ingest.seed.__module__ == "sentinel.feed.ingest"
    assert ingest.daily.__module__ == "sentinel.feed.ingest"
    assert maintenance._reconcile_sep_mutations_core.__module__ == "sentinel.feed.maintenance"
    assert publication.publish.__module__ == "sentinel.feed.publication"
    assert sep_reconciliation.reconcile_year.__module__ == "sentinel.feed.sep_reconciliation"
    assert staging.staged.__module__ == "sentinel.feed.staging"
