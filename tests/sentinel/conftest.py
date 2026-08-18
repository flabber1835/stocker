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
