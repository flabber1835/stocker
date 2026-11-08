"""Complete reviewed source compatibility never grants financial authority."""
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path

import pytest

from tests.support.source_history import expanded_profile, encoded_profile

from sentinel import runtime_admission as admission
from sentinel import structural_refactor_source_basis as structural
from sentinel import transition_registry
from sentinel import url_selected_source_basis as basis
from tests.sentinel.test_backed_paper_source import (  # noqa: F401
    handover, owner_mode, _rebind_origin,
)


def _actual():
    return admission._source_files(Path(basis.__file__).parent)


ACCESS_PATH_ADDITIONS = {'checkpoint_lineage_access.py', 'operational_ddl_handoff.py',
                         'panel/feed_display.py'}
ACCESS_PATH_CHANGES = {'operational_catalog.py', 'operational_schema.py',
                       'rolling_daily_checkpoint.py', 'panel/review_migration.py'}
CASH_ADDITIONS = {'paper/cash_retirement.py'}
STARTUP_CHANGES = {'shadow_service_probe.py'}
COORDINATION_ADDITIONS = {'panel/composition.py','panel/dom_refresh.py','snapshot_scan_admission.py'}
COORDINATION_CHANGES = {'panel/presentation.py','panel/projection_worker.py','committed_read.py','rolling_runtime.py','paper/finalization.py','paper_plan_preview.py',
    'panel/projection_service.py','panel/overview.py','panel/render.py','panel/styles.py'}
READ_COST_ADDITIONS = COORDINATION_ADDITIONS | {
    'panel/verification_health.py', 'shadow_drain_observer.py',
    'shadow_service_config.py', 'shadow_exit_codes.py',
}
READ_COST_CHANGES = {
    'execution_collector.py', 'feed/retention.py', 'panel/intent_memo.py',
    'panel/projection_service.py', 'panel/verification_service.py', 'web_push.py',
    'shadow_drain.py', 'shadow_service.py', 'shadow_supervisor.py', 'shadow_worker.py',
    'url_selected_source_basis.py', 'supervisor_io.py', 'panel/authority_reader.py',
}
EFFICIENCY_ADDITIONS = {'panel/shadow_execution_projection.py'} | READ_COST_ADDITIONS
FEED_EVIDENCE_CHANGES = {'panel/feed_display.py'}
ROOT_CAUSE_CHANGES = {
    'automation/health.py', 'automation/service.py', 'automation/store.py',
    'alert_service.py', 'shadow_drain.py', 'shadow_supervisor.py',
    'shadow_health_projection.py', 'url_selected_source_basis.py',
} | READ_COST_CHANGES | COORDINATION_CHANGES
DIAGNOSTIC_CHANGES = {
    'supervisor_io.py', 'shadow_supervisor.py', 'automation_supervisor.py',
    'automation/health.py', 'alert_service.py',
    'url_selected_source_basis.py',
} | ROOT_CAUSE_CHANGES
EFFICIENCY_CHANGES = {
    'dual_reconciliation.py', 'paper/preparation.py', 'panel/model.py',
    'panel/observer_codec.py', 'panel/read_projection.py', 'panel/sources.py',
    'panel/verification_service.py', 'panel/projection_service.py', 'panel/review.py',
    'url_selected_source_basis.py',
} | DIAGNOSTIC_CHANGES
RECOVERY_CHANGES = {'cli/main.py', 'cli/paper.py', 'execution/alpaca.py', 'execution/alpaca_asset_id.py',
                'execution/certification.py', 'paper/preparation.py', 'paper/cash.py', 'restore_validation.py',
                'execution/authority_gate.py', 'paper/validation.py', 'operational_schema.py',
                'shadow_observation.py'}
MARKET_OPEN_CHANGES = {'automation/service.py', 'execution/alpaca.py', 'execution/cash_corrections.py',
                      'panel/operational_snapshot.py', 'panel/presentation.py',
                      'panel/model.py', 'panel/sources.py'}
OPERATIONAL_ADDITIONS = {
    'automation/source_completion.py', 'panel/attempt_store.py', 'panel/delivery.py', 'panel/observer_failure.py',
    'panel/operational_snapshot.py', 'panel/projection_service.py', 'panel/projection_worker.py',
    'panel/segment_disclosure.py', 'panel/serialization.py',
} | ACCESS_PATH_ADDITIONS | CASH_ADDITIONS | EFFICIENCY_ADDITIONS
PATCH_CHANGES = {
    'shadow_drain.py',
    'shadow_service_probe.py', 'panel/sources.py', 'panel/projection_service.py',
    'panel/projection_worker.py', 'panel/review.py', 'panel/authority_reader.py',
    'panel/verification_service.py', 'panel/shadow_source_wait.py', 'url_selected_source_basis.py',
} | ACCESS_PATH_CHANGES | MARKET_OPEN_CHANGES | RECOVERY_CHANGES | EFFICIENCY_CHANGES
OPERATIONAL_CHANGES = {
    'automation/service.py', 'automation_recovery.py', 'automation_resilience.py',
    'automation_runtime.py', 'panel/app.py', 'panel/authority_reader.py', 'panel/model.py',
    'panel/observer_codec.py', 'panel/overview.py', 'panel/presentation.py', 'panel/pwa.py',
    'panel/read_projection.py', 'panel/render.py', 'panel/styles.py',
    'panel/review.py', 'panel/verification_service.py', 'url_selected_source_basis.py',
} | (PATCH_CHANGES - OPERATIONAL_ADDITIONS) | (COORDINATION_CHANGES - OPERATIONAL_ADDITIONS)


def test_sealed_successor_and_all_original_witnesses_have_exact_bytes():
    assert basis.PROFILE_SHA256 != '0' * 64
    actual = _actual()
    before = deepcopy(actual)
    profile = basis._profile()
    predecessor = basis.predecessor_view(actual)
    assert predecessor is not actual
    assert actual == before
    assert len(predecessor) == 422
    assert admission.source_closure(predecessor) == basis.BASE_SOURCE_SHA256
    assert predecessor == profile['base_files']
    assert profile['authority_effect'] == 'NONE'
    assert set(profile['retained_predecessors']) == set(basis.RETAINED_PREDECESSORS)
    for revision, (count, sha) in basis.RETAINED_PREDECESSORS.items():
        retained = profile['retained_predecessors'][revision]
        assert len(retained['files']) == count
        assert admission.source_closure(retained['files']) == sha
    assert structural.historical_view(actual) is actual
    historical = structural.historical_view(predecessor)
    assert len(historical) == 364
    assert admission.source_closure(historical) == (
        '56890ee50268961357faf2f6a8c2dc66ca76eb74c7440c832ba3a7bd06a09e15')
    assert len(transition_registry.load().profiles) == 20


def _all_unknown_sources_refuse():
    actual = _actual()
    for name in actual:
        changed = {**actual, name: hashlib.sha256((actual[name] + 'foreign').encode()).hexdigest()}
        assert basis.predecessor_view(changed) is changed, name
    for name in actual:
        missing = {key: value for key, value in actual.items() if key != name}
        assert basis.predecessor_view(missing) is missing, name
    extra = {**actual, 'execution/unknown.py': 'f' * 64}
    assert basis.predecessor_view(extra) is extra


def test_every_tampered_missing_or_extra_current_file_keeps_actual_identity():
    _all_unknown_sources_refuse()


def test_complete_source_guard_has_a_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.predecessor_view)
    needle = 'if actual != expected:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), 'open-source-successor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'predecessor_view', namespace['predecessor_view'])
    with pytest.raises(AssertionError):
        _all_unknown_sources_refuse()


def test_missing_seal_grants_no_compatibility(monkeypatch):
    actual = _actual()
    monkeypatch.setattr(basis, 'PROFILE_SHA256', '0' * 64)
    assert basis.predecessor_view(actual) is actual


def test_installed_pr561_predecessor_is_exact_and_never_rewritten():
    profile = basis._profile()
    previous = profile['retained_predecessors'][basis.REVIEWED_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    assert len(previous) == 434
    assert admission.source_closure(previous) == (
        'a8b6cce6e00654f402fd74735b66e0711331c44b3ea171e0241a40230b4096a4')
    assert basis.predecessor_view(_actual(), previous=previous) == previous == saved
    assert basis.predecessor_view({**_actual(), 'unknown.py': 'f'*64}, previous=previous) != previous
    changed = {**previous, 'automation_supervisor.py': 'f'*64}
    assert basis.predecessor_view(_actual(), previous=changed) != changed


def test_installed_pr563_source_and_economic_history_are_preserved():
    profile=basis._profile()
    previous=profile['retained_predecessors'][basis.INSTALLED_PREDECESSOR_REVISION]['files']
    assert len(previous)==434
    assert admission.source_closure(previous)=='85165e291f835307e86d45a1c678d44529ce42d1d46713614147c676ade7c47b'
    assert basis.predecessor_view(_actual(),previous=previous)==previous
    assert basis.predecessor_view({**_actual(),'unknown.py':'f'*64},previous=previous)!=previous


def test_installed_pr564_source_is_exact_while_complete_repair_changes_are_sealed():
    previous = basis._profile()['retained_predecessors'][basis.DASHBOARD_PREDECESSOR_REVISION]['files']
    assert len(previous) == 440
    assert admission.source_closure(previous) == 'a84f981e687970d230b197025a0b4260e9587aaf6381a7ecc64022761cfa02fa'
    assert basis.predecessor_view(_actual(), previous=previous) == previous
    for key in ('panel/review_migration.py', 'panel/review_coverage_recovery.py'):
        changed = {**_actual(), key: 'f' * 64}
        assert basis.predecessor_view(changed, previous=previous) is changed


def test_installed_pr565_source_is_exact_and_only_reviewed_modules_change():
    profile = basis._profile()
    previous = profile['retained_predecessors'][basis.PAPER_RELEASE_PREDECESSOR_REVISION]['files']
    assert len(previous) == 442
    assert admission.source_closure(previous) == (
        '95b41c4029df447215be2f04bcce5a25c7a4fe629e130cc37a673badc22cedca')
    actual = _actual()
    assert set(actual) - set(previous) == OPERATIONAL_ADDITIONS
    assert set(previous) <= set(actual)
    assert basis.predecessor_view(actual, previous=previous) == previous
    assert {name for name in previous if actual[name] != previous[name]} == {
        'automation/service.py', 'panel/app.py', 'panel/intent_memo.py', 'panel/model.py',
        'panel/presentation.py', 'panel/pwa.py', 'panel/render.py', 'panel/review.py',
        'panel/retry_status.py', 'paper_plan_preview.py', 'url_selected_source_basis.py',
        'panel/authority_reader.py', 'panel/sources.py', 'panel/verification_service.py',
    } | OPERATIONAL_CHANGES


def test_installed_main_verifier_predecessor_has_only_the_exact_display_successor():
    previous = basis._profile()['retained_predecessors'][basis.VERIFIER_PREDECESSOR_REVISION]['files']
    assert len(previous) == 442
    assert admission.source_closure(previous) == (
        'db2228d6def65283cb75ac3da8f3250a99fb3f180600f9fd9e52b46cf6da0ee8')
    actual = _actual()
    assert set(actual) - set(previous) == OPERATIONAL_ADDITIONS
    assert set(previous) <= set(actual)
    assert {name for name in previous if actual[name] != previous[name]} == {
        'panel/authority_reader.py', 'panel/sources.py', 'panel/verification_service.py',
        'url_selected_source_basis.py'} | OPERATIONAL_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous
    for name in actual:
        changed = {**actual, name: 'f'*64}
        assert basis.predecessor_view(changed, previous=previous) is changed


def test_installed_pr567_remains_exact_for_the_complete_operational_successor():
    previous = basis._profile()['retained_predecessors'][basis.OPERATIONAL_PREDECESSOR_REVISION]['files']
    assert len(previous) == 442
    assert admission.source_closure(previous) == '18de9f4c50f1695aeaa11cdc59081267ab1274f318ab9abc3e470a568ad48e42'
    actual = _actual()
    assert set(actual) - set(previous) == OPERATIONAL_ADDITIONS
    assert set(previous) <= set(actual)
    assert {name for name in previous if actual[name] != previous[name]} == OPERATIONAL_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous


def test_installed_pr568_is_independently_pinned_and_only_exact_probe_patch_changes():
    previous = basis._profile()['retained_predecessors'][basis.PATCH_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    assert len(previous) == 451
    assert admission.source_closure(previous) == 'ea3e4e163241a2075bf5b49fa965b384e65bf2f8456a7e346e0fe8bba38978f8'
    actual = _actual()
    assert set(actual) == set(previous) | ACCESS_PATH_ADDITIONS | CASH_ADDITIONS | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == PATCH_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_installed_local_probe_candidate_is_pinned_without_replacing_its_bytes():
    previous = basis._profile()['retained_predecessors'][basis.LOCAL_PROBE_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    assert len(previous) == 451
    assert admission.source_closure(previous) == '2778b44660897768e9f808e4f26ac16847e158feba06f3b5187a3ab9defb8552'
    actual = _actual()
    assert set(actual) == set(previous) | ACCESS_PATH_ADDITIONS | CASH_ADDITIONS | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == PATCH_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_installed_reusable_observer_is_retained_for_exact_root_cause_corrections():
    previous = basis._profile()['retained_predecessors'][basis.PREPARATION_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    assert len(previous) == 451
    assert admission.source_closure(previous) == '9888f64b30c02da6b06091c52a6961d91282a5473142cdf4519b865bc6459f46'
    actual = _actual()
    assert set(actual) == set(previous) | ACCESS_PATH_ADDITIONS | CASH_ADDITIONS | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == {
        'panel/shadow_source_wait.py', 'panel/projection_service.py',
        'panel/sources.py',
        'shadow_drain.py', 'url_selected_source_basis.py'} | ACCESS_PATH_CHANGES | MARKET_OPEN_CHANGES | RECOVERY_CHANGES | STARTUP_CHANGES | EFFICIENCY_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_installed_checkpoint_access_runtime_has_only_reviewed_drain_and_display_changes():
    previous = basis._profile()['retained_predecessors'][basis.CHECKPOINT_ACCESS_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    assert len(previous) == 453
    assert admission.source_closure(previous) == 'f4eaa5729cee9c2ce5794e4fa334c945dbf2ab2cadd55a77aa35a8b1abe61121'
    actual = _actual()
    assert set(actual) == set(previous) | {'panel/feed_display.py'} | CASH_ADDITIONS | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == {
        'shadow_drain.py', 'url_selected_source_basis.py', 'panel/sources.py'} | MARKET_OPEN_CHANGES | RECOVERY_CHANGES | STARTUP_CHANGES | EFFICIENCY_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_running_feed_display_source_is_retained_without_claiming_completed_installation():
    previous = basis._profile()['retained_predecessors'][basis.FEED_DISPLAY_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    assert len(previous) == 454
    assert admission.source_closure(previous) == 'c3eb52854101901c854cdf84b944ba5e0abcb0e077824ded15ca714b10161eab'
    actual = _actual()
    assert set(actual) == set(previous) | CASH_ADDITIONS | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == MARKET_OPEN_CHANGES | RECOVERY_CHANGES | STARTUP_CHANGES | EFFICIENCY_CHANGES | FEED_EVIDENCE_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_installed_pr570_is_preserved_and_only_coherent_worker_collection_changes():
    previous = basis._profile()['retained_predecessors'][basis.STARTUP_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    actual = _actual()
    assert len(previous) == 455
    assert admission.source_closure(previous) == '5470089498b2e6341865fd5483732c07f347e0019de71376dfdbbc8b2121c344'
    assert set(actual) == set(previous) | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == {
        'shadow_service_probe.py', 'url_selected_source_basis.py'} | EFFICIENCY_CHANGES | FEED_EVIDENCE_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_installed_pr572_and_every_original_predecessor_are_preserved():
    previous = basis._profile()['retained_predecessors'][basis.EFFICIENCY_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    actual = _actual()
    assert len(previous) == 455
    assert admission.source_closure(previous) == 'abe9a2628cc3d46e43a73e9b811e5855c89f3af74619aca87fd765402c8bfc95'
    assert set(actual) == set(previous) | EFFICIENCY_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == EFFICIENCY_CHANGES | FEED_EVIDENCE_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved


def test_installed_pr573_archive_is_exact_and_only_diagnostics_change():
    profile = basis._profile()
    previous = profile['retained_predecessors'][basis.DIAGNOSTIC_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    actual = _actual()
    assert basis.DIAGNOSTIC_PREDECESSOR_REVISION == '8fafcfae9c46f471a834d7bd221497d6d940732a'
    assert len(previous) == 456
    assert admission.source_closure(previous) == (
        '92dcbcf6559efb0d19476438dae0a653850d44afc7bb7dc7b69294b38f5035b5')
    assert previous['url_selected_source_basis.py'] == (
        '702439463966cfaa06d5eca2837d716b1204eb61a09b432b3967c1e2229bfeae')
    assert set(actual) == set(previous) | READ_COST_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == DIAGNOSTIC_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved
    assert profile['authority_effect'] == 'NONE'


def test_each_diagnostic_module_change_or_removal_keeps_actual_identity():
    actual = _actual()
    previous = basis._profile()['retained_predecessors'][basis.DIAGNOSTIC_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    for name in DIAGNOSTIC_CHANGES | READ_COST_ADDITIONS:
        changed = {**actual, name: 'f' * 64}
        assert basis.predecessor_view(changed, previous=previous) is changed, name
        missing = {key: digest for key, digest in actual.items() if key != name}
        assert basis.predecessor_view(missing, previous=previous) is missing, name
    extra = {**actual, 'unreviewed_diagnostic.py': 'f' * 64}
    assert basis.predecessor_view(extra, previous=previous) is extra
    assert previous == saved


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_installed_pr573(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.DIAGNOSTIC_PREDECESSOR_REVISION]
    if defect == 'changed': prior['files']['supervisor_io.py'] = 'f' * 64
    elif defect == 'missing': prior['files'].pop('supervisor_io.py')
    elif defect == 'extra': prior['files']['unreviewed.py'] = 'f' * 64
    else: prior['files']['url_selected_source_basis.py'] = 'f' * 64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path/'changed-diagnostic-predecessor.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


def test_diagnostic_predecessor_independent_pin_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    prior = deepcopy(basis._profile()['retained_predecessors'][basis.DIAGNOSTIC_PREDECESSOR_REVISION])
    prior['files']['supervisor_io.py'] = 'f' * 64
    # Deliberately replace the independent expected pin with the tampered map's
    # self-consistent closure. The re-pinning rejection assertion must then fail.
    monkeypatch.setitem(basis.RETAINED_PREDECESSORS, basis.DIAGNOSTIC_PREDECESSOR_REVISION,
                        (len(prior['files']), basis._closure(prior['files'])))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_repinning_cannot_replace_installed_pr573(tmp_path, monkeypatch, 'changed')


def test_installed_diagnostic_release_has_exact_complete_original_source():
    profile = basis._profile()
    previous = profile['retained_predecessors'][basis.ROOT_CAUSE_PREDECESSOR_REVISION]['files']
    saved = deepcopy(previous)
    actual = _actual()
    assert basis.ROOT_CAUSE_PREDECESSOR_REVISION == 'ba05fe76950fe6d976e08edaadfd88a9e39dec0e'
    assert len(previous) == 456
    assert admission.source_closure(previous) == (
        '7706a3683dbee27c684291f520517f2e6f2447f3de4662dbd9b7b3b111692929')
    assert previous['url_selected_source_basis.py'] == (
        'c82dc2c6dbb1e57cf5c4964cb46f635d50010a25b33b7dec672a3b8d59ec98c6')
    assert set(actual) == set(previous) | READ_COST_ADDITIONS
    assert {name for name in previous if actual[name] != previous[name]} == ROOT_CAUSE_CHANGES
    assert basis.predecessor_view(actual, previous=previous) == previous == saved
    assert len(profile['retained_predecessors']) == 23
    assert profile['authority_effect'] == 'NONE'


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_installed_diagnostic_release(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.ROOT_CAUSE_PREDECESSOR_REVISION]
    if defect == 'changed':
        prior['files']['shadow_health_projection.py'] = 'f' * 64
    elif defect == 'missing':
        prior['files'].pop('shadow_health_projection.py')
    elif defect == 'extra':
        prior['files']['unreviewed.py'] = 'f' * 64
    else:
        prior['files']['url_selected_source_basis.py'] = 'f' * 64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path / 'changed-root-cause-predecessor.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


def test_root_cause_predecessor_independent_pin_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    prior = deepcopy(basis._profile()['retained_predecessors'][basis.ROOT_CAUSE_PREDECESSOR_REVISION])
    prior['files']['shadow_health_projection.py'] = 'f' * 64
    monkeypatch.setitem(basis.RETAINED_PREDECESSORS, basis.ROOT_CAUSE_PREDECESSOR_REVISION,
                        (len(prior['files']), basis._closure(prior['files'])))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_repinning_cannot_replace_installed_diagnostic_release(tmp_path, monkeypatch, 'changed')


@pytest.mark.parametrize('revision', [basis.STARTUP_PREDECESSOR_REVISION,
                                      basis.EFFICIENCY_PREDECESSOR_REVISION])
@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_installed_pr570_or_pr572(tmp_path, monkeypatch, defect, revision):
    value = expanded_profile()
    prior = value['retained_predecessors'][revision]
    if defect == 'changed': prior['files']['shadow_service_probe.py'] = 'f'*64
    elif defect == 'missing': prior['files'].pop('shadow_service_probe.py')
    elif defect == 'extra': prior['files']['unknown.py'] = 'f'*64
    else: prior['files']['url_selected_source_basis.py'] = 'f'*64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path/'changed-startup-predecessor.json'; path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_running_feed_display_source(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.FEED_DISPLAY_PREDECESSOR_REVISION]
    if defect == 'changed': prior['files']['panel/feed_display.py'] = 'f' * 64
    elif defect == 'missing': prior['files'].pop('panel/feed_display.py')
    elif defect == 'extra': prior['files']['unknown.py'] = 'f' * 64
    else: prior['files']['url_selected_source_basis.py'] = 'f' * 64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path/'changed-feed-display-predecessor.json'; path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_installed_operational_predecessor(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.OPERATIONAL_PREDECESSOR_REVISION]
    if defect == 'changed': prior['files']['panel/verification_service.py'] = 'f'*64
    elif defect == 'missing': prior['files'].pop('panel/verification_service.py')
    elif defect == 'extra': prior['files']['unknown.py'] = 'f'*64
    else: prior['files']['url_selected_source_basis.py'] = 'f'*64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path/'changed-operational-predecessor.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_installed_main_verifier_source(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.VERIFIER_PREDECESSOR_REVISION]
    if defect == 'changed': prior['files']['panel/sources.py'] = 'f'*64
    elif defect == 'missing': prior['files'].pop('panel/sources.py')
    elif defect == 'extra': prior['files']['unknown.py'] = 'f'*64
    else: prior['files']['url_selected_source_basis.py'] = 'f'*64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path/'changed-verifier-predecessor.json'; path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_cannot_replace_installed_pr564(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.DASHBOARD_PREDECESSOR_REVISION]
    if defect == 'changed': prior['files']['panel/review_schema.py'] = 'f' * 64
    elif defect == 'missing': prior['files'].pop('panel/review_schema.py')
    elif defect == 'extra': prior['files']['unknown.py'] = 'f' * 64
    else: prior['files']['url_selected_source_basis.py'] = 'f' * 64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path / 'changed-dashboard-predecessor.json'; path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(), previous=prior['files'])


@pytest.mark.parametrize('defect',['changed','missing','extra','checker'])
def test_repinning_cannot_replace_the_installed_pr563_predecessor(tmp_path,monkeypatch,defect):
    value=expanded_profile()
    prior=value['retained_predecessors'][basis.INSTALLED_PREDECESSOR_REVISION]
    if defect=='changed':prior['files']['automation_supervisor.py']='f'*64
    elif defect=='missing':prior['files'].pop('automation_supervisor.py')
    elif defect=='extra':prior['files']['unknown.py']='f'*64
    else:prior['files']['url_selected_source_basis.py']='f'*64
    prior['source_sha256']=basis._closure(prior['files'])
    raw=encoded_profile(value)
    path=tmp_path/'changed-profile.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path)
    monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):
        basis.predecessor_view(_actual(),previous=prior['files'])


@pytest.mark.parametrize('defect', ['changed', 'missing', 'extra', 'checker'])
def test_repinning_profile_cannot_replace_installed_pr561_source(tmp_path, monkeypatch, defect):
    value = expanded_profile()
    prior = value['retained_predecessors'][basis.REVIEWED_PREDECESSOR_REVISION]
    if defect == 'changed':
        prior['files']['automation_supervisor.py'] = 'f'*64
    elif defect == 'missing':
        prior['files'].pop('automation_supervisor.py')
    elif defect == 'extra':
        prior['files']['unknown.py'] = 'f'*64
    else:
        prior['files']['url_selected_source_basis.py'] = 'f'*64
    prior['source_sha256'] = basis._closure(prior['files'])
    raw = encoded_profile(value)
    path = tmp_path/'foreign-profile.json';path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis._profile()


def test_changed_checker_or_original_structural_witness_refuses(tmp_path, monkeypatch):
    checker = tmp_path / 'url_selected_source_basis.py'
    checker.write_bytes(Path(basis.__file__).read_bytes() + b'\n# unknown checker bytes\n')
    with monkeypatch.context() as changed:
        changed.setattr(basis, '__file__', str(checker))
        with pytest.raises(ValueError, match='URL_SOURCE_PROFILE_SHAPE_CHANGED'):
            basis._profile()
    witness = tmp_path / 'structural-refactor-transition.json'
    witness.write_bytes(structural.TRANSITION.read_bytes() + b' ')
    monkeypatch.setattr(structural, 'TRANSITION', witness)
    with pytest.raises(ValueError, match='STRUCTURAL_TRANSITION_PROFILE_CHANGED'):
        basis._profile()


@pytest.mark.parametrize('defect', ['raw_bytes', 'authority', 'base_revision',
    'base_hash', 'base_neighbor', 'base_missing', 'base_extra', 'self_pin',
    'path', 'module', 'structural', 'retained_revision', 'retained_hash',
    'retained_neighbor', 'retained_missing', 'retained_extra'])
def test_changed_or_supplied_profile_digest_cannot_widen_independent_policy(
        tmp_path, monkeypatch, defect):
    raw = basis.PROFILE.read_bytes()
    value = expanded_profile()
    if defect == 'raw_bytes':
        changed = raw + b' '
    else:
        if defect == 'authority':
            value['authority_effect'] = 'LIVE'
        elif defect == 'base_revision':
            value['base_revision'] = 'f' * 40
        elif defect == 'base_hash':
            value['base_source_sha256'] = 'f' * 64
        elif defect == 'base_neighbor':
            value['base_files']['core/decision.py'] = 'f' * 64
        elif defect == 'base_missing':
            value['base_files'].pop('core/decision.py')
        elif defect == 'base_extra':
            value['base_files']['unknown.py'] = 'f' * 64
        elif defect == 'self_pin':
            value['candidate_files']['url_selected_source_basis.py'] = 'f' * 64
        elif defect == 'path':
            value['candidate_files']['../unknown.py'] = 'f' * 64
        elif defect == 'module':
            value['module_sha256'] = 'f' * 64
        elif defect == 'structural':
            value['structural_profile_sha256'] = 'f' * 64
        elif defect == 'retained_revision':
            value['retained_predecessors']['f' * 40] = value['retained_predecessors'].pop(basis.RETAINED_REVISION)
        else:
            retained = value['retained_predecessors'][basis.RETAINED_REVISION]
            if defect == 'retained_hash':
                retained['source_sha256'] = 'f' * 64
            elif defect == 'retained_neighbor':
                retained['files']['core/decision.py'] = 'f' * 64
            elif defect == 'retained_missing':
                retained['files'].pop('core/decision.py')
            else:
                retained['files']['unknown.py'] = 'f' * 64
        changed = encoded_profile(value)
        monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(changed).hexdigest())
    path = tmp_path / 'changed-profile.json'
    path.write_bytes(changed)
    monkeypatch.setattr(basis, 'PROFILE', path)
    with pytest.raises(ValueError, match='URL_SOURCE_'):
        basis._profile()


def test_no_authority_effect_guard_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(basis._profile)
    needle = "value['authority_effect'] != 'NONE'"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'authority-effect-successor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_changed_or_supplied_profile_digest_cannot_widen_independent_policy(
            tmp_path, monkeypatch, 'authority')


def test_retained_predecessor_hash_guard_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(basis._profile)
    needle = "_validated_closure(record['files']) != expected_sha"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'open-retained-predecessor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_changed_or_supplied_profile_digest_cannot_widen_independent_policy(
            tmp_path, monkeypatch, 'retained_neighbor')


@pytest.mark.parametrize('revision', sorted(basis.RETAINED_PREDECESSORS))
def test_exact_predecessor_pair_is_the_only_new_registry_edge(revision):
    actual = _actual()
    predecessor = basis.predecessor_view(actual)
    registry = transition_registry.load()
    assert registry.closure_allowed(predecessor, actual, admission.ADDITIONS)
    assert transition_registry.historical_view(predecessor, actual) == predecessor
    for changed in ({**predecessor, 'unknown.py': 'f' * 64},
                    {**predecessor, 'core/decision.py': 'f' * 64}):
        assert not registry.closure_allowed(changed, actual, admission.ADDITIONS)
    assert not registry.source_allowed('execution/live_order_policy.py', 'f' * 64,
                                       actual['execution/live_order_policy.py'])
    retained = basis._profile()['retained_predecessors'][revision]['files']
    assert basis.predecessor_view(actual, previous=retained) == retained
    assert registry.closure_allowed(retained, actual, admission.ADDITIONS)
    assert transition_registry.historical_view(retained, actual) == retained
    for changed in ({**retained, 'unknown.py': 'f' * 64},
                    {**retained, 'core/decision.py': 'f' * 64},
                    {name: digest for name, digest in retained.items() if name != 'backup_guard.py'}):
        assert basis.predecessor_view(actual, previous=changed) == predecessor
        assert not registry.closure_allowed(changed, actual, admission.ADDITIONS)
    unknown = {**actual, 'execution/foreign.py': 'f' * 64}
    assert basis.predecessor_view(unknown, previous=retained) is unknown


def test_direct_retained_selection_guard_has_a_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.predecessor_view)
    needle = 'if previous == retained:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if previous is not None:'), 'open-direct-predecessor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'predecessor_view', namespace['predecessor_view'])
    with pytest.raises(AssertionError):
        test_exact_predecessor_pair_is_the_only_new_registry_edge(basis.RETAINED_REVISION)


@pytest.mark.parametrize('predecessor', ['current_main', *sorted(basis.RETAINED_PREDECESSORS)])
def test_exact_current_main_manifest_uses_the_new_edge_without_rewriting_identities(handover, predecessor):
    case = handover
    revision, files = basis.BASE_REVISION, basis.predecessor_view(case.actual)
    if predecessor != 'current_main':
        revision = predecessor
        files = basis._profile()['retained_predecessors'][revision]['files']
    case.manifest = {"schema": "sentinel.retained-source-manifest/1",
        "revision": revision, "files": dict(files),
        "seam_sources": {}}
    _rebind_origin(case)
    before = deepcopy((case.source, case.context, case.checkpoint.model_dump(by_alias=True)))
    assert admission.prove_compatibility(case.manifest, case.checkpoint,
                                        case.context, source=case.source)
    assert (case.source, case.context, case.checkpoint.model_dump(by_alias=True)) == before


def test_backed_owner_scope_keeps_actual_current_identity_and_operating_guards(handover, monkeypatch):
    case = handover
    scope = admission._backed_owner_scope(case.checkpoint.runtime_identity,
                                         case.context, actual=case.actual)
    assert dict(scope.current_files) == case.actual
    assert scope.current_source_sha256 == admission.source_closure(case.actual)
    before = deepcopy((case.source, case.context, case.checkpoint.model_dump(by_alias=True)))
    assert admission.prove_compatibility(case.manifest, case.checkpoint,
                                        case.context, source=case.source)
    assert (case.source, case.context, case.checkpoint.model_dump(by_alias=True)) == before
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    with pytest.raises(admission.Refused, match='OWNER_PAPER_SOURCE_MODE_REQUIRED'):
        admission._backed_owner_scope(case.checkpoint.runtime_identity,
                                     case.context, actual=case.actual)


@pytest.mark.parametrize('revision', sorted(basis.RETAINED_PREDECESSORS))
@pytest.mark.parametrize('defect', ['hash', 'neighbor', 'missing', 'extra', 'absent'])
def test_each_retained_snapshot_requires_its_independent_complete_closure(
        tmp_path, monkeypatch, revision, defect):
    value = expanded_profile()
    record = value['retained_predecessors'][revision]
    if defect == 'hash':
        record['source_sha256'] = 'f' * 64
    elif defect == 'neighbor':
        record['files']['core/decision.py'] = 'f' * 64
    elif defect == 'missing':
        del record['files']['core/decision.py']
    elif defect == 'extra':
        record['files']['unreviewed.py'] = 'f' * 64
    else:
        del value['retained_predecessors'][revision]
    raw = encoded_profile(value)
    path = tmp_path / 'retained-profile.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='URL_SOURCE_RETAINED_PREDECESSOR_CHANGED'):
        basis._profile()


@pytest.mark.parametrize('revision', sorted(basis.RETAINED_PREDECESSORS))
def test_each_retained_closure_guard_has_a_behavioral_falsifier(tmp_path, monkeypatch, revision):
    source = inspect.getsource(basis._profile)
    guard = "_validated_closure(record['files']) != expected_sha"
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'False'), '<removed-retained-closure-guard>', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_each_retained_snapshot_requires_its_independent_complete_closure(
            tmp_path, monkeypatch, revision, 'neighbor')
