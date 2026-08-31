"""Put this directory on sys.path so the suites share one `fakes` module.

`tests/` has no `__init__.py`, so these are not importable as a package — and a
`tests/sentinel/__init__.py` must NOT be added to fix that: it would make
`import sentinel` resolve to the TEST package and shadow the real one, which is
exactly how this suite first failed to collect.

A small compatibility fixture also keeps older unit-level database doubles at
the seam they actually exercise. Routine Sentinel paths now use read-only schema
validation. Older tests that pre-date that split still use ``ensure_schema`` as
fixture bootstrap, so this file preserves the historical installer only inside
the test process; production never imports this module.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(HERE), str(ROOT), str(ROOT / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)


_LEGACY_SCHEMA_DOUBLE_MODULES = {
    "test_automation_runtime",
    "test_paper_cli",
}
_SINGLETON_REFUSAL_TESTS = {
    "test_missing_control_singleton_refuses_instead_of_reseeding",
    "test_schema_check_never_repairs_a_deleted_control_singleton",
}
_FEED_RUNTIME_SCHEMA_CONTRACT_PREFIX = "test_issue_165_feed_schema"
_ISSUE_178_SOURCE_AUTHORITY_PREFIX = "test_issue_178_"


def _legacy_feed_fixture_install(conn) -> None:
    """Install feed DDL without invoking the production schema validator.

    Legacy fixtures still use ``ensure_schema`` as setup. Keep that test-only
    compatibility spelling, but include derived feed relations required by the
    current runtime so those fixtures exercise the same data model as production.
    """
    from sentinel.feed.schema import DDL as BASE_DDL
    from sentinel.feed.universe_projection import DDL as UNIVERSE_PROJECTION_DDL

    try:
        with conn.cursor() as cur:
            for statement in (*BASE_DDL, *UNIVERSE_PROJECTION_DDL):
                cur.execute(statement)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@pytest.fixture(autouse=True)
def _runtime_schema_test_double_compat(request, monkeypatch):
    """Keep legacy doubles narrow without weakening production validation."""
    from sentinel import schema
    from sentinel.feed import store as feed_store

    module_name = request.module.__name__.rsplit(".", 1)[-1]

    # This module deliberately drives a fixed August 2026 scheduling tape. Its
    # run-loop tests also open fresh PostgreSQL connections, so bind the database
    # wall clock to that same deterministic tape instead of letting the fixture
    # expire as real calendar time advances. Dedicated issue-201 tests exercise
    # the actual host/database skew refusal outside this compatibility module.
    if module_name == "test_automation_service":
        from sentinel.automation import integrity as automation_integrity

        deterministic_now = request.module.AFTER_WEDNESDAY_CLOSE
        monkeypatch.setattr(
            automation_integrity, "database_now",
            lambda _conn: deterministic_now)

    # Production IngestRun now refuses to exist without the deployment binding
    # established by sentinel-compose.sh. Most unit modules construct runs
    # directly because they test SQL/economic behavior rather than host Docker
    # identity. Keep that seam explicit and deterministic; the dedicated
    # deployment-provenance module exercises the real fail-closed function.
    if module_name != "test_feed_deployment_provenance":
        from sentinel import identity as runtime_identity

        monkeypatch.setattr(
            runtime_identity, "require_feed_producer_identity",
            lambda: {
                "schema": "sentinel.feed-producer/1",
                "git_commit": "a" * 40,
                "runtime_image_digest": "sha256:" + "b" * 64,
                "image_source_revision": "a" * 40,
            })

    # The legacy readiness fixture predates the dedicated recent-export cursor.
    # Its purpose is to construct a corpus that is healthy except for the one
    # domain a test deliberately damages, so complete its synthetic authority
    # bundle with the new cursor. Tests dedicated to the recent-source gate live
    # in test_issue_185_readiness.py and are not touched here.
    if module_name == "test_readiness":
        original_load = request.module.load

        def load_with_recent_authority(conn, *args, **kwargs):
            result = original_load(conn, *args, **kwargs)
            from sentinel.feed import recent_reconciliation as recent

            published = request.module.P.require_current(conn)
            request.module.M._write_cursor(
                conn, name=recent.CURSOR_NAME, kind=recent.CURSOR_KIND,
                through=request.module.dt.date.fromisoformat(request.module.TODAY),
                publication_version=published.version)
            return result

        monkeypatch.setattr(request.module, "load", load_with_recent_authority)

    if module_name in _LEGACY_SCHEMA_DOUBLE_MODULES:
        # Resolve ensure_schema at call time: the legacy tests install their
        # own no-I/O/refusal stub after this autouse fixture has been created.
        monkeypatch.setattr(
            schema, "require_runtime_schema",
            lambda conn: schema.ensure_schema(conn))
        monkeypatch.setattr(
            feed_store, "require_feed_schema",
            lambda conn: feed_store.ensure_schema(conn))

    # Before issue #165, feed fixtures used ensure_schema as an installer.
    # Preserve that convenience with DDL-only behavior, rather than weakening
    # or bypassing the new production migration validator. The DDL must still
    # include derived feed relations used by the current runtime.
    if not module_name.startswith(_FEED_RUNTIME_SCHEMA_CONTRACT_PREFIX):
        monkeypatch.setattr(
            feed_store, "ensure_schema", _legacy_feed_fixture_install)

    if not module_name.startswith(_ISSUE_178_SOURCE_AUTHORITY_PREFIX):
        # Issue #178 makes the production source contract deliberately stricter:
        # real TICKERS authority must identify its Sharadar product explicitly,
        # and historical SEP chunks must satisfy calibrated full-source floors.
        # A large body of older unit tests intentionally models neither thing:
        # their injected vendors use one/few rows and pre-date the TICKERS
        # ``table`` field because they exercise action reconciliation, corpus
        # publication, memory behavior, retry semantics, etc.
        #
        # Keep compatibility at the TEST seam and make it input-sensitive. A
        # legacy TICKERS fixture is synthetic only when every returned row omits
        # the product field. Accept those rows for the metadata tests they were
        # built to exercise, but deliberately DO NOT add ``table=SEP``: that tag
        # now carries completeness authority at persistence, and manufacturing it
        # in a test shim would turn a one-row fake into a false whole-snapshot
        # negative-space claim. Any fixture that names a product is real source-
        # contract evidence and still runs the complete validator. Likewise,
        # only sub-calibration synthetic seed populations bypass historical
        # completeness. The issue-178 falsifier modules are excluded entirely.
        from sentinel.feed import coherence

        real_assert_tickers_metadata = coherence.assert_tickers_metadata
        real_assert_seed_history = coherence.assert_seed_history

        def legacy_synthetic_tickers(rows):
            materialized = list(rows)
            if materialized and all("table" not in row for row in materialized):
                return materialized
            if not materialized:
                return materialized
            return real_assert_tickers_metadata(materialized)

        def legacy_synthetic_seed(sessions, *, date_from, date_to):
            if not sessions:
                return None
            if max(counts.rows for counts in sessions.values()) < \
                    coherence.MIN_SEED_SESSION_ROWS:
                return None
            return real_assert_seed_history(
                sessions, date_from=date_from, date_to=date_to)

        monkeypatch.setattr(
            coherence, "assert_tickers_metadata", legacy_synthetic_tickers)
        monkeypatch.setattr(
            coherence, "assert_seed_history", legacy_synthetic_seed)

    if request.node.name in _SINGLETON_REFUSAL_TESTS:
        # These tests pre-date the stronger explicit-migration final check.
        # Fresh fixture bootstrap must still be able to create the schema. If
        # the test subsequently deletes the authority singleton, accept the
        # stronger early refusal and continue to the original assertion that
        # the state was not guessed or reseeded. Any other migration refusal
        # remains a hard failure.
        real_ensure_schema = schema.ensure_schema

        def allow_stronger_singleton_refusal(conn):
            try:
                return real_ensure_schema(conn)
            except schema.SchemaMigrationRefused as exc:
                if ("Stage-4 singleton sentinel_automation_control is missing"
                        in str(exc)):
                    return None
                raise

        monkeypatch.setattr(
            schema, "ensure_schema", allow_stronger_singleton_refusal)
