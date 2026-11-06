"""Explicit bootstrap selection cannot alter ordinary installation requests."""
from copy import deepcopy

import pytest

from tests.scripts import test_sentinel_local_delivery_cli as fixture

inputs = fixture.inputs
cli, model, qualification = fixture.cli, fixture.model, fixture.qualification


def selected(inputs):
    value = fixture.request(inputs, inputs.approved)
    value.update(schema=model.ACCESS_PATH_SCHEMA,
                 canonical_proof_phase=model.POST_SCHEMA_ACCESS_PATH)
    return value


def test_new_phase_is_explicit_and_journal_keeps_the_existing_stage_order(inputs):
    request = model.validate_request(selected(inputs))
    model.write_new(inputs.folder/'request.json', request)
    journal = model.Journal(inputs.folder)
    assert model.canonical_proof_phase(request) == model.POST_SCHEMA_ACCESS_PATH
    assert journal.stages == model.STAGES and journal.read()['stage'] == 'NEW'
    journal.advance('NEW', 'PREFLIGHT_PASS', predecessor_canonical_proof={'retained': True})
    assert journal.read()['artifacts'] == {'predecessor_canonical_proof': {'retained': True}}
    assert 'canonical_proof' not in journal.read()['artifacts']


@pytest.mark.parametrize('mode', ['POST_TRADE', 'POST_TRADE_SUCCESSOR', 'BLOCKED_UNSENT'])
def test_bootstrap_request_refuses_other_handoff_modes(inputs, mode):
    value = selected(inputs)
    value['handoff_mode'] = mode
    with pytest.raises(model.DeliveryRefused, match='REQUEST_HANDOFF_MODE'):
        model.validate_request(value)


def test_removed_pre_open_request_guard_is_detected(inputs, monkeypatch):
    original = model.require
    monkeypatch.setattr(model, 'require', lambda ok, reason:
        None if reason == 'REQUEST_HANDOFF_MODE' else original(ok, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_bootstrap_request_refuses_other_handoff_modes(inputs, 'POST_TRADE')


@pytest.mark.parametrize('damage', ['missing', 'pre_drain', 'unknown', 'boolean', 'old_schema'])
def test_phase_cannot_be_implicit_unknown_or_added_to_an_old_schema(inputs, damage):
    value = selected(inputs)
    if damage == 'missing':
        value.pop('canonical_proof_phase')
    elif damage == 'old_schema':
        value['schema'] = model.SCHEMA
    else:
        value['canonical_proof_phase'] = {'pre_drain': 'PRE_DRAIN', 'unknown': 'SKIP', 'boolean': True}[damage]
    with pytest.raises(model.DeliveryRefused):
        model.validate_request(value)


def test_ordinary_request_keeps_its_shape_and_pre_drain_phase(inputs):
    value = fixture.request(inputs, inputs.approved)
    before = deepcopy(value)
    assert model.validate_request(value) == before
    assert model.canonical_proof_phase(value) == 'PRE_DRAIN'
    assert 'canonical_proof_phase' not in value


def prepare(inputs, monkeypatch, *, supported):
    fixture.run_build(inputs, monkeypatch)
    class Candidate:
        supports_post_schema_access_path = supported
        def __init__(self, request, folder):
            self.request = request
        def verify_candidate(self):
            assert self.request['schema'] == model.ACCESS_PATH_SCHEMA
    path = inputs.folder/'build.json'
    return cli.prepare(operation_dir=inputs.folder, build_record=path,
        build_sha256=qualification.sha256_file(path), operation_id='explicit-bootstrap',
        host_type=Candidate, canonical_proof_phase=model.POST_SCHEMA_ACCESS_PATH)


def test_prepare_records_selected_phase_in_immutable_request_and_status(inputs, monkeypatch):
    journal = prepare(inputs, monkeypatch, supported=True)
    assert journal.request['canonical_proof_phase'] == model.POST_SCHEMA_ACCESS_PATH
    assert journal.read()['history'] == [] and journal.read()['artifacts'] == {}
    assert cli.status(inputs.folder)['canonical_proof_phase'] == model.POST_SCHEMA_ACCESS_PATH


def test_prepare_refuses_a_host_without_the_backed_capability(inputs, monkeypatch):
    with pytest.raises(model.DeliveryRefused, match='ACCESS_PATH_BOOTSTRAP_REQUIRES_BACKED_PRE_OPEN'):
        prepare(inputs, monkeypatch, supported=False)
    assert not (inputs.folder/'request.json').exists()


def test_removed_prepare_capability_guard_is_detected(inputs, monkeypatch):
    original = cli.require
    monkeypatch.setattr(cli, 'require', lambda ok, reason:
        None if reason == 'ACCESS_PATH_BOOTSTRAP_REQUIRES_BACKED_PRE_OPEN' else original(ok, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_prepare_refuses_a_host_without_the_backed_capability(inputs, monkeypatch)


def test_only_backed_parser_exposes_the_explicit_phase():
    arguments = ['prepare', '--operation-dir', '/tmp/operation', '--build-record', '/tmp/build.json',
                 '--build-sha256', '1'*64, '--operation-id', 'explicit-bootstrap']
    assert cli.parser(backed=True).parse_args(arguments).canonical_proof_phase == 'PRE_DRAIN'
    assert cli.parser(backed=True).parse_args(arguments + [
        '--canonical-proof-phase', model.POST_SCHEMA_ACCESS_PATH]).canonical_proof_phase == model.POST_SCHEMA_ACCESS_PATH
    with pytest.raises(SystemExit):
        cli.parser().parse_args(arguments + ['--canonical-proof-phase', model.POST_SCHEMA_ACCESS_PATH])
