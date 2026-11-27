"""The fixed economic pipeline is an exact extraction, not a source wildcard."""
import ast
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path

import pytest

from tests.support import alpaca_coverage_source as alpaca_coverage

from sentinel import economic_manifest, publisher_pipeline_source_basis as basis
from sentinel import semantic_source_basis as semantics
from sentinel.feed import operational_snapshot as snapshot
from sentinel.feed import publisher_pipeline as pipeline, rolling_publisher as lifecycle
from tests.support.publisher_source_proofs import publisher_baseline

EXPECTED_STRATEGY = alpaca_coverage.CURRENT_STRATEGY
HELPERS = ('ComparisonRefused', '_operational_source', '_latest', '_legacy_version',
           'published', 'freeze', 'publish', '_checkpoint')


def _definition(tree, name):
    return next(node for node in tree.body if getattr(node, 'name', None) == name)


def _dump(value):
    return ast.dump(value, include_attributes=False)


def _restore_contexts_and_observations(body):
    class Restore(ast.NodeTransformer):
        def visit_While(self, node):
            retry = ast.parse(
                'while True:\n'
                '    try:\n'
                '        backup_runtime_authority.require(conn, operation="operational publication preflight")\n'
                '        break\n'
                '    except backup_runtime_authority.BackupIntegrityBusy as exc:\n'
                '        observer.wait_for_backup(exc)').body[0]
            if _dump(node) == _dump(retry):
                return retry.body[0].body[0]
            return self.generic_visit(node)

        def visit_Expr(self, node):
            call = node.value
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == 'observer' and call.func.attr == 'stage'):
                assert len(call.args) == 1 and not call.keywords
                return ast.Assign(targets=[ast.Name(id='operation_stage', ctx=ast.Store())],
                                  value=call.args[0])
            return self.generic_visit(node)

        def visit_With(self, node):
            reporting = ast.parse(
                'with observer.reporting(phase, job_id):\n'
                '    while True:\n'
                '        try:\n'
                '            with observer.publication(phase, job_id):\n'
                '                pass\n'
                '            break\n'
                '        except operational_snapshot.PublicationAdmissionBusy as exc:\n'
                '            if not operational:\n'
                '                raise\n'
                '            observer.wait_for_backup(exc)').body[0]
            if _dump(node.items[0]) == _dump(reporting.items[0]):
                writer = node.body[0].body[0].body[0]
                reporting.body[0].body[0].body[0].body = writer.body
                assert _dump(node) == _dump(reporting)
                return self.visit_With(writer)
            self.generic_visit(node)
            if len(node.items) != 1:
                return node
            call = node.items[0].context_expr
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == 'observer'):
                return node
            assert node.items[0].optional_vars is None
            if call.func.attr == 'acquisition':
                assert not call.args and not call.keywords
                old = 'with writer_schedule.turn(conn, lease), store.acquisition_write_lock(conn):\n    pass'
            else:
                assert _dump(call) == _dump(ast.parse('observer.publication(phase, job_id)').body[0].value)
                old = ('with progress.phase(phase, job_id=job_id), writer_schedule.turn(conn, lease), '
                       'store.corpus_write_lock(conn):\n    pass')
            node.items = ast.parse(old).body[0].items
            return node
    return Restore().visit(ast.Module(body=deepcopy(body), type_ignores=[]))


def _assert_complete_pipeline(baseline_raw, pipeline_raw):
    old, new = ast.parse(baseline_raw), ast.parse(pipeline_raw)
    for name in HELPERS:
        assert _dump(_definition(old, name)) == _dump(_definition(new, name)), name
    original = _definition(old, '_prepare')
    original_try = next(node for node in original.body if isinstance(node, ast.Try))
    run = _definition(new, 'run')
    assert ast.get_docstring(run) == 'Run the fixed pipeline under an already claimed owned job.'
    assert _dump(run.body[1]) == _dump(ast.parse('from sentinel.feed import operational_snapshot').body[0])
    assert _dump(_restore_contexts_and_observations(run.body[2:])) == _dump(
        ast.Module(body=original_try.body, type_ignores=[]))
    # No other economic function can appear outside the exactly compared set.
    assert {n.name for n in new.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} == {
        *HELPERS, 'Observer', 'run'}


def test_complete_economic_pipeline_ast_matches_independent_installed_git_witness():
    _assert_complete_pipeline(publisher_baseline(),
        economic_manifest.previous_source(basis.PIPELINE_MODULE, Path(pipeline.__file__).read_bytes()))


@pytest.mark.parametrize('before,after', [
    (b'if not ready:', b'if False:'),
    (b'boundary.publish(conn, lease, request, producer=producer)',
     b'boundary.publish(conn, lease, request, producer={})'),
    (b'rolling_builder.build(conn, lease, request, source)',
     b'rolling_builder.build(conn, lease, request, None)'),
    (b'source.corroborate()', b'source.preflight()'),
    (b'observer.wait_for_backup(exc)', b'break'),
    (b'except operational_snapshot.PublicationAdmissionBusy as exc:', b'except Exception as exc:'),
    (b'with observer.acquisition():', b'with observer.publication(phase, job_id):'),
    (b'if _legacy_version(conn) != request.expected_publication_version:', b'if False:'),
])
def test_economic_neighbor_edits_fail_full_ast_and_contribute_actual_hash(before, after):
    current = Path(pipeline.__file__).read_bytes()
    assert before in current
    changed = current.replace(before, after, 1)
    assert basis.contribution(changed) == hashlib.sha256(changed).hexdigest()
    assert basis.contribution(changed) != basis.BASE_SHA256
    with pytest.raises(AssertionError):
        _assert_complete_pipeline(publisher_baseline(), changed)


def test_lifecycle_retains_original_failure_and_cleanup_ast():
    old = ast.parse(publisher_baseline())
    current = Path(lifecycle.__file__).read_text(encoding='utf-8')
    new = ast.parse(current)
    assert _dump(_definition(old, 'prepare')) == _dump(_definition(new, 'prepare'))
    # The late Alpaca evidence wait extends failure classification while the
    # preparation handler and cleanup remain pinned to their historical AST.
    failure_body = ast.get_source_segment(current, _definition(new, '_record_failure'))
    assert hashlib.sha256(failure_body.encode()).hexdigest() == (
        '81f3001e72cf4fd2cfef4a1ba8e607c7cdd3cbea8de89cfc3d48de8b0b68e513')
    old_prepare = _definition(old, '_prepare')
    new_prepare = _definition(new, '_prepare')
    old_try = next(n for n in old_prepare.body if isinstance(n, ast.Try))
    new_try = next(n for n in new_prepare.body if isinstance(n, ast.Try))
    # Restore the historical local stage variable for the handler comparison.
    handlers = deepcopy(new_try.handlers)
    for node in ast.walk(handlers[0]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'capture_stage'):
            node.args[1] = ast.Name(id='operation_stage', ctx=ast.Load())
    assert _dump(ast.Module(body=handlers, type_ignores=[])) == _dump(
        ast.Module(body=old_try.handlers, type_ignores=[]))
    # The idle SHADOW supervisor owns retention. Verify the exact remaining
    # operational commit, then restore retention solely for the baseline comparison.
    assert _dump(new_try.finalbody[0]) == _dump(ast.parse('observer.close()').body[0])
    cleanup = deepcopy(new_try.finalbody[1:])
    operational_cleanup = cleanup[0].body[-1]
    assert _dump(operational_cleanup) == _dump(ast.parse(
        'if operational:\n    conn.commit()').body[0])
    operational_cleanup.body = ast.parse(
        'from sentinel.feed import retention\nconn.commit()\nretention.maintain(conn)').body
    assert _dump(ast.Module(body=cleanup, type_ignores=[])) == _dump(
        ast.Module(body=old_try.finalbody, type_ignores=[]))
    assert _dump(new_try.body[0]) == _dump(ast.parse(
        'with progress.observing(observer.observe):\n'
        '    return publisher_pipeline.run(conn, job_id, operational=operational, '
        'boundary=boundary, lease=lease, observer=observer)').body[0])
    restored = deepcopy(new_prepare)
    observer_initialization = ast.parse(
        'observer = PublicationObserver(conn, lease, operational=operational)').body[0]
    replacements = [index for index, node in enumerate(restored.body)
                    if _dump(node) == _dump(observer_initialization)]
    assert len(replacements) == 1
    restored.body[replacements[0]] = ast.parse("operation_stage = 'SHADOW_ADVANCE'").body[0]
    restored_try = next(n for n in restored.body if isinstance(n, ast.Try))
    restored_try.body = deepcopy(old_try.body)
    restored_try.handlers = handlers
    restored_try.finalbody = cleanup
    assert _dump(restored) == _dump(old_prepare)


def test_current_logical_slot_uses_fixed_pipeline_bytes():
    raw = Path(pipeline.__file__).read_bytes()
    prior = economic_manifest.previous_source(basis.PIPELINE_MODULE, raw)
    assert hashlib.sha256(prior).hexdigest() == basis.PIPELINE_SHA256
    value = semantics.economic_sources([basis.MODULE], schema='pipeline-boundary-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': basis.BASE_SHA256}]
    assert {'module': basis.MODULE, 'actual_sha256': hashlib.sha256(raw).hexdigest(),
            'economic_sha256': basis.BASE_SHA256} in value['administrative_source_basis']['observed_seams']


def test_original_extracted_pipeline_still_has_its_proven_identity():
    raw = economic_manifest.previous_source(basis.PIPELINE_MODULE, Path(pipeline.__file__).read_bytes())
    tree = ast.parse(raw)
    observer = _definition(tree, 'Observer')
    run = _definition(tree, 'run')
    retry = next(node for node in ast.walk(run)
                 if isinstance(node, ast.While) and node.body[0].handlers[0].type.attr == 'BackupIntegrityBusy')
    lines = raw.splitlines(keepends=True)
    reporting = run.body[-2]
    writer = reporting.body[0].body[0].body[0]
    indent = writer.col_offset - reporting.col_offset
    lines[reporting.lineno - 1:reporting.end_lineno] = [
        line[indent:] for line in lines[writer.lineno - 1:writer.end_lineno]]
    guard = lines[retry.body[0].body[0].lineno - 1].lstrip()
    lines[retry.lineno - 1:retry.end_lineno] = [b' ' * retry.col_offset + guard]
    for name in ('reporting', 'wait_for_backup'):
        method = _definition(observer, name)
        del lines[method.lineno - 1:method.end_lineno]
    historical = b''.join(lines)
    assert hashlib.sha256(historical).hexdigest() == basis.EXTRACTED_PIPELINE_SHA256
    assert basis.contribution(historical) == basis.BASE_SHA256


def test_snapshot_identity_changes_only_for_its_exact_prepublication_guard(monkeypatch):
    from sentinel import economic_manifest
    from sentinel.feed import operational_snapshot

    name = operational_snapshot.__name__
    path = Path(operational_snapshot.__file__).resolve()
    current = path.read_bytes()
    # Reconstruct the independently pinned pre-merger compiler. The new
    # supersession functions and publication edge have a distinct current hash.
    historical = alpaca_coverage.predecessor(name, current)
    start = historical.index(b'SUPERSESSION_SCHEMA = ')
    stop = historical.index(b'\nclass OperationalSnapshotRefused', start)
    historical = historical[:start] + b'\n' + historical[stop:]
    start = historical.index(b'def _alpaca_policy(')
    stop = historical.index(b'def require_alpaca_openfigi(', start)
    historical = historical[:start] + historical[stop:]
    new_publish = (b'    previous = _current(conn)\n'
                   b'    same_session = previous is not None and previous.window_end == str(request.window.end)\n'
                   b'    correction = False\n'
                   b'    if same_session:\n'
                   b'        _, old_manifest = _bound_and_manifest(conn, previous)\n'
                   b'        correction = (_alpaca_policy(conn, old_manifest) == _OLD_ALPACA_POLICY\n'
                   b'                      or _alpaca_policy(conn, manifest) == _MERGER_ALPACA_POLICY)\n'
                   b'    edge = None\n'
                   b'    if correction:\n'
                   b'        if _session_consumed(conn, previous.window_end):\n'
                   b"            raise OperationalSnapshotRefused('SAME_SESSION_PUBLICATION_ALREADY_CONSUMED')\n"
                   b'        _require_correction_strategy(conn, previous, request)\n'
                   b'        edge = _edge_fields(conn, previous, candidate, request)\n')
    old_publish = (b'    previous = _current(conn)\n'
                   b'    with conn.cursor() as cur:\n'
                   b'        cur.execute("SELECT clock_timestamp()")\n'
                   b'        at = cur.fetchone()[0]\n')
    assert historical.count(new_publish) == 1
    historical = historical.replace(new_publish, old_publish)
    edge_and_timing = (b'    if edge is not None:\n'
                       b"        evidence['operational_supersession'] = edge\n"
                       b'    from sentinel.feed import action_history, rolling_work\n'
                       b'    with rolling_work.renewing(lambda: jobs.heartbeat(conn, lease, lease_seconds=600)):\n'
                       b'        evidence["action_history"] = action_history.append(\n'
                       b'            conn, candidate=candidate, version=version, previous=previous)\n'
                       b'    jobs._owned(conn, lease)\n'
                       b"    at = conn.execute('SELECT clock_timestamp()').fetchone()[0]\n"
                       b'    if correction:\n'
                       b'        opened, _ = calendar.session_window(calendar.next_session(previous.window_end))\n'
                       b'        if (at >= opened) != (request.cursor is not None):\n'
                       b"            raise OperationalSnapshotRefused('SAME_SESSION_CORRECTION_TIMING_CHANGED')\n")
    action_history = (b'    from sentinel.feed import action_history, rolling_work\n'
                      b'    with rolling_work.renewing(lambda: jobs.heartbeat(conn, lease, lease_seconds=600)):\n'
                      b'        evidence["action_history"] = action_history.append(\n'
                      b'            conn, candidate=candidate, version=version, previous=previous)\n'
                      b'    jobs._owned(conn, lease)\n')
    assert historical.count(edge_and_timing) == 1
    historical = historical.replace(edge_and_timing, b'')
    insert = b'    publication._insert_receipted_publication(\n'
    assert historical.count(insert) == 1
    historical = historical.replace(insert, action_history + insert)
    staged = b'readiness_inputs(conn, candidate_id=candidate, snapshot_id=manifest.snapshot_id, staged=True)'
    assert historical.count(staged) == 1
    changes = (
        (b'def _bound_and_manifest(conn, pub):', b'def _bound(conn, pub):'),
        (b'    binding = {"data_version": pub.version, "scope": "DATA_ONLY", "operational_go": False,\n'
         b'               "job_id": str(row[0]), "candidate_id": str(row[1]), "snapshot_id": manifest.snapshot_id}\n'
         b'    return binding, manifest\n\n\n'
         b'def _bound(conn, pub):\n    binding, _ = _bound_and_manifest(conn, pub)\n    return binding\n',
         b'    return {"data_version": pub.version, "scope": "DATA_ONLY", "operational_go": False,\n'
         b'            "job_id": str(row[0]), "candidate_id": str(row[1]), "snapshot_id": manifest.snapshot_id}\n'),
        (b'    binding, manifest = _bound_and_manifest(conn, pub)\n    if manifest.provider != "ALPACA_OPENFIGI":',
         b'    binding = _bound(conn, pub)\n'
         b'    if rolling_store.manifest(conn, binding["candidate_id"]).provider != "ALPACA_OPENFIGI":'),
    )
    prior = historical
    for reviewed, predecessor in changes:
        assert prior.count(reviewed) == 1
        prior = prior.replace(reviewed, predecessor)
    prior = prior.replace(staged, staged.replace(b', staged=True', b''))
    assert hashlib.sha256(prior).hexdigest() == basis.SNAPSHOT_ADMISSION_SHA256
    assert economic_manifest.SNAPSHOT_ADMISSION_SHA256 == basis.SNAPSHOT_ADMISSION_SHA256
    tag = (b'class PublicationAdmissionBusy(backup_runtime_authority.BackupIntegrityBusy):\n'
           b'    """An exact backup check refused the writer before any publication mutation."""\n\n\n')
    guard = b'    backup_runtime_authority.require(conn, operation="operational snapshot publication")\n'
    checked = (b'    try:\n    ' + guard + b'    except backup_runtime_authority.BackupIntegrityBusy as exc:\n'
               b'        raise PublicationAdmissionBusy(str(exc)) from exc\n')
    assert current.count(tag) == current.count(checked) == 1
    old = prior.replace(tag, b'').replace(checked, guard)
    assert hashlib.sha256(old).hexdigest() == basis.SNAPSHOT_BEFORE_SHA256
    read = Path.read_bytes
    with monkeypatch.context() as historical:
        historical.setattr(Path, 'read_bytes', lambda p: prior if p == path else read(p))
        assert semantics.economic_sources([name], schema='snapshot-proof')['files'] == [
            {'module': name, 'sha256': basis.SNAPSHOT_BEFORE_SHA256}]
    changed = current.replace(checked, b'    pass\n')
    monkeypatch.setattr(Path, 'read_bytes', lambda p: changed if p == path else read(p))
    assert semantics.economic_sources([name], schema='snapshot-proof')['files'] == [
        {'module': name, 'sha256': hashlib.sha256(changed).hexdigest()}]
    with pytest.raises(economic_manifest.EconomicManifestRefused, match='CLOSE_LINEAGE_PREDECESSOR_CHANGED'):
        economic_manifest.identity(schema='snapshot-proof')
    monkeypatch.setattr(Path, 'read_bytes', read)
    raw_module = economic_manifest._module_raw
    previous = economic_manifest._before_broker_reads({key: raw_module(key) for key in economic_manifest._BROKER_READ_BASE})
    changed = previous[name].replace(checked, b'    pass\n')
    assert changed != previous[name]
    monkeypatch.setattr(economic_manifest, '_module_raw', lambda member: changed if member == name
                        else previous.get(member) or raw_module(member))
    live = economic_manifest.identity(schema='snapshot-proof')
    assert {'module': name, 'sha256': hashlib.sha256(changed).hexdigest()} in live['files']
    assert live['sha256'] != alpaca_coverage.CURRENT_DATA_SEMANTICS


@pytest.mark.parametrize('name', economic_manifest.CLOSE_READINESS_COMPILERS)
def test_close_readiness_identity_requires_all_reviewed_compiler_bytes(monkeypatch, name):
    before = economic_manifest.identity(schema='close-readiness')
    assert before['sha256'] == before['implementation_sha256']
    assert before['economic_implementation']['preserved_behavior'] is False
    read = economic_manifest._module_raw
    previous = economic_manifest._before_broker_reads({key: read(key) for key in economic_manifest._BROKER_READ_BASE})
    changed = read(name) + b'\n# unreviewed compiler bytes\n'
    monkeypatch.setattr(economic_manifest, '_module_raw', lambda module: changed if module == name else read(module))
    if name in economic_manifest._BROKER_READ_BASE:
        with pytest.raises(economic_manifest.EconomicManifestRefused, match='PREDECESSOR_CHANGED'):
            economic_manifest.identity(schema='close-readiness')
        changed = previous[name] + b'\n# unreviewed compiler bytes\n'
        monkeypatch.setattr(economic_manifest, '_module_raw', lambda member: changed if member == name
                            else previous.get(member) or read(member))
    live = economic_manifest.identity(schema='close-readiness')
    assert {'module': name, 'sha256': hashlib.sha256(changed).hexdigest()} in live['files']
    assert live['sha256'] != before['sha256']


def test_state_only_recovery_snapshot_identity_has_exact_predecessor(monkeypatch):
    name = 'sentinel.feed.operational_snapshot'
    path = Path(snapshot.__file__).resolve()
    current = alpaca_coverage.predecessor(name, path.read_bytes())
    current_sha = hashlib.sha256(current).hexdigest()
    assert current_sha == economic_manifest.SNAPSHOT_RETIRED_EDGE_SHA256
    assert (economic_manifest.SNAPSHOT_RECOVERY_PREDECESSOR_SHA256
            == semantics.SNAPSHOT_RECOVERY_PREDECESSOR_SHA256)

    # Peel only the exact reviewed retirement read path. The older recovery
    # witness below must still reconstruct its own exact predecessor.
    retired_header = (b'def _edge_fields(conn, previous, candidate, request, *, older=None,\n'
        b'                 old_manifest=None, new_manifest=None):\n'
        b'    if older is None or old_manifest is None:\n'
        b'        older, old_manifest = _bound_and_manifest(conn, previous)\n'
        b'    if new_manifest is None:\n'
        b'        new_manifest = rolling_store.manifest(conn, candidate)\n')
    previous_header = (b'def _edge_fields(conn, previous, candidate, request):\n'
        b'    older, old_manifest = _bound_and_manifest(conn, previous)\n'
        b'    new_manifest = rolling_store.manifest(conn, candidate)\n')
    assert current.count(retired_header) == 1
    recovered = current.replace(retired_header, previous_header)
    helper_start = recovered.index(b'\n\ndef _retired_edge_fields(')
    helper_end = recovered.index(b'\n\ndef _require_supersession(', helper_start)
    recovered = recovered[:helper_start] + recovered[helper_end:]
    retired_check = b'''            or ('operational_recovery' in pub.evidence) != (request.cursor is not None)):
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_CHANGED')
    older, old_manifest = _bound_and_manifest(conn, previous)
    new_manifest = rolling_store.manifest(conn, binding['candidate_id'])
    old_retired = rolling_store.retired(conn, older['candidate_id'])
    new_retired = rolling_store.retired(conn, binding['candidate_id'])
    common = dict(older=older, old_manifest=old_manifest, new_manifest=new_manifest)
    expected = (_retired_edge_fields(conn, previous, binding['candidate_id'], request,
                                     edge, old_retired=old_retired, new_retired=new_retired,
                                     **common)
                if old_retired or new_retired else
                _edge_fields(conn, previous, binding['candidate_id'], request, **common))
    if edge != expected:
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_CHANGED')'''
    previous_check = b'''            or ('operational_recovery' in pub.evidence) != (request.cursor is not None)
            or edge != _edge_fields(conn, previous, binding['candidate_id'], request)):
        raise OperationalSnapshotRefused('OPERATIONAL_SUPERSESSION_CHANGED')'''
    assert recovered.count(retired_check) == 1
    recovered = recovered.replace(retired_check, previous_check)
    assert hashlib.sha256(recovered).hexdigest() == economic_manifest.SNAPSHOT_RECOVERY_SHA256
    assert hashlib.sha256(recovered).hexdigest() == semantics.SNAPSHOT_RECOVERY_SHA256

    recovery_schema = (
        b'RECOVERY_SUPERSESSION_SCHEMA = '
        b'"sentinel.current-information-recovery-supersession/1"\n')
    assert recovered.count(recovery_schema) == 1
    predecessor = recovered.replace(recovery_schema, b'')
    start = predecessor.index(b'def _edge_fields(conn, previous, candidate, request):')
    end = predecessor.index(b'\n\ndef _require_supersession', start)
    previous_edge = b'''def _edge_fields(conn, previous, candidate, request):
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
'''
    predecessor = predecessor[:start] + previous_edge + predecessor[end:]
    assert hashlib.sha256(predecessor).hexdigest() == (
        economic_manifest.SNAPSHOT_RECOVERY_PREDECESSOR_SHA256)

    raw_read = Path.read_bytes
    store_path = path.with_name('rolling_store.py')
    sealed_predecessor = alpaca_coverage._before_sealed_read('sentinel.feed.rolling_store', raw_read(store_path))
    def read(candidate):
        return sealed_predecessor if candidate == store_path else raw_read(candidate)
    monkeypatch.setattr(Path, 'read_bytes', read)
    with monkeypatch.context() as change:
        change.setattr(Path, 'read_bytes',
                       lambda candidate: current if candidate == path else read(candidate))
        source = semantics.economic_sources([name], schema='recovery-snapshot-proof')
        assert source['files'] == [{'module': name, 'sha256':
            economic_manifest.SNAPSHOT_RECOVERY_PREDECESSOR_SHA256}]
        identity = economic_manifest.identity(schema='recovery-snapshot-proof')
        assert {'module': name, 'sha256':
            economic_manifest.SNAPSHOT_RECOVERY_PREDECESSOR_SHA256} in identity['files']

    retired_guard = b'    if not (old_retired or new_retired):'
    assert current.count(retired_guard) == 1
    changed_retirement = current.replace(retired_guard, b'    if False:')
    changed_retirement_sha = hashlib.sha256(changed_retirement).hexdigest()
    original_raw = economic_manifest._module_raw
    with monkeypatch.context() as change:
        change.setattr(economic_manifest, '_module_raw',
            lambda module: changed_retirement if module == name else original_raw(module))
        assert {'module': name, 'sha256': changed_retirement_sha} in (
            economic_manifest.identity(schema='retired-edge-mutant')['files'])
    with monkeypatch.context() as change:
        change.setattr(Path, 'read_bytes',
            lambda candidate: changed_retirement if candidate == path else read(candidate))
        assert semantics.economic_sources([name], schema='retired-edge-mutant')['files'] == [
            {'module': name, 'sha256': changed_retirement_sha}]

    guard = b'request.cursor is not None and prior == conversions'
    assert recovered.count(guard) == 1
    mutated = recovered.replace(guard, b'request.cursor is not None or prior == conversions')
    mutated_sha = hashlib.sha256(mutated).hexdigest()
    with monkeypatch.context() as change:
        change.setattr(economic_manifest, '_module_raw',
            lambda module: mutated if module == name else original_raw(module))
        assert {'module': name, 'sha256': mutated_sha} in (
            economic_manifest.identity(schema='recovery-snapshot-mutant')['files'])
    with monkeypatch.context() as change:
        change.setattr(Path, 'read_bytes',
            lambda candidate: mutated if candidate == path else read(candidate))
        assert semantics.economic_sources([name], schema='recovery-snapshot-mutant')['files'] == [
            {'module': name, 'sha256': mutated_sha}]


def test_unknown_pipeline_bytes_reach_real_economic_bundle(monkeypatch):
    path = Path(pipeline.__file__).resolve()
    original = Path.read_bytes
    changed = original(path) + b'\n# unknown economic bytes\n'
    monkeypatch.setattr(Path, 'read_bytes', lambda p: changed if p == path else original(p))
    value = semantics.economic_sources([basis.MODULE], schema='pipeline-boundary-test')
    assert value['files'] == [{'module': basis.MODULE, 'sha256': hashlib.sha256(changed).hexdigest()}]


def test_economic_identity_matches_current_strategy():
    from sentinel.strategy import production_strategy
    from sentinel.feed.rolling_contract import digest
    assert digest(production_strategy()[1]) == EXPECTED_STRATEGY


def test_closed_pipeline_mapping_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.contribution)
    needle = 'prior in (EXTRACTED_PIPELINE_SHA256, PIPELINE_SHA256)'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'unclosed-pipeline', 'exec'), basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'contribution', namespace['contribution'])
    with pytest.raises(AssertionError):
        test_economic_neighbor_edits_fail_full_ast_and_contribute_actual_hash(
            b'if not ready:', b'if False:')
