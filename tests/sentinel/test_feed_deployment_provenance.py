"""A stale immutable image may be inspected, never used as a corpus writer."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import sentinel_feed_gate as gate
from sentinel import identity


A = "a" * 40
B = "b" * 40
DIGEST = "sha256:" + "c" * 64


def test_mutating_feed_commands_are_classified_at_the_compose_boundary():
    assert gate.is_feed_mutation(["run", "--rm", "sentinel", "feed-daily"])
    assert gate.is_feed_mutation([
        "run", "-T", "--env", "X=1", "sentinel", "feed-seed"])
    assert gate.is_feed_mutation([
        "run", "--rm", "sentinel", "feed-repair", "--apply"])
    assert not gate.is_feed_mutation([
        "run", "--rm", "sentinel", "feed-repair"])
    assert not gate.is_feed_mutation([
        "run", "--rm", "sentinel", "identity"])


def test_old_image_A_cannot_run_feed_daily_after_source_advances_to_B():
    """The requested falsifier: immutability is not current authorization."""
    with pytest.raises(gate.FeedGateRefused, match="built from.*clean repository HEAD"):
        gate.validate_binding(
            head=B, dirty=False, image_revision=A,
            image_ref=DIGEST, image_id=DIGEST)


def test_matching_clean_head_resolves_and_binds_the_selected_digest():
    assert gate.validate_binding(
        head=B, dirty=False, image_revision=B,
        image_ref="registry.example/sentinel@" + DIGEST,
        image_id="sha256:" + "d" * 64) == (B, DIGEST)


def test_dirty_source_cannot_authorize_even_a_matching_image():
    with pytest.raises(gate.FeedGateRefused, match="worktree is dirty"):
        gate.validate_binding(
            head=B, dirty=True, image_revision=B,
            image_ref=DIGEST, image_id=DIGEST)


def test_compatible_environment_is_not_a_deployment_certification():
    verdict = identity.certification_verdict(
        {"compatible": True},
        {"git_commit": "", "runtime_image_digest": ""})
    assert verdict["environment_compatible"] is True
    assert verdict["deployment_certified"] is False
    assert verdict["certified"] is False
    assert "GIT_COMMIT_MISSING_OR_MALFORMED" in verdict["failures"]


def test_container_feed_binding_requires_baked_revision_and_injected_facts(
        monkeypatch):
    monkeypatch.setattr(identity, "environment", lambda: {"compatible": True})
    values = {
        "SENTINEL_FEED_AUTHORIZED": identity.FEED_AUTHORIZATION_VALUE,
        "SENTINEL_FEED_GIT_COMMIT": B,
        "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": DIGEST,
        "SENTINEL_IMAGE_SOURCE_REVISION": B,
        "SENTINEL_GIT_COMMIT": B,
        "SENTINEL_RUNTIME_IMAGE_DIGEST": DIGEST,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    producer = identity.require_feed_producer_identity()
    assert producer["git_commit"] == B
    assert producer["runtime_image_digest"] == DIGEST

    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", A)
    with pytest.raises(RuntimeError, match="baked image source revision differs"):
        identity.require_feed_producer_identity()

    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", B)
    monkeypatch.setattr(identity, "environment", lambda: {"compatible": False})
    with pytest.raises(RuntimeError, match="fully deployment-certified"):
        identity.require_feed_producer_identity()


def test_cli_refuses_unbound_feed_before_database_contact(monkeypatch, capsys):
    import sentinel.__main__ as cli
    from sentinel.feed import store

    monkeypatch.setattr(
        identity, "require_feed_producer_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("unbound producer")))
    monkeypatch.setattr(
        store, "connect",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("database was contacted")))
    rc = cli.cmd_feed(
        SimpleNamespace(database_url="postgresql://must-not-be-used"),
        SimpleNamespace(command="feed-daily"))
    assert rc == cli.EXIT_NOT_ESTABLISHED
    assert "unbound producer" in capsys.readouterr().err


class _Cursor:
    def __init__(self, row=None):
        self.row = row
        self.statement = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params):
        self.statement = statement
        self.params = params

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row=None):
        self.cursor_value = _Cursor(row)
        self.commits = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1


def test_ingest_run_persists_the_authorized_commit_and_digest(monkeypatch):
    from sentinel.feed import store

    monkeypatch.setattr(identity, "require_feed_producer_identity", lambda: {
        "schema": "sentinel.feed-producer/1",
        "git_commit": B,
        "runtime_image_digest": DIGEST,
        "image_source_revision": B,
    })
    conn = _Connection()
    store.IngestRun(conn, "daily")
    assert "source_git_commit, runtime_image_digest" in conn.cursor_value.statement
    assert conn.cursor_value.params[-2:] == (B, DIGEST)
    assert conn.commits == 1


def test_publication_refuses_missing_or_different_run_producer(monkeypatch):
    from sentinel.feed import publication

    monkeypatch.setattr(identity, "require_feed_producer_identity", lambda: {
        "schema": "sentinel.feed-producer/1",
        "git_commit": B,
        "runtime_image_digest": DIGEST,
        "image_source_revision": B,
    })
    with pytest.raises(publication.CorpusIncoherent, match="no ingest run record"):
        publication._run_producer_identity(_Connection(), "missing")
    with pytest.raises(publication.CorpusIncoherent, match="missing or differs"):
        publication._run_producer_identity(
            _Connection((A, DIGEST)), "stale-run")
