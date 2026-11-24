"""Opt-in rolling data publication through ordinary corpus receipts. No GO."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sentinel import backup_runtime_authority, identity
from sentinel.feed import calendar, publication, rolling_jobs as jobs, rolling_store, store
from sentinel.feed.rolling_contract import FormationWindow, PriceWindow, digest
from sentinel.feed.observation_timing import latest_acquirable_session

SCHEMA = "sentinel.operational-snapshot-publication/1"
VALIDATION_SCHEMA = "sentinel.operational-snapshot-validation/1"
SUPERSESSION_SCHEMA = "sentinel.operational-snapshot-supersession/1"
_OLD_ALPACA_POLICY = (
    "sentinel.alpaca-openfigi-operational-source/3",
    "sentinel.rolling-alpaca-openfigi-references/3",
    "sentinel.alpaca-openfigi-dividend-current-window/3",
)
_MERGER_ALPACA_POLICY = (
    "sentinel.alpaca-openfigi-operational-source/4",
    "sentinel.rolling-alpaca-openfigi-references/4",
    "sentinel.alpaca-openfigi-dividend-current-window/4",
)


class OperationalSnapshotRefused(RuntimeError):
    pass


class PublicationAdmissionBusy(backup_runtime_authority.BackupIntegrityBusy):
    """An exact backup check refused the writer before any publication mutation."""


def _now():
    return datetime.now(timezone.utc)


def source_final_session(now=None):
    now = _now() if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise OperationalSnapshotRefused("SOURCE_CLOCK_MUST_BE_AWARE")
    return latest_acquirable_session(now)


def registered(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sentinel_operational_snapshot_jobs WHERE job_id=%s", (job_id,))
        return cur.fetchone() is not None


def _current(conn):
    return publication._validate_publication(conn, publication._core.current(conn), allow_snapshot=True)


def enqueue(conn, *, strategy_sha256, dependencies_sha256, budget_seconds=3600,
            resume_job_id=None, absolute_deadline=None):
    """Freeze the current source-final target and ordinary publication CAS. No commit."""
    current = _current(conn)
    request = jobs.PreparationRequest(
        window=acquisition_window(conn, strategy_sha256),
        expected_publication_version=current.version if current else None,
        strategy_sha256=strategy_sha256,
        dependencies_sha256=digest({"schema": SCHEMA, "dependencies": dependencies_sha256}))
    if resume_job_id is not None:
        state = jobs.status(conn, resume_job_id)
        if (not registered(conn, resume_job_id)
                or jobs.PreparationRequest.model_validate(state["request"]) != request
                or state["state"] != "RETRY_WAIT"
                or state["reason"] != "BACKUP_HORIZON_EXCEEDED"
                or state["remaining_seconds"] <= 0
                or state["owner"] is not None):
            raise OperationalSnapshotRefused("BACKUP_RESUME_JOB_NOT_CURRENT")
        return str(resume_job_id)
    job = jobs.enqueue(conn, request, budget_seconds=budget_seconds,
                       absolute_deadline=absolute_deadline)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_operational_snapshot_jobs VALUES (%s) ON CONFLICT DO NOTHING", (job,))
    return job


def acquisition_window(conn, strategy_sha256):
    from sentinel import rolling_checkpoint
    from sentinel.strategy import production_strategy
    _, strategy = production_strategy()
    if strategy_sha256 == digest(strategy):
        from sentinel.core.window_policy import enabled, formed
        if enabled(strategy) and not formed(strategy):
            return PriceWindow.through(source_final_session())
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('sentinel_processed_sessions')")
            installed = cur.fetchone()[0]
        if installed and not rolling_checkpoint.lineage_names(conn):
            rolling_checkpoint.require_fresh(conn)
            from sentinel.feed.rolling_contract import CurrentFormationWindow
            cls = CurrentFormationWindow if formed(strategy) else FormationWindow
            return cls.through(source_final_session())
    return PriceWindow.through(source_final_session())


def enqueue_reconstruction(conn, *, session, cursor, strategy_sha256,
                           dependencies_sha256, budget_seconds=3600, absolute_deadline=None):
    """Acquire a missed bounded transition now; never backdate publication."""
    current = _current(conn)
    request = jobs.PreparationRequest(window=PriceWindow.through(session),
        cursor=cursor, expected_publication_version=current.version if current else None,
        strategy_sha256=strategy_sha256,
        dependencies_sha256=digest({'schema': SCHEMA, 'scope':'CURRENT_INFORMATION_RECOVERY_V1',
                                    'dependencies':dependencies_sha256}))
    _require_reconstruction_request(conn, request)
    job = jobs.enqueue(conn, request, budget_seconds=budget_seconds, absolute_deadline=absolute_deadline)
    conn.execute('INSERT INTO sentinel_operational_snapshot_jobs VALUES (%s) ON CONFLICT DO NOTHING', (job,))
    return job


def _require_reconstruction_request(conn, request):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    from sentinel.core import window_policy
    from sentinel.strategy import production_strategy
    _, strategy = production_strategy()
    previous = rolling_daily_checkpoint.read(conn) or rolling_checkpoint.read(conn)
    if (not window_policy.enabled(strategy) or request.strategy_sha256 != digest(strategy)
            or request.cursor is None or previous is None
            or previous.session != str(request.cursor)
            or calendar.next_session(previous.session) != str(request.window.end)
            or str(request.window.end) > source_final_session()
            or type(request.window) is not PriceWindow):
        raise OperationalSnapshotRefused('RECONSTRUCTION_REQUEST_NOT_BOUND_TO_RETAINED_BOOK')


def freeze(conn, lease, request):
    store._assert_corpus_locked(conn)
    jobs._owned(conn, lease)
    if not registered(conn, lease.job_id):
        raise OperationalSnapshotRefused("OPERATIONAL_JOB_REGISTRATION_REQUIRED")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sentinel_snapshot_comparisons WHERE job_id=%s", (lease.job_id,))
        if cur.fetchone():
            raise OperationalSnapshotRefused("COMPARISON_CANNOT_BECOME_OPERATIONAL")
    current = _current(conn)
    if (current.version if current else None) != request.expected_publication_version:
        raise OperationalSnapshotRefused("PUBLICATION_CAS_CHANGED")
    reconstruction = request.cursor is not None
    if reconstruction:
        _require_reconstruction_request(conn, request)
    elif str(request.window.end) != source_final_session():
        raise OperationalSnapshotRefused("SOURCE_FINAL_TARGET_CHANGED")
    if not reconstruction and current and current.window_end and str(request.window.end) < current.window_end:
        raise OperationalSnapshotRefused("PUBLICATION_FRONTIER_REGRESSION")
    if isinstance(request.window, FormationWindow):
        expected = acquisition_window(conn, request.strategy_sha256)
        if expected != request.window:
            raise OperationalSnapshotRefused('FORMATION_REQUIRES_FRESH_OWNED55_LINEAGE')


def validate(conn, lease, request):
    """Expensive immutable content/reference checks outside the publication lock."""
    from sentinel.core.rolling_inputs import readiness_inputs
    row = jobs._owned(conn, lease)
    if row[0] != "READY":
        raise OperationalSnapshotRefused("OPERATIONAL_VALIDATION_REQUIRES_READY")
    candidate = str(row[6])
    manifest = rolling_store.manifest(conn, candidate)
    backup_runtime_authority.require_staging(conn, operation="operational snapshot validation")
    jobs._owned(conn, lease)
    readiness_inputs(conn, candidate_id=candidate, snapshot_id=manifest.snapshot_id, staged=True)
    proof = {"schema": VALIDATION_SCHEMA, "scope": "DATA_ONLY",
             "snapshot_id": manifest.snapshot_id, "reference_sha256": manifest.reference_sha256,
             "source_evidence_sha256": manifest.source_evidence_sha256,
             "request_sha256": request.request_sha256}
    jobs._owned(conn, lease)
    sha = rolling_store.put_evidence(conn, proof)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_operational_snapshot_validations VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (candidate, sha))
        cur.execute("SELECT validation_sha256 FROM sentinel_operational_snapshot_validations WHERE candidate_id=%s",
                    (candidate,))
        if cur.fetchone()[0] != sha:
            raise OperationalSnapshotRefused("OPERATIONAL_VALIDATION_CHANGED")


def _bound_and_manifest(conn, pub):
    binding = pub.evidence.get("rolling_snapshot")
    if not isinstance(binding, dict) or binding.get("schema") != SCHEMA:
        raise OperationalSnapshotRefused("NOT_AN_OPERATIONAL_SNAPSHOT")
    with conn.cursor() as cur:
        cur.execute("SELECT b.job_id,b.candidate_id,b.validation_sha256,j.state,j.publication_version "
                    "FROM sentinel_operational_snapshots b JOIN sentinel_snapshot_jobs j USING(job_id) "
                    "WHERE b.publication_version=%s", (pub.version,))
        row = cur.fetchone()
    if (row is None or row[3] != "PUBLISHED" or row[4] != pub.version
            or str(row[0]) != binding.get("job_id") or str(row[1]) != binding.get("candidate_id")
            or row[2] != binding.get("validation_sha256")):
        raise OperationalSnapshotRefused("OPERATIONAL_BINDING_MISMATCH")
    manifest = rolling_store.manifest(conn, str(row[1]))
    request = jobs.PreparationRequest.model_validate(jobs.status(conn, str(row[0]))["request"])
    proof = rolling_store.load_evidence(conn, row[2])
    if (binding.get("snapshot_id") != manifest.snapshot_id
            or binding.get("reference_sha256") != manifest.reference_sha256
            or proof.get("schema") != VALIDATION_SCHEMA or proof.get("scope") != "DATA_ONLY"
            or proof.get("snapshot_id") != manifest.snapshot_id
            or proof.get("reference_sha256") != manifest.reference_sha256
            or proof.get("source_evidence_sha256") != manifest.source_evidence_sha256
            or proof.get("request_sha256") != request.request_sha256):
        raise OperationalSnapshotRefused("OPERATIONAL_PROOF_MISMATCH")
    binding = {"data_version": pub.version, "scope": "DATA_ONLY", "operational_go": False,
               "job_id": str(row[0]), "candidate_id": str(row[1]), "snapshot_id": manifest.snapshot_id}
    return binding, manifest


def _bound(conn, pub):
    binding, _ = _bound_and_manifest(conn, pub)
    return binding


def _alpaca_policy(conn, manifest):
    if manifest.provider != 'ALPACA_OPENFIGI':
        return None
    source = rolling_store.load_evidence(conn, manifest.source_evidence_sha256)
    reference = rolling_store.load_evidence(conn, manifest.reference_sha256)
    if not isinstance(source, dict) or not isinstance(reference, dict):
        raise OperationalSnapshotRefused('SUPERSESSION_SOURCE_EVIDENCE_INVALID')
    return source.get('schema'), reference.get('schema'), manifest.normalization_version


def superseded_source(conn, pub):
    """Whether this publication needs the reviewed merger source successor."""
    _, manifest = _bound_and_manifest(conn, pub)
    return _alpaca_policy(conn, manifest) == _OLD_ALPACA_POLICY


def _session_consumed(conn, session):
    # A publisher holds the exclusive corpus lock. A canonical transition
    # holds a shared publication pin, so no checkpoint can cross this test.
    if conn.execute("SELECT to_regclass('sentinel_processed_sessions')").fetchone()[0] is None:
        return False
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    checkpoint = rolling_daily_checkpoint.read(conn) or rolling_checkpoint.read(conn)
    return checkpoint is not None and checkpoint.session >= session


def _require_correction_strategy(conn, previous, request):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    from sentinel.strategy import production_strategy

    selected = production_strategy()[1]
    if request.strategy_sha256 != digest(selected):
        raise OperationalSnapshotRefused('SUPERSESSION_SELECTED_STRATEGY_CHANGED')
    checkpoint = rolling_daily_checkpoint.read(conn) or rolling_checkpoint.read(conn)
    if checkpoint is not None and (checkpoint.session >= previous.window_end
            or not rolling_checkpoint.compatible_strategy(checkpoint.strategy_identity, selected)):
        raise OperationalSnapshotRefused('SUPERSESSION_STRATEGY_COMPATIBILITY_UNPROVEN')


def _edge_fields(conn, previous, candidate, request):
    older, old_manifest = _bound_and_manifest(conn, previous)
    new_manifest = rolling_store.manifest(conn, candidate)
    old_policy = _alpaca_policy(conn, old_manifest)
    new_policy = _alpaca_policy(conn, new_manifest)
    if (old_policy not in (_OLD_ALPACA_POLICY, _MERGER_ALPACA_POLICY)
            or new_policy != _MERGER_ALPACA_POLICY):
        raise OperationalSnapshotRefused('SAME_SESSION_SUPERSESSION_POLICY_REQUIRED')
    old_request = jobs.PreparationRequest.model_validate(jobs.status(conn, older['job_id'])['request'])
    if (previous.version != request.expected_publication_version
            or previous.window_end != str(request.window.end)):
        raise OperationalSnapshotRefused('SAME_SESSION_SUPERSESSION_PREDECESSOR_CHANGED')
    reference = rolling_store.load_evidence(conn, new_manifest.reference_sha256)
    source = rolling_store.load_evidence(conn, new_manifest.source_evidence_sha256)
    conversions = reference.get('merger_conversions') if isinstance(reference, dict) else None
    if (not isinstance(conversions, list)
            or not any(isinstance(item, dict) and item.get('effective_session') == previous.window_end
                       for item in conversions)
            or not isinstance(source, dict)
            or source.get('merger_conversions_sha256') != digest(conversions)):
        raise OperationalSnapshotRefused('SAME_SESSION_MERGER_CORRECTION_REQUIRED')
    if old_policy == _MERGER_ALPACA_POLICY:
        prior_reference = rolling_store.load_evidence(conn, old_manifest.reference_sha256)
        prior_source = rolling_store.load_evidence(conn, old_manifest.source_evidence_sha256)
        prior = (prior_reference.get('merger_conversions')
                 if isinstance(prior_reference, dict) else None)
        if (not isinstance(prior, list) or not isinstance(prior_source, dict)
                or prior_source.get('merger_conversions_sha256') != digest(prior)
                or old_manifest.snapshot_id == new_manifest.snapshot_id
                or old_manifest.source_evidence_sha256 == new_manifest.source_evidence_sha256):
            raise OperationalSnapshotRefused('SAME_SESSION_MERGER_EXTENSION_REQUIRED')
        old_by_id = {item.get('old_security_id'): item for item in prior
                     if isinstance(item, dict) and isinstance(item.get('old_security_id'), str)}
        new_by_id = {item.get('old_security_id'): item for item in conversions
                     if isinstance(item, dict) and isinstance(item.get('old_security_id'), str)}
        if (len(old_by_id) != len(prior) or len(new_by_id) != len(conversions)
                or len(new_by_id) <= len(old_by_id)
                or any(sid not in new_by_id or digest(new_by_id[sid]) != digest(item)
                       for sid, item in old_by_id.items())
                or any(item.get('effective_session') != previous.window_end
                       for sid, item in new_by_id.items() if sid not in old_by_id)):
            raise OperationalSnapshotRefused('SAME_SESSION_MERGER_EXTENSION_REQUIRED')
    return {
        'schema': SUPERSESSION_SCHEMA, 'session': previous.window_end,
        'superseded_version': previous.version,
        'superseded_publication_sha256': digest(previous.to_dict()),
        'superseded_snapshot_id': old_manifest.snapshot_id,
        'superseded_source_sha256': old_manifest.source_evidence_sha256,
        'superseded_source_schema': old_policy[0],
        'successor_candidate_id': candidate,
        'successor_snapshot_id': new_manifest.snapshot_id,
        'successor_source_sha256': new_manifest.source_evidence_sha256,
        'successor_source_schema': _MERGER_ALPACA_POLICY[0],
        'superseded_strategy_sha256': old_request.strategy_sha256,
        'successor_strategy_sha256': request.strategy_sha256,
    }


def _require_supersession(conn, pub, remaining):
    """Authenticate every edge behind a correction tip within a fixed bound."""
    edge = pub.evidence.get('operational_supersession')
    if edge is None:
        return None
    if remaining <= 0:
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_CHAIN_LIMIT')
    publication._validate_publication(conn, pub, allow_snapshot=True)
    version = edge.get('superseded_version') if isinstance(edge, dict) else None
    if type(version) is not int or version < 1:
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_CHANGED')
    row = conn.execute(
        'SELECT version,previous_version,run_id,window_start,window_end,evidence '
        'FROM sentinel_corpus_publications WHERE version=%s', (version,)).fetchone()
    if row is None:
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_PREDECESSOR_MISSING')
    previous = publication.Publication(int(row[0]), row[1], str(row[2]) if row[2] else None,
                                       str(row[3]), str(row[4]), row[5])
    publication._validate_publication(conn, previous, allow_snapshot=True)
    binding = _bound(conn, pub)
    request = jobs.PreparationRequest.model_validate(jobs.status(conn, binding['job_id'])['request'])
    at_row = conn.execute('SELECT published_at FROM sentinel_corpus_publications WHERE version=%s',
                          (pub.version,)).fetchone()
    opened, _ = calendar.session_window(calendar.next_session(previous.window_end))
    if (pub.previous_version != previous.version
            or pub.window_end != previous.window_end
            or at_row is None
            or (at_row[0] >= opened) != (request.cursor is not None)
            or ('operational_recovery' in pub.evidence) != (request.cursor is not None)
            or edge != _edge_fields(conn, previous, binding['candidate_id'], request)):
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_CHANGED')
    _require_supersession(conn, previous, remaining - 1)
    return previous


def require_supersession(conn, pub):
    """Authenticate the full immutable correction chain; return its predecessor."""
    return _require_supersession(conn, pub, 8)


def require_alpaca_openfigi(conn, pub):
    """Reject a legacy rolling candidate at a deployed operational boundary."""
    binding, manifest = _bound_and_manifest(conn, pub)
    if manifest.provider != "ALPACA_OPENFIGI":
        raise OperationalSnapshotRefused("OPERATIONAL_ALPACA_OPENFIGI_SOURCE_REQUIRED")
    return binding


def published(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT publication_version FROM sentinel_operational_snapshots WHERE job_id=%s", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute("SELECT version,previous_version,run_id,window_start,window_end,evidence "
                    "FROM sentinel_corpus_publications WHERE version=%s", (row[0],))
        p = cur.fetchone()
    pub = publication.Publication(int(p[0]), p[1], str(p[2]) if p[2] else None,
                                  str(p[3]), str(p[4]), p[5])
    publication._validate_publication(conn, pub, allow_snapshot=True)
    return _bound(conn, pub)


def publish(conn, lease, request, *, producer):
    """Atomically append ordinary receipt, snapshot binding and job. Caller commits."""
    freeze(conn, lease, request)
    row = jobs._owned(conn, lease)
    if row[0] != "READY" or jobs.PreparationRequest.model_validate(row[7]) != request:
        raise OperationalSnapshotRefused("OPERATIONAL_PUBLICATION_REQUIRES_BOUND_READY")
    actual_producer = identity.require_feed_producer_identity()
    if producer != actual_producer:
        raise OperationalSnapshotRefused("PUBLICATION_PRODUCER_CHANGED")
    try:
        backup_runtime_authority.require(conn, operation="operational snapshot publication")
    except backup_runtime_authority.BackupIntegrityBusy as exc:
        raise PublicationAdmissionBusy(str(exc)) from exc
    candidate = str(row[6])
    manifest = rolling_store.manifest(conn, candidate)
    with conn.cursor() as cur:
        cur.execute("SELECT validation_sha256 FROM sentinel_operational_snapshot_validations WHERE candidate_id=%s", (candidate,))
        validated = cur.fetchone()
    proof = rolling_store.load_evidence(conn, validated[0]) if validated else {}
    if proof != {"schema": VALIDATION_SCHEMA, "scope": "DATA_ONLY",
                 "snapshot_id": manifest.snapshot_id, "reference_sha256": manifest.reference_sha256,
                 "source_evidence_sha256": manifest.source_evidence_sha256,
                 "request_sha256": request.request_sha256}:
        raise OperationalSnapshotRefused("BOUND_OPERATIONAL_VALIDATION_REQUIRED")
    previous = _current(conn)
    same_session = previous is not None and previous.window_end == str(request.window.end)
    correction = False
    if same_session:
        _, old_manifest = _bound_and_manifest(conn, previous)
        correction = (_alpaca_policy(conn, old_manifest) == _OLD_ALPACA_POLICY
                      or _alpaca_policy(conn, manifest) == _MERGER_ALPACA_POLICY)
    edge = None
    if correction:
        if _session_consumed(conn, previous.window_end):
            raise OperationalSnapshotRefused('SAME_SESSION_PUBLICATION_ALREADY_CONSUMED')
        _require_correction_strategy(conn, previous, request)
        edge = _edge_fields(conn, previous, candidate, request)
    version = previous.version + 1 if previous else 1
    evidence = {"producer": actual_producer, "pitr": publication._publication_recovery_target(conn),
                "rolling_snapshot": {"schema": SCHEMA, "candidate_id": candidate,
                    "snapshot_id": manifest.snapshot_id, "reference_sha256": manifest.reference_sha256,
                    "job_id": lease.job_id, "validation_sha256": validated[0]},
                "strategy_history": {"schema": "sentinel.strategy-history-mutations/1",
                    "baseline_version": version, "publication_version": version, "changes": []}}
    if edge is not None:
        evidence['operational_supersession'] = edge
    from sentinel.feed import action_history, rolling_work
    with rolling_work.renewing(lambda: jobs.heartbeat(conn, lease, lease_seconds=600)):
        evidence["action_history"] = action_history.append(
            conn, candidate=candidate, version=version, previous=previous)
    jobs._owned(conn, lease)
    at = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    if correction:
        opened, _ = calendar.session_window(calendar.next_session(previous.window_end))
        if (at >= opened) != (request.cursor is not None):
            raise OperationalSnapshotRefused('SAME_SESSION_CORRECTION_TIMING_CHANGED')
    if request.cursor is not None:
        evidence['operational_recovery'] = {
            'schema':'sentinel.current-information-recovery-inputs/1',
            'policy':'CURRENT_INFORMATION_RECOVERY_V1', 'cursor':str(request.cursor),
            'session':str(request.window.end), 'observed_at':at.isoformat(),
            'historical_availability_claim':False, 'broker_authority':False}
    publication._insert_receipted_publication(
        conn, previous=previous, next_version=version, run_id=None, published_at=at,
        window_start=str(request.window.start), window_end=str(request.window.end), publication_evidence=evidence)
    jobs._owned(conn, lease)  # Receipt-chain work cannot extend the publication lease.
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_operational_snapshots VALUES (%s,%s,%s,%s)",
                    (version, lease.job_id, candidate, validated[0]))
        cur.execute("UPDATE sentinel_snapshot_jobs SET state='PUBLISHED',reason='OPERATIONAL_DATA_PUBLISHED',"
                    "publication_version=%s,owner=NULL,lease_until=NULL,next_retry=NULL,updated_at=clock_timestamp() "
                    "WHERE job_id=%s", (version, lease.job_id))
    return published(conn, lease.job_id)


@contextmanager
def pinned(conn, *, commit=True):
    with publication._core.pinned(conn, commit=commit) as pub:
        publication._validate_publication(conn, pub, allow_snapshot=True)
        yield pub, _bound(conn, pub)


def prepare(conn, job_id):
    from sentinel.feed.rolling_publisher import _prepare
    return _prepare(conn, job_id, operational=True)
