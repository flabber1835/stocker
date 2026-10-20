"""A complete input scan can be borrowed only while its real pin survives."""
from contextvars import copy_context
from copy import deepcopy
import inspect
import textwrap

import psycopg
import pytest
from sentinel.execution import feed_inputs
from sentinel.feed import readiness_scope, rolling_store, publication
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


def count_scans(monkeypatch):
    original = rolling_store._verify_content_uncached; calls=[]
    def observed(*args): calls.append(args[1]); return original(*args)
    monkeypatch.setattr(rolling_store, '_verify_content_uncached', observed)
    return calls


def test_complete_scan_is_shared_across_reference_readers_and_guard_connections(conn, published, monkeypatch):
    calls = count_scans(monkeypatch); candidate=published['candidate_id']
    with feed_inputs.pinned(conn, commit=False) as pub:
        first=rolling_store.verify_content(conn,candidate)
        expected=deepcopy(first); object.__setattr__(first,'bar_count',first.bar_count+1)
        with psycopg.connect(conn.info.dsn) as guard:
            assert rolling_store.verify_content(guard,candidate)==expected
            feed_inputs.references(guard,pub)
            assert readiness_scope._current.get().verified_snapshots
        conn.commit()
        assert rolling_store.verify_content(conn,candidate)==expected
        assert calls==[candidate]
        inherited=copy_context()
    with feed_inputs.pinned(conn,commit=False):
        with pytest.raises(publication.CorpusIncoherent,match='SCOPE_EXPIRED'):
            inherited.run(rolling_store.verify_content,conn,candidate)
        rolling_store.verify_content(conn,candidate)
    assert calls==[candidate,candidate]


def test_released_original_pin_cannot_reacquire_and_reuse_proof(conn,published,monkeypatch):
    candidate=published['candidate_id']; calls=count_scans(monkeypatch)
    with psycopg.connect(conn.info.dsn) as owner:
        with feed_inputs.pinned(owner,commit=False):
            rolling_store.verify_content(owner,candidate)
            owner.execute('SELECT pg_advisory_unlock_all()');owner.commit()
            with psycopg.connect(conn.info.dsn) as guard:
                with pytest.raises(publication.CorpusIncoherent,match='PIN_LOST'):
                    rolling_store.verify_content(guard,candidate)
    assert calls==[candidate]


def test_changed_manifest_and_partial_scan_install_no_reusable_proof(conn,published,monkeypatch):
    candidate=published['candidate_id']; original=rolling_store._verify_content_uncached
    with feed_inputs.pinned(conn,commit=False):
        monkeypatch.setattr(rolling_store,'_verify_content_uncached',lambda *a: (_ for _ in ()).throw(TimeoutError('scan cancelled')))
        with pytest.raises(TimeoutError):rolling_store.verify_content(conn,candidate)
        assert not readiness_scope._current.get().verified_snapshots
        monkeypatch.setattr(rolling_store,'_verify_content_uncached',original)
        first=rolling_store.verify_content(conn,candidate)
        saved=rolling_store.manifest
        def changed(*a):
            return saved(*a).model_copy(update={'bars_sha256':'0'*64},deep=True)
        monkeypatch.setattr(rolling_store,'manifest',changed)
        with pytest.raises(publication.CorpusIncoherent,match='MANIFEST_CHANGED'):
            rolling_store.verify_content(conn,candidate)
        assert first.bars_sha256!='0'*64


def test_other_candidate_cannot_borrow_current_snapshot_proof(conn,published,monkeypatch):
    candidate=published['candidate_id']; original=rolling_store._verify_content_uncached; calls=[]
    with feed_inputs.pinned(conn,commit=False):
        rolling_store.verify_content(conn,candidate)
        def foreign(*a):calls.append(a[1]);raise rolling_store.SnapshotStorageRefused('foreign candidate')
        monkeypatch.setattr(rolling_store,'_verify_content_uncached',foreign)
        with pytest.raises(rolling_store.SnapshotStorageRefused):rolling_store.verify_content(conn,'foreign-candidate')
        assert calls==['foreign-candidate']
        monkeypatch.setattr(rolling_store,'_verify_content_uncached',original)
        rolling_store.verify_content(conn,candidate)


def test_unscoped_and_new_scope_reverify_actual_corrupted_rows(conn,published):
    candidate=published['candidate_id']
    with feed_inputs.pinned(conn,commit=False):rolling_store.verify_content(conn,candidate)
    conn.execute('ALTER TABLE sentinel_snapshot_bars DISABLE TRIGGER ALL')
    conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=close_unadjusted+1 WHERE candidate_id=%s',(candidate,))
    conn.execute('ALTER TABLE sentinel_snapshot_bars ENABLE TRIGGER ALL');conn.commit()
    with pytest.raises(rolling_store.SnapshotStorageRefused,match='differs'):
        rolling_store.verify_content(conn,candidate)
    with feed_inputs.pinned(conn,commit=False),pytest.raises(rolling_store.SnapshotStorageRefused,match='differs'):
        rolling_store.verify_content(conn,candidate)


@pytest.mark.parametrize('guard',['pin','manifest','detach','failure'])
def test_removed_snapshot_reuse_guards_are_detected(conn,published,monkeypatch,guard):
    if guard=='pin':
        monkeypatch.setattr(readiness_scope,'_require_pin',lambda *a:None)
        check=lambda:test_released_original_pin_cannot_reacquire_and_reuse_proof(conn,published,monkeypatch)
    else:
        source=textwrap.dedent(inspect.getsource(readiness_scope.verified_snapshot))
        if guard=='manifest':
            source=source.replace("if current.snapshot_id != binding['snapshot_id']:",'if False:').replace('if not isinstance(cached, rolling_store.VerifiedSnapshot) or cached.manifest != current:','if False:')
            check=lambda:test_changed_manifest_and_partial_scan_install_no_reusable_proof(conn,published,monkeypatch)
        elif guard=='detach':
            # A caller must not be able to poison the stored proof.
            source=source.replace('return deepcopy(completed.readiness if summary_only else completed.manifest)',
                                  'return completed.readiness if summary_only else completed.manifest')
            def check():
                candidate=published['candidate_id']
                with feed_inputs.pinned(conn,commit=False):
                    expected=rolling_store.manifest(conn,candidate).bar_count
                    rolling_store.verify_content(conn,candidate)
                    one=rolling_store.verify_content(conn,candidate)
                    object.__setattr__(one,'bar_count',one.bar_count+1)
                    assert rolling_store.verify_content(conn,candidate).bar_count==expected
        else:
            source=source.replace('completed = load()',"completed = rolling_store.VerifiedSnapshot(current, None)\n        try: load()\n        except TimeoutError: pass")
            check=lambda:test_changed_manifest_and_partial_scan_install_no_reusable_proof(conn,published,monkeypatch)
        namespace={};exec(compile(source,'snapshot-reuse-falsifier','exec'),readiness_scope.__dict__,namespace)
        monkeypatch.setattr(readiness_scope,'verified_snapshot',namespace['verified_snapshot'])
    with pytest.raises((AssertionError,pytest.fail.Exception,publication.CorpusIncoherent)):
        check()
