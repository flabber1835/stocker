"""Regression contract for the flattened feed/PIT module architecture."""
from __future__ import annotations

import ast
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
        "readiness.py", "sep_reconciliation.py", "seed_coherence.py",
    ):
        text = (FEED / name).read_text(encoding="utf-8")
        assert "sys.modules[__name__].__class__" not in text, name
        assert "types.ModuleType" not in text, name


def test_public_feed_facades_use_only_explicit_imports():
    for name in (
        "maintenance.py", "publication.py", "readiness.py",
        "sep_reconciliation.py", "staging.py",
    ):
        tree = ast.parse((FEED / name).read_text(encoding="utf-8"))
        wildcards = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == "*" for alias in node.names)
        ]
        assert wildcards == [], name


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
        _publication_impl, maintenance_impl, readiness_impl,
        sep_reconciliation_impl, staging_impl,
    )

    originals = {
        "publication": _publication_impl.current,
        "maintenance_validator": maintenance_impl._validate_sep_mutation_rows,
        "readiness": readiness_impl.check_readiness,
        "sep_fingerprint": sep_reconciliation_impl._source_fingerprint,
        "staged": staging_impl.staged,
    }
    for module_name in (
        "sentinel.feed.publication", "sentinel.feed.maintenance",
        "sentinel.feed.readiness", "sentinel.feed.sep_reconciliation",
        "sentinel.feed.staging",
    ):
        importlib.reload(importlib.import_module(module_name))

    assert _publication_impl.current is originals["publication"]
    assert maintenance_impl._validate_sep_mutation_rows is originals["maintenance_validator"]
    assert readiness_impl.check_readiness is originals["readiness"]
    assert sep_reconciliation_impl._source_fingerprint is originals["sep_fingerprint"]
    assert staging_impl.staged is originals["staged"]


def test_reverse_import_order_keeps_implementation_callables_stable():
    from sentinel.feed import (
        _publication_impl, maintenance_impl, readiness_impl,
        sep_reconciliation_impl, staging_impl,
    )

    originals = (
        _publication_impl.current,
        maintenance_impl._validate_sep_mutation_rows,
        readiness_impl.check_readiness,
        sep_reconciliation_impl._source_fingerprint,
        staging_impl.staged,
    )
    modules = (
        "sentinel.feed.staging", "sentinel.feed.sep_reconciliation",
        "sentinel.feed.readiness", "sentinel.feed.maintenance",
        "sentinel.feed.publication",
    )
    for module_name in modules:
        importlib.reload(importlib.import_module(module_name))
    assert originals == (
        _publication_impl.current,
        maintenance_impl._validate_sep_mutation_rows,
        readiness_impl.check_readiness,
        sep_reconciliation_impl._source_fingerprint,
        staging_impl.staged,
    )


def test_public_feed_exports_are_direct_canonical_object_bindings():
    from sentinel.feed import (
        _publication_impl, maintenance, maintenance_impl, publication,
        readiness, readiness_impl, sep_reconciliation,
        sep_reconciliation_impl, staging, staging_impl,
    )

    assert publication.Publication is _publication_impl.Publication
    assert publication.CorpusIncoherent is _publication_impl.CorpusIncoherent
    assert publication.current is _publication_impl.current
    assert publication.pinned is _publication_impl.pinned
    assert publication.visible_predicate is _publication_impl.visible_predicate

    assert maintenance.SourceCursor is maintenance_impl.SourceCursor
    assert maintenance.load_sep_cursor is maintenance_impl.load_sep_cursor
    assert (
        maintenance.reconcile_actions_if_due
        is maintenance_impl.reconcile_actions_if_due
    )

    assert readiness.Check is readiness_impl.Check
    assert readiness.Readiness is readiness_impl.Readiness
    assert readiness.ReadinessSnapshot is readiness_impl.ReadinessSnapshot
    assert readiness.latest_snapshot is readiness_impl.latest_snapshot
    assert readiness.save_snapshot is readiness_impl.save_snapshot

    assert (
        sep_reconciliation.ReconciliationResult
        is sep_reconciliation_impl.ReconciliationResult
    )
    assert (
        sep_reconciliation.SepKeysetDrift
        is sep_reconciliation_impl.SepKeysetDrift
    )

    assert staging.clear is staging_impl.clear
    assert staging.stage is staging_impl.stage


def test_hidden_feed_modules_expose_no_duplicate_production_orchestration():
    from sentinel.feed import _publication_impl, sep_reconciliation_impl

    assert not hasattr(_publication_impl, "publish")
    for name in ("reconcile_year", "reconcile_all", "reconcile_next"):
        assert not hasattr(sep_reconciliation_impl, name)


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
