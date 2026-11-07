"""Authenticated rolling display metadata; no financial corpus admission."""
from sentinel.feed import operational_snapshot as snapshots, publication, readers
from sentinel.feed import readiness, rolling_jobs as jobs, rolling_store


def status_snapshot(conn, *, include_publication=False):
    """Read one fresh, read-only MVCC frame; caller owns its rollback."""
    if conn.autocommit:
        raise ValueError('DISPLAY_STATUS_REQUIRES_CALLER_TRANSACTION')
    with conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    pub = _current(conn)
    if pub is None or not readers.is_rolling(pub):
        return readers.status_snapshot(conn, include_publication=include_publication)
    snapshot = readiness.latest_snapshot(conn)
    result = pub.window_end, snapshot if readers.snapshot_matches(pub, snapshot) else None
    return (*result, pub.version) if include_publication else result


def _current(conn):
    from sentinel.feed import readiness_scope
    readiness_scope.require(conn)
    try:
        return publication.current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != 'ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER':
            raise
    pub = snapshots._current(conn)
    _binding(conn, pub)
    return pub


def _manifest(conn, candidate_id):
    """Project immutable metadata, retaining the financial reader's validations."""
    if conn.autocommit:
        raise rolling_store.SnapshotStorageRefused('DISPLAY_MANIFEST_REQUIRES_CALLER_TRANSACTION')
    settings = conn.execute(
        "SELECT current_setting('transaction_isolation'),"
        "current_setting('transaction_read_only')").fetchone()
    if settings != ('repeatable read', 'on'):
        raise rolling_store.SnapshotStorageRefused('DISPLAY_MANIFEST_REQUIRES_READ_ONLY_SNAPSHOT')
    row = conn.execute(
        'SELECT snapshot_id,manifest,session_axis,reference_sha256,source_evidence_sha256 '
        'FROM sentinel_price_candidates WHERE candidate_id=%s', (candidate_id,)).fetchone()
    if row is None or row[1] is None:
        raise rolling_store.SnapshotStorageRefused('candidate has no sealed manifest')
    value = rolling_store.SnapshotManifest.model_validate(row[1])
    if value.snapshot_id != row[0]:
        raise rolling_store.SnapshotStorageRefused('snapshot manifest content identity differs')
    if (value.window.model_dump(mode='json')['sessions'] != row[2]
            or value.reference_sha256 != row[3] or value.source_evidence_sha256 != row[4]):
        raise rolling_store.SnapshotStorageRefused('snapshot manifest differs from its candidate')
    from sentinel.feed.normalized_layout import require_layout
    require_layout(conn, candidate_id, value)
    if not rolling_store.retired(conn, candidate_id):
        rolling_store.verify_evidence(conn, value.reference_sha256)
        rolling_store.verify_evidence(conn, value.source_evidence_sha256)
    return value


def _binding(conn, pub):
    """Project the existing DATA_ONLY binding; never grant operational GO."""
    binding = pub.evidence.get('rolling_snapshot')
    if not isinstance(binding, dict) or binding.get('schema') != snapshots.SCHEMA:
        raise snapshots.OperationalSnapshotRefused('NOT_AN_OPERATIONAL_SNAPSHOT')
    row = conn.execute(
        'SELECT b.job_id,b.candidate_id,b.validation_sha256,j.state,j.publication_version '
        'FROM sentinel_operational_snapshots b JOIN sentinel_snapshot_jobs j USING(job_id) '
        'WHERE b.publication_version=%s', (pub.version,)).fetchone()
    if (row is None or row[3] != 'PUBLISHED' or row[4] != pub.version
            or str(row[0]) != binding.get('job_id') or str(row[1]) != binding.get('candidate_id')
            or row[2] != binding.get('validation_sha256')):
        raise snapshots.OperationalSnapshotRefused('OPERATIONAL_BINDING_MISMATCH')
    manifest = _manifest(conn, str(row[1]))
    request = jobs.PreparationRequest.model_validate(jobs.status(conn, str(row[0]))['request'])
    proof = rolling_store.load_evidence(conn, row[2])
    if (binding.get('snapshot_id') != manifest.snapshot_id
            or binding.get('reference_sha256') != manifest.reference_sha256
            or proof.get('schema') != snapshots.VALIDATION_SCHEMA or proof.get('scope') != 'DATA_ONLY'
            or proof.get('snapshot_id') != manifest.snapshot_id
            or proof.get('reference_sha256') != manifest.reference_sha256
            or proof.get('source_evidence_sha256') != manifest.source_evidence_sha256
            or proof.get('request_sha256') != request.request_sha256):
        raise snapshots.OperationalSnapshotRefused('OPERATIONAL_PROOF_MISMATCH')
    return dict(data_version=pub.version, scope='DATA_ONLY', operational_go=False,
                job_id=str(row[0]), candidate_id=str(row[1]), snapshot_id=manifest.snapshot_id)
