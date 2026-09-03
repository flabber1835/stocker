from __future__ import annotations

import pytest

from sentinel.feed import _publication_impl, runtime_schema


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        text = str(sql)
        self.conn.executed.append((text, params))
        if "pg_try_advisory_xact_lock(%s,%s)" in text:
            self.result = (self.conn.schema_lock,)
        elif "pg_try_advisory_xact_lock(%s)" in text:
            self.result = (self.conn.corpus_lock,)
        elif "to_regclass('public.sentinel_corpus_publications')" in text:
            self.result = (self.conn.shape,)
        elif "COALESCE(MAX(version),0)" in text:
            self.result = (self.conn.legacy_max,)
        elif ("COUNT(*)::bigint, COALESCE(MIN(required_after_version),-1)::bigint"
              in text):
            self.result = self.conn.installed_policy
        elif ("COUNT(*)::bigint, MIN(required_after_version)::bigint" in text):
            self.result = self.conn.post_policy
        elif text == "TEST_DDL":
            self.conn.ddl_count += 1
            self.result = None
        elif text.startswith("SET LOCAL"):
            self.result = None
        else:
            raise AssertionError("unexpected SQL: %s" % text)

    def fetchone(self):
        value = self.result
        self.result = None
        return value


class _Connection:
    def __init__(
            self, *, shape="1:0:0", legacy_max=7, schema_lock=True,
            corpus_lock=True, installed_policy=(1, 7, 7),
            post_policy=(1, 7, 7)):
        self.shape = shape
        self.legacy_max = legacy_max
        self.schema_lock = schema_lock
        self.corpus_lock = corpus_lock
        self.installed_policy = installed_policy
        self.post_policy = post_policy
        self.executed = []
        self.ddl_count = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _isolate_catalog(monkeypatch):
    monkeypatch.setattr(runtime_schema, "DDL", ["TEST_DDL"])
    monkeypatch.setattr(
        runtime_schema.behavioral_schema, "_read_catalog",
        lambda _cur: ({}, {}, {}, {}, {}))
    monkeypatch.setattr(runtime_schema, "_validate_catalog", lambda _catalog: None)
    monkeypatch.setattr(runtime_schema, "_validate_views", lambda _cur: None)


def test_receipt_migration_uses_canonical_corpus_lock_key():
    assert runtime_schema._CORPUS_LOCK_KEY == _publication_impl.CORPUS_LOCK_KEY


def test_legacy_receipt_shape_refuses_without_explicit_attestation(
        monkeypatch):
    _isolate_catalog(monkeypatch)
    conn = _Connection(shape="1:0:0", legacy_max=7)

    with pytest.raises(
            runtime_schema.FeedSchemaRefused,
            match="explicit verified pre-receipt migration attestation is required"):
        runtime_schema.migrate_feed_schema(conn)

    assert conn.ddl_count == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_verified_pre_receipt_migration_binds_locked_legacy_frontier(
        monkeypatch):
    _isolate_catalog(monkeypatch)
    conn = _Connection(
        shape="1:0:0", legacy_max=7, post_policy=(1, 7, 7))

    runtime_schema.migrate_feed_schema(
        conn, allow_verified_pre_receipt=True)

    assert conn.ddl_count == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert any(
        "pg_try_advisory_xact_lock(%s)" in sql
        and params == (runtime_schema._CORPUS_LOCK_KEY,)
        for sql, params in conn.executed)


def test_verified_pre_receipt_migration_refuses_wrong_policy_boundary(
        monkeypatch):
    _isolate_catalog(monkeypatch)
    conn = _Connection(
        shape="1:0:0", legacy_max=7, post_policy=(1, 8, 8))

    with pytest.raises(
            runtime_schema.FeedSchemaRefused,
            match="did not bind the receipt policy to the locked legacy publication frontier"):
        runtime_schema.migrate_feed_schema(
            conn, allow_verified_pre_receipt=True)

    assert conn.ddl_count == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1


@pytest.mark.parametrize("shape", ["0:1:0", "0:0:1", "1:1:0", "1:0:1", "0:1:1"])
def test_attestation_never_bypasses_partial_receipt_schema(monkeypatch, shape):
    _isolate_catalog(monkeypatch)
    conn = _Connection(shape=shape)

    with pytest.raises(
            runtime_schema.FeedSchemaRefused,
            match="receipt schema is partially installed"):
        runtime_schema.migrate_feed_schema(
            conn, allow_verified_pre_receipt=True)

    assert conn.ddl_count == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_missing_installed_policy_never_reseeds_from_latest_publication(
        monkeypatch):
    _isolate_catalog(monkeypatch)
    conn = _Connection(shape="1:1:1", installed_policy=(0, -1, -1))

    with pytest.raises(
            runtime_schema.FeedSchemaRefused,
            match="policy singleton is missing or ambiguous"):
        runtime_schema.migrate_feed_schema(conn)

    assert conn.ddl_count == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_corpus_lock_busy_refuses_before_receipt_authority_read(monkeypatch):
    _isolate_catalog(monkeypatch)
    conn = _Connection(shape="1:0:0", corpus_lock=False)

    with pytest.raises(
            runtime_schema.FeedSchemaRefused,
            match="corpus publication authority is busy"):
        runtime_schema.migrate_feed_schema(
            conn, allow_verified_pre_receipt=True)

    assert not any("to_regclass" in sql for sql, _params in conn.executed)
    assert conn.ddl_count == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1
