"""A bootstrap receipt retains its complete proof when reused as a predecessor."""
from copy import deepcopy

import pytest

from tests.scripts import test_sentinel_backed_predecessor as fixture
from sentinel_local_delivery import model

patch = fixture.patch
chain = fixture.chain


@pytest.fixture
def access_case(chain):
    chain['request'].update(schema=model.ACCESS_PATH_SCHEMA,
        canonical_proof_phase=model.POST_SCHEMA_ACCESS_PATH)
    return chain


def completed_access_receipt(case, *, final_stage='VERIFIED', damage=None):
    """Build a real digest-linked history, including the post-schema evidence."""
    folder = case['operation']
    request = case['request']
    model.write_new(folder/'request.json', request)
    model.write_new(folder/'build.json', case['built'])
    journal = model.Journal(folder)
    state = dict(system='1234', issuer_evidence=dict(count=0,
        md5=patch.checks.EMPTY_ISSUER_EVIDENCE_MD5))
    proof = dict(plan='unchanged-future-plan', book='unchanged-book', transaction_read_only=True)
    contract = dict(schema='sentinel.checkpoint-access-bootstrap/1', authority_effect='NONE',
        request_sha256=journal.subject, operation_id=request['operation_id'],
        predecessor={key: request['predecessor'][key] for key in ('commit', 'image')},
        candidate=deepcopy(request['candidate']), state_sha256=model.digest(state),
        predecessor_proof_sha256=model.digest(proof), system_identifier=state['system'],
        operational_installation_sha256='c'*64, access_contract_sha256='d'*64)
    installed = dict(schema='sentinel.checkpoint-access-installed/1', authority_effect='NONE',
        **{key: contract[key] for key in ('request_sha256', 'state_sha256', 'system_identifier',
            'operational_installation_sha256', 'access_contract_sha256')},
        access_installation_sha256='e'*64)
    qualification = dict(schema='sentinel.checkpoint-access-canonical-qualification/1',
        authority_effect='NONE', request_sha256=journal.subject, state_sha256=model.digest(state),
        contract_sha256=model.digest(contract), installation=installed,
        canonical_proof_sha256=model.digest(proof), qualified_at='2026-10-26T11:01:00+00:00')
    if damage == 'tampered_completion':
        qualification['installation']['operational_installation_sha256'] = 'f'*64
    actual = deepcopy(proof)
    if damage == 'canonical_proof':
        actual['book'] = 'different-candidate-book'
    for before, after in zip(journal.stages, journal.stages[1:]):
        fields = {}
        if after == 'PREFLIGHT_PASS':
            fields = dict(postgres=case['pg'], preserved=state,
                predecessor_canonical_proof=deepcopy(proof), access_path_canonical_contract=contract,
                native_positions={'native-asset': '17'}, notification_history={key: {} for key in (
                    'alerts', 'delivered_alerts', 'events', 'fanouts', 'recipients', 'delivered_recipients')})
        elif after == 'COMPOSE_INSTALL_REQUESTED':
            fields = dict(canonical_proof=actual)
            if damage != 'missing_completion':
                fields['access_path_canonical_qualification'] = qualification
        elif after == 'SHADOW_VERIFIED':
            # Keep the usual successor digest valid even for a changed candidate
            # proof, so refusal must come from the bootstrap's equality contract.
            fields = dict(successor_proof_sha256=model.digest(actual))
        journal.advance(before, after, **fields)
        if after == final_stage:
            break
    record = journal.read()
    assert record['stage'] == final_stage
    return folder/'receipt.json', state, proof


def retained_host(case, receipt, *, final_stage):
    """Select that exact receipt as the next operation's immutable predecessor."""
    folder = case['operation'].parent/'successor-operation'
    folder.mkdir()
    model.write_new(folder/'build.json', dict(predecessor_receipt=dict(
        path=str(receipt), sha256=patch.sha256_file(receipt))))
    host = object.__new__(patch.BackedHost)
    host.operation_dir = folder
    host.predecessor_receipt = receipt
    host.allow_started_predecessor = final_stage == 'APPLICATIONS_STARTED'
    host.request = dict(predecessor={key: case['request']['candidate'][key]
        for key in ('commit', 'image')})
    return host


@pytest.mark.parametrize('final_stage', ['VERIFIED', 'APPLICATIONS_STARTED'])
def test_complete_bootstrap_receipt_is_a_future_witness_and_exact_retained_proof(access_case, final_stage):
    receipt, state, proof = completed_access_receipt(access_case, final_stage=final_stage)
    witness = patch.predecessor_witness(receipt, allow_started=final_stage == 'APPLICATIONS_STARTED')
    assert witness['git_commit'] == access_case['request']['candidate']['commit']
    assert witness['runtime_image'] == access_case['request']['candidate']['image']
    assert witness['preserved'] == state
    assert witness['unfinished'] is (final_stage == 'APPLICATIONS_STARTED')
    host = retained_host(access_case, receipt, final_stage=final_stage)
    assert host.predecessor_canonical_proof(state) == proof


def assert_consumption_refused(case, *, consumer, final_stage, damage):
    receipt, state, _ = completed_access_receipt(case, final_stage=final_stage, damage=damage)
    # The request, journal history, build and next operation's anchor digest all
    # agree. They cannot replace the selected phase's complete qualification.
    assert model.Journal(case['operation']).read()['stage'] == final_stage
    if consumer == 'witness':
        with pytest.raises(patch.DeliveryRefused, match='ACCESS_PATH_CANONICAL_'):
            patch.predecessor_witness(receipt, allow_started=final_stage == 'APPLICATIONS_STARTED')
    else:
        host = retained_host(case, receipt, final_stage=final_stage)
        with pytest.raises(patch.DeliveryRefused, match='ACCESS_PATH_CANONICAL_'):
            host.predecessor_canonical_proof(state)


@pytest.mark.parametrize('consumer', ['witness', 'retained'])
@pytest.mark.parametrize('final_stage', ['VERIFIED', 'APPLICATIONS_STARTED'])
@pytest.mark.parametrize('damage', ['missing_completion', 'tampered_completion', 'canonical_proof'])
def test_future_consumers_refuse_missing_or_changed_bootstrap_evidence(
        access_case, consumer, final_stage, damage):
    assert_consumption_refused(access_case, consumer=consumer, final_stage=final_stage, damage=damage)


@pytest.mark.parametrize('consumer', ['witness', 'retained'])
def test_removed_receipt_consumer_completion_check_has_executed_falsifier(access_case, monkeypatch, consumer):
    monkeypatch.setattr(patch, '_require_access_path_completion', lambda journal, record: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        assert_consumption_refused(access_case, consumer=consumer, final_stage='VERIFIED',
            damage='missing_completion')
