"""Durable, non-authoritative hints for bounded missing-source recovery."""
from __future__ import annotations

import json

from sentinel.feed import rolling_jobs as jobs, source_probe
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.feed.source_authority.dates import SourceAuthorityRefused


class SourceCoveragePending(SourceAuthorityRefused):
    """Pure missing membership; it never excuses a missing price."""

    def __init__(self, evidence):
        self.evidence = evidence
        from sentinel.feed import source_corrections
        self.corrections_sha256 = digest(source_corrections.current())
        super().__init__('Sharadar SEP seed eligible-set coverage refused: '
                         + json.dumps(evidence, separators=(",", ":")))


def record(conn, lease, exc):
    jobs._owned(conn, lease)
    value = {'coverage': exc.evidence, 'corrections_sha256': exc.corrections_sha256}
    conn.execute('INSERT INTO sentinel_acquisition_source_wait VALUES (%s,%s,%s::jsonb) '
                 'ON CONFLICT(job_id) DO UPDATE SET evidence_sha256=EXCLUDED.evidence_sha256,'
                 'payload=EXCLUDED.payload', (lease.job_id, digest(value), canonical_json(value)))


def check(conn, lease, request, source):
    """A probe only permits another full proof, never publication by itself."""
    from sentinel.automation.model import SourceDataPending
    from sentinel.feed import acquisition_work, rolling_source
    from sentinel.feed.acquisition_parts import PartCorrupt, SourceRevision
    jobs._owned(conn, lease)
    row = conn.execute('SELECT evidence_sha256,payload FROM sentinel_acquisition_source_wait '
                       'WHERE job_id=%s', (lease.job_id,)).fetchone()
    if row is None:
        return
    checksum, value = row
    if (digest(value) != checksum or set(value) != {'coverage', 'corrections_sha256'}):
        raise PartCorrupt('source wait evidence changed')
    if digest(source.corrections) != value['corrections_sha256']:
        return  # New reviewed data must earn the entire coverage/normalization proof.
    pending = SourceCoveragePending(value['coverage'])
    pending.corrections_sha256 = value['corrections_sha256']
    hint = source_probe.coverage_hint(str(pending))
    with source.parts.unit():
        # A metadata revision can resolve a gap by changing its denominator,
        # without ever supplying the formerly expected price. Revalidate those
        # source changes even when the small membership probe is still missing.
        for snapshot in source.snapshots:
            name = rolling_source.component(snapshot)
            prior = conn.execute('SELECT p.manifest FROM sentinel_acquisition_bindings b '
                'JOIN sentinel_acquisition_parts p USING(part_id) WHERE b.job_id=%s AND b.component=%s',
                (lease.job_id, name)).fetchone()
            if prior and prior[0]['generation'] != rolling_source.generation(snapshot):
                raise SourceRevision(name, digest(prior[0]['generation']), digest(rolling_source.generation(snapshot)))
        if hint is None:
            # Truncated evidence cannot become a partial probe.
            raise pending
        try:
            source_probe.require_recovery_probe(hint, through=str(request.window.end))
        except SourceDataPending as exc:
            raise pending from exc
        # Provider JSON now contains the absent identity. Discard only the
        # affected monthly export, then require the full independent export proof.
        snapshot = next((item for item in source.snapshots if item.table == 'SEP'
                         and item.params['date.gte'] <= hint['session'] <= item.params['date.lte']), None)
        if snapshot is None:
            raise PartCorrupt('source wait session outside frozen acquisition window')
        with acquisition_work.cached_file(snapshot) as path:
            path.unlink(missing_ok=True)
        raise SourceRevision(rolling_source.component(snapshot), checksum, 'SOURCE_PROBE_RECOVERED')
