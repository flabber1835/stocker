"""Dated input selection uses real authenticated publication/job bindings."""
from copy import deepcopy

import pytest
import psycopg

from sentinel import strategy
from sentinel.feed import operational_snapshot as op, rolling_go_inputs as inputs, rolling_jobs
from sentinel import rolling_reconstruction_evidence as evidence
from sentinel.feed.rolling_contract import digest, canonical_json
from tests.sentinel.test_rolling_recovery import (
    conn, pg, source, operational_source, issuer_source, ready, dated_source, published)  # noqa: F401


def selected_upgrade(monkeypatch):
    controller, old = strategy.production_strategy()
    selected = {**deepcopy(old), 'data_semantics_source_sha256': 'a'*64}
    assert selected != old
    monkeypatch.setattr(strategy, 'production_strategy', lambda: (controller, selected))
    monkeypatch.setattr(inputs, 'production_strategy', lambda: (controller, selected))
    return controller, old, selected


def test_stale_sole_dated_publication_is_unavailable_not_accepted(conn, published, monkeypatch):
    pub = inputs.current(conn)
    selected_upgrade(monkeypatch)
    with pytest.raises(evidence.InputsUnavailable, match='MISSING_DATED_PUBLICATION:2026-09-14'):
        evidence.select(conn, session='2026-09-14', previous_version=0)
    # The strict reader continues to reject direct reuse of the old publication.
    with pytest.raises(inputs.RollingGoRefused, match='^ROLLING_DATA_GENERATION_STRATEGY_ADMISSION_REQUIRED$'):
        inputs.validate_reconstruction(conn, pub, summary_only=True)
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0


def test_unchanged_strategy_keeps_exact_dated_selection(conn, published):
    current = inputs.current(conn)
    pub, binding = evidence.select(conn, session='2026-09-14', previous_version=0)
    assert pub.to_dict() == current.to_dict()
    assert binding == op._bound(conn, current)


def publish_selected(conn, selected, label):
    job = op.enqueue(conn, strategy_sha256=digest(selected), dependencies_sha256=digest(label))
    conn.commit()
    return op.prepare(conn, job)


def test_stale_and_compatible_publications_select_only_compatible(conn, published, monkeypatch):
    stale = inputs.current(conn)
    _, _, selected = selected_upgrade(monkeypatch)
    fresh = publish_selected(conn, selected, 'new selected strategy')
    pub, binding = evidence.select(conn, session='2026-09-14', previous_version=0)
    assert pub.version == fresh['data_version'] and pub.version != stale.version
    assert binding['candidate_id'] == fresh['candidate_id']


def test_two_compatible_dated_publications_remain_ambiguous(conn, published, monkeypatch):
    _, _, selected = selected_upgrade(monkeypatch)
    publish_selected(conn, selected, 'compatible first')
    publish_selected(conn, selected, 'compatible second')
    with pytest.raises(evidence.InputsUnavailable, match='AMBIGUOUS_DATED_PUBLICATION'):
        evidence.select(conn, session='2026-09-14', previous_version=0)


def test_selected_request_tampering_remains_a_hard_refusal(conn, published, monkeypatch):
    _, _, selected = selected_upgrade(monkeypatch)
    # The normal database guard rejects request tampering before selection.
    job = op._bound(conn, inputs.current(conn))['job_id']
    with pytest.raises(psycopg.errors.RaiseException, match='job request, deadline and terminal outcomes are immutable'):
        conn.execute("UPDATE sentinel_snapshot_jobs SET request=jsonb_set(request,'{strategy_sha256}',to_jsonb(%s::text)) WHERE job_id=%s", (digest(selected), job))
    conn.rollback()
    # On this isolated fixture only, bypass that write guard to independently
    # verify that the authenticated publication proof also refuses the forgery.
    conn.execute('ALTER TABLE sentinel_snapshot_jobs DISABLE TRIGGER USER')
    request = rolling_jobs.PreparationRequest.model_validate({
        **rolling_jobs.status(conn, job)['request'], 'strategy_sha256': digest(selected)})
    conn.execute('UPDATE sentinel_snapshot_jobs SET request=%s::jsonb,request_sha256=%s WHERE job_id=%s',
                 (canonical_json(request.model_dump(mode='json')), request.request_sha256, job))
    conn.execute('ALTER TABLE sentinel_snapshot_jobs ENABLE TRIGGER USER')
    with pytest.raises(op.OperationalSnapshotRefused, match='OPERATIONAL_PROOF_MISMATCH'):
        evidence.select(conn, session='2026-09-14', previous_version=0)
    conn.rollback()
