"""Bootstrap metadata remains read-only and cannot stand in for financial proof."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_evidence import MODULE, model
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401

bootstrap = importlib.import_module(MODULE.__name__+'.access_path_bootstrap')


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


@pytest.fixture
def make_host(tmp_path, monkeypatch):
    def make(system='123456789'):
        operation = tmp_path/'operation'
        previous = tmp_path/'previous'
        operation.mkdir()
        previous.mkdir()
        state = dict(system=system, ready=True, plan=dict(plan_id='future-plan'))
        proof = dict(plan='future-plan', complete_retained_economic_proof=True)
        old = dict(commit='a'*40, image='sha256:'+'1'*64, postgres={}, system=system)
        candidate = dict(commit='b'*40, image='sha256:'+'2'*64,
            source_identity=dict(source='3'*64, wealth='4'*64, shadow_config='5'*64))
        request = dict(schema=bootstrap.REQUEST_SCHEMA, canonical_proof_phase=bootstrap.PHASE,
            handoff_mode='PRE_OPEN', operation_id='private-bootstrap', predecessor=old,
            candidate=candidate, source='/private/source', deployment='/private/deployment')
        prior_request = dict(candidate={key: old[key] for key in ('commit', 'image')})
        record = dict(stage='VERIFIED', artifacts=dict(canonical_proof=proof,
            successor_proof_sha256=model.digest(proof)))
        receipt = previous/'receipt.json'
        write(receipt, record)
        built = dict(foundation=deepcopy(old), commit=candidate['commit'], image=candidate['image'],
            source_identity=deepcopy(candidate['source_identity']), source=request['source'],
            deployment=request['deployment'], predecessor_receipt=dict(path=str(receipt),
                sha256=bootstrap.sha256_file(receipt)))
        write(operation/'build.json', built)
        metadata = dict(transaction_read_only=True, system_identifier=system,
            operational_installation_sha256='6'*64, access_contract_sha256='7'*64,
            access_installation_sha256=None)
        host = SimpleNamespace(request=request, operation_dir=operation,
            predecessor_receipt=receipt, allow_started_predecessor=False,
            supports_post_schema_access_path=True, state=state, proof=proof,
            record=record, prior_request=prior_request, built=built, metadata=metadata, calls=[])
        host.predecessor_canonical_proof = lambda current: deepcopy(proof) if current == state else None
        host.load_values = lambda: {}
        host.candidate_values = lambda _: dict(SENTINEL_GIT_COMMIT=candidate['commit'], **{
            name: candidate['image'] for name in ('SENTINEL_RUNTIME_IMAGE_DIGEST',
                'SENTINEL_TEST_IMAGE_DIGEST', 'SENTINEL_RUNTIME_IMAGE_REF', 'SENTINEL_LOCAL_PAPER_IMAGE')})
        def compose(values, *args, timeout):
            host.calls.append((deepcopy(values), args, timeout))
            assert args[-2] == bootstrap.PROBE and timeout == 60
            value = deepcopy(host.metadata)
            if args[-1] == 'installed' and value['access_installation_sha256'] is None:
                value['access_installation_sha256'] = '8'*64
            return SimpleNamespace(stdout=json.dumps(value).encode())
        host.compose = compose
        monkeypatch.setattr(bootstrap, 'Journal', lambda folder: SimpleNamespace(
            request=host.prior_request, read=lambda: json.loads((Path(folder)/'receipt.json').read_text())))
        return host
    return make


def repin(host):
    write(host.predecessor_receipt, host.record)
    host.built['predecessor_receipt']['sha256'] = bootstrap.sha256_file(host.predecessor_receipt)
    write(host.operation_dir/'build.json', host.built)


def test_exact_contracts_grant_no_financial_authority(make_host):
    host = make_host()
    contract = bootstrap.preflight(host, host.state, host.proof)
    assert set(contract) == bootstrap.CONTRACT_KEYS
    assert contract['authority_effect'] == 'NONE'
    assert contract['candidate'] == host.request['candidate']
    assert contract['predecessor_proof_sha256'] == model.digest(host.proof)
    assert 'canonical_proof' not in contract and 'verified' not in contract
    installed = bootstrap.post_schema(host, host.state, contract)
    assert set(installed) == {'schema', 'authority_effect', 'request_sha256', 'state_sha256',
        'system_identifier', 'operational_installation_sha256', 'access_contract_sha256',
        'access_installation_sha256'}
    assert installed['schema'] == bootstrap.INSTALLED_SCHEMA and installed['authority_effect'] == 'NONE'
    assert [call[1][-1] for call in host.calls] == ['absent', 'installed']


@pytest.mark.parametrize('change', ['unsupported_host', 'ordinary_schema', 'wrong_phase', 'post_trade'])
def test_only_explicit_backed_pre_open_bootstrap_is_admitted(make_host, change):
    host = make_host()
    if change == 'unsupported_host':
        host.supports_post_schema_access_path = False
    else:
        key, value = {'ordinary_schema': ('schema', 'sentinel.local-paper-delivery/3'),
            'wrong_phase': ('canonical_proof_phase', 'PRE_DRAIN'),
            'post_trade': ('handoff_mode', 'POST_TRADE')}[change]
        host.request[key] = value
    with pytest.raises(model.DeliveryRefused, match='ACCESS_BOOTSTRAP_NOT_SELECTED'):
        bootstrap.preflight(host, host.state, host.proof)
    assert host.calls == []


@pytest.mark.parametrize('change', ['stage', 'host_started', 'anchor_started', 'proof',
    'proof_digest', 'derivation', 'anchor', 'runtime', 'build'])
def test_predecessor_anchor_stage_and_complete_proof_are_not_replaceable(make_host, change):
    host = make_host()
    if change == 'stage': host.record['stage'] = 'APPLICATIONS_STARTED'
    elif change == 'host_started': host.allow_started_predecessor = True
    elif change == 'anchor_started': host.built['predecessor_receipt']['allow_started'] = True
    elif change == 'proof': host.record['artifacts']['canonical_proof'] = {'different': True}
    elif change == 'proof_digest': host.record['artifacts']['successor_proof_sha256'] = 'f'*64
    elif change == 'derivation': host.predecessor_canonical_proof = lambda _: None
    elif change == 'runtime': host.prior_request['candidate']['image'] = 'sha256:'+'f'*64
    elif change == 'build': host.built['source_identity']['source'] = 'f'*64
    repin(host)
    if change == 'anchor': host.predecessor_receipt.write_text('{}')
    with pytest.raises(model.DeliveryRefused):
        bootstrap.preflight(host, host.state, host.proof)
    assert not host.calls


@pytest.mark.parametrize('retained', [None, {}, [], {'different': True}])
def test_missing_or_different_retained_proof_cannot_be_created_here(make_host, retained):
    host = make_host()
    with pytest.raises(model.DeliveryRefused):
        bootstrap.preflight(host, host.state, retained)
    assert not host.calls


@pytest.mark.parametrize('change', ['state', 'request', 'candidate', 'extra', 'authority'])
def test_post_schema_contract_stays_bound_to_request_and_preserved_state(make_host, change):
    host = make_host()
    contract = bootstrap.preflight(host, host.state, host.proof)
    if change == 'state': state = {**host.state, 'ready': False}
    else:
        state = host.state
        if change == 'request': host.request['operation_id'] = 'other-operation'
        elif change == 'candidate': contract['candidate']['image'] = 'sha256:'+'f'*64
        elif change == 'extra': contract['canonical_proof'] = host.proof
        elif change == 'authority': contract['authority_effect'] = 'PASS'
    with pytest.raises(model.DeliveryRefused, match='ACCESS_BOOTSTRAP_CONTRACT_CHANGED'):
        bootstrap.post_schema(host, state, contract)
    assert len(host.calls) == 1


@pytest.mark.parametrize('key', ['system_identifier', 'operational_installation_sha256', 'access_contract_sha256'])
def test_installed_metadata_must_preserve_original_system_marker_and_ddl(make_host, key):
    host = make_host()
    contract = bootstrap.preflight(host, host.state, host.proof)
    host.metadata[key] = '9' if key == 'system_identifier' else 'f'*64
    with pytest.raises(model.DeliveryRefused, match='ACCESS_BOOTSTRAP_INSTALLATION_CHANGED'):
        bootstrap.post_schema(host, host.state, contract)


def test_removing_original_marker_comparison_is_detected(make_host, monkeypatch):
    real = bootstrap.require
    monkeypatch.setattr(bootstrap, 'require', lambda value, code: None
        if code == 'ACCESS_BOOTSTRAP_INSTALLATION_CHANGED' else real(value, code))
    with pytest.raises(pytest.fail.Exception):
        test_installed_metadata_must_preserve_original_system_marker_and_ddl(make_host,
            'operational_installation_sha256')


def execute_probe(monkeypatch, dsn, *, installed, code=None):
    monkeypatch.setenv('SENTINEL_DATABASE_URL', dsn)
    monkeypatch.setattr(sys, 'argv', ['thin-probe', 'installed' if installed else 'absent'])
    printed = []
    exec(compile(bootstrap.PROBE if code is None else code, 'actual bootstrap metadata probe', 'exec'),
         {'print': printed.append})
    assert len(printed) == 1
    return json.loads(printed[0])


@pytest.fixture
def predecessor(conn, monkeypatch):
    from sentinel import checkpoint_lineage_access as access, operational_schema
    registry = operational_schema.ACCESS_PATH_COMPONENTS
    try:
        operational_schema.ACCESS_PATH_COMPONENTS = ()
        original = operational_schema.install_quiescent(conn)
    finally:
        operational_schema.ACCESS_PATH_COMPONENTS = registry
    assert access.installation(conn, required=False) is None
    conn.rollback()
    return original


def test_actual_private_metadata_probe_before_and_after_real_additive_migration(conn, predecessor, monkeypatch, make_host):
    from sentinel import checkpoint_lineage_access as access, operational_schema, rolling_daily_checkpoint
    monkeypatch.setattr(access, 'find_foreign', lambda *a, **k: pytest.fail('thin probe scanned lineage'))
    monkeypatch.setattr(rolling_daily_checkpoint, 'load', lambda *a, **k: pytest.fail('thin probe replayed book'))
    system = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
    conn.rollback()
    host = make_host(system)
    def compose(values, *args, timeout):
        host.calls.append((deepcopy(values), args, timeout))
        assert args[-2] == bootstrap.PROBE and timeout == 60
        value = execute_probe(monkeypatch, conn.info.dsn, installed=args[-1] == 'installed')
        return SimpleNamespace(stdout=json.dumps(value).encode())
    host.compose = compose
    contract = bootstrap.preflight(host, host.state, host.proof)
    assert contract['operational_installation_sha256'] == model.digest(predecessor)
    assert contract['authority_effect'] == 'NONE'
    assert operational_schema.install_quiescent(conn) == predecessor
    after = bootstrap.post_schema(host, host.state, contract)
    assert after['system_identifier'] == contract['system_identifier']
    assert after['operational_installation_sha256'] == contract['operational_installation_sha256']
    assert after['access_contract_sha256'] == contract['access_contract_sha256']
    assert len(after['access_installation_sha256']) == 64
    assert all(call[2] == 60 for call in host.calls)


def expect_installed_refusal(monkeypatch, dsn, *, code=None):
    with pytest.raises(AssertionError, match='ACCESS_COMPONENT_ALREADY_INSTALLED'):
        execute_probe(monkeypatch, dsn, installed=False, code=code)


def test_existing_component_cannot_reenter_absent_phase_and_guard_has_falsifier(conn, predecessor, monkeypatch):
    from sentinel import operational_schema
    operational_schema.install_quiescent(conn)
    expect_installed_refusal(monkeypatch, conn.info.dsn)
    guard="assert installation is None,'ACCESS_COMPONENT_ALREADY_INSTALLED'"
    assert bootstrap.PROBE.count(guard) == 1
    mutant = bootstrap.PROBE.replace(guard, 'assert True')
    with pytest.raises(pytest.fail.Exception):
        expect_installed_refusal(monkeypatch, conn.info.dsn, code=mutant)


def test_partial_access_object_is_not_clean_absence(conn, predecessor, monkeypatch):
    from sentinel import checkpoint_lineage_access as access
    conn.execute(f'CREATE INDEX {access.INDEX} ON sentinel_processed_sessions(cursor_name)')
    conn.commit()
    with pytest.raises(access.AccessPathRefused, match='MARKER_LOST_OR_ORPHANED'):
        execute_probe(monkeypatch, conn.info.dsn, installed=False)


def test_installed_access_hmac_failure_refuses_metadata(conn, predecessor, monkeypatch):
    from psycopg.types.json import Jsonb
    from sentinel import checkpoint_lineage_access as access, operational_schema
    operational_schema.install_quiescent(conn)
    row = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                       (access.CURSOR,)).fetchone()[0]
    row['hmac_sha256'] = 'f'*64
    conn.execute(f'ALTER TABLE sentinel_processed_sessions DISABLE TRIGGER {access.ROW_TRIGGER}')
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s WHERE cursor_name=%s', (Jsonb(row), access.CURSOR))
    conn.execute(f'ALTER TABLE sentinel_processed_sessions ENABLE TRIGGER {access.ROW_TRIGGER}')
    conn.commit()
    with pytest.raises(access.AccessPathRefused, match='AUTHENTICATION_FAILED'):
        execute_probe(monkeypatch, conn.info.dsn, installed=True)
