"""Authenticated inert artifact/stop/checkpoint falsifiers, no financial code."""
import gzip
import json
from pathlib import Path
import zipfile

import pytest
from cryptography.exceptions import InvalidTag

from core_volatility_admit import digest, extract
from core_volatility_source import sha
from core_volatility_continue_job import bounds
from core_volatility_job import require_continuation_stage
from full_system_trials_job import seal
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file


def write(root, name, value):
    p = root/name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes((json.dumps(value, sort_keys=True)+'\n').encode())
    return p


def container(role):
    name = 'core-volatility-control-'+role+'-123-1'
    mounts = ['/variant', '/frozen', '/driver', '/out'] + (['/evidence'] if role == 'review' else [])
    return {'Name': '/'+name, 'Image': EXECUTION_IMAGE, 'Id': 'a'*64,
            'State': {'Running': False, 'OOMKilled': False, 'ExitCode': 0},
            'HostConfig': {'NetworkMode': 'none', 'Memory': 8*1024**3, 'MemorySwap': 8*1024**3,
                          'NanoCpus': 2000000000, 'PidsLimit': 64, 'ReadonlyRootfs': True,
                          'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges']},
            'Config': {'WorkingDir': '/variant', 'User': '1001:1001', 'Env': ['FULL_SYSTEM_HOSTED=1'],
                       'Labels': {'research.study': 'core-volatility-20261108', 'research.role': role},
                       'Entrypoint': ['python'], 'Cmd': ['-B', '-u', '/driver/core_volatility_worker.py',
                           '--mode', 'review' if role == 'review' else 'economic', '--arm', 'CONTROL', '--maximum', '134']},
            'Mounts': [{'Destination': n, 'Type': 'bind', 'RW': n == '/out'} for n in mounts]}


def artifact(tmp_path, monkeypatch, mutation=None):
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_SHA', 'b'*40)
    root = tmp_path/'fixture'
    root.mkdir()
    request = write(root, 'request.json', {'inert_fixture': True})
    journals = {}
    for stream in ('formation', 'daily', 'monthly', 'watch'):
        raw = b'{"inert":true}\n'
        p = root/'book'/(stream+'.jsonl')
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(raw)
        journals[stream] = {'bytes': len(raw), 'prefix_sha256': sha(raw)}
    base, repairs, state = {'inert_fixture': True}, [], {'inert_state': True}
    run = {'state': state, 'state_sha256': digest(state), 'input_sha256': digest({'base': base, 'repairs': repairs})}
    run['checkpoint_sha256'] = digest(run)
    cp = {'completed': 8, 'source_cursor': '2018-01-11', 'journals': journals,
          'base': base, 'repairs': repairs, 'run': run}
    cp['sha256'] = digest(cp)
    (root/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    write(root, 'source-bindings.json', {'inert_binding': True})
    worker, reviewer = container('worker'), container('review')
    if mutation == 'running':
        worker['State']['Running'] = True
    elif mutation == 'writable_input':
        worker['Mounts'][0]['RW'] = True
    elif mutation == 'wrong_entrypoint':
        worker['Config']['Cmd'][-1] = '0'
    elif mutation == 'prefix':
        (root/'book/daily.jsonl').write_bytes(b'{"different":true}\n')
    write(root, 'worker-inspect.json', worker)
    write(root, 'independent-review-stop/worker-inspect.json', reviewer)
    write(root, 'independent-review-stop/core-review.json', {'checkpoint_sha256': cp['sha256'],
          'counts': {'formation': 126, 'daily': 8}, 'all_prefixes_verified': True,
          'all_daily_factors_and_chains_verified': True})
    key = b'K'*32
    cipher = tmp_path/'core-volatility-CONTROL.tar.crseal'
    encrypted = seal(root, cipher, key, request, 'CONTROL', stage='campaign-candidate', protocol_sha256='c'*64)
    if mutation == 'gcm':
        raw = bytearray(cipher.read_bytes())
        raw[25] ^= 1
        cipher.write_bytes(raw)
        encrypted['sha256'] = sha256_file(cipher)
    status = 'PAIRED_ARM_PILOT_REVIEWED_PENDING_ARTIFACT_ADMISSION'
    receipt = {'schema': 'research.core-volatility-receipt/1', 'status': status, 'arm': 'CONTROL',
               'run_id': '123', 'head': 'b'*40, 'request_sha256': sha256_file(request),
               'protocol_sha256': 'c'*64, 'production_contacted': False, 'original_campaign_resumed': False,
               'encrypted_output': encrypted, 'worker': {'stopped': True, 'oom_killed': False, 'exit_code': 0},
               'reviewer': {'stopped': True, 'oom_killed': False, 'exit_code': 0}}
    public = {'core-volatility-receipt.json': (json.dumps(receipt)+'\n').encode(),
              'core-volatility-staging.json': b'{"inert":true}\n',
              'ephemeral-runner-capacity.json': b'{"inert":true}\n'}
    archive = tmp_path/'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for name, raw in public.items():
            z.writestr(name, raw)
        z.write(cipher, cipher.name)
    spec = {'zip_bytes': archive.stat().st_size, 'zip_sha256': sha256_file(archive),
            'public_members': {n: {'bytes': len(raw), 'sha256': sha(raw)} for n, raw in public.items()},
            'encrypted_output': encrypted, 'status': status, 'arm': 'CONTROL', 'run_id': 123, 'head': 'b'*40,
            'request_sha256': receipt['request_sha256'], 'protocol_sha256': 'c'*64,
            'container_user': '1001:1001', 'maximum': 134, 'continuation': False, 'worker_exit_code': 0,
            'checkpoint_file_sha256': sha256_file(root/'book/checkpoint.json.gz'),
            'checkpoint_sha256': cp['sha256'], 'session': cp['source_cursor'], 'completed': 8,
            'source_bindings_sha256': sha256_file(root/'source-bindings.json')}
    return archive, key, spec


def test_full_authentication_and_inner_commitments(tmp_path, monkeypatch):
    archive, key, spec = artifact(tmp_path, monkeypatch)
    proof = extract(archive, tmp_path/'admitted', key, spec)
    assert proof['whole_cipher_authenticated_before_parsing'] and proof['completed'] == 8
    assert proof['canonical_runtime_executed'] is False


@pytest.mark.parametrize('mutation', ('running', 'writable_input', 'wrong_entrypoint', 'prefix', 'gcm'))
def test_authentication_and_actual_parent_falsifiers(tmp_path, monkeypatch, mutation):
    archive, key, spec = artifact(tmp_path, monkeypatch, mutation)
    with pytest.raises((ValueError, InvalidTag)):
        extract(archive, tmp_path/'admitted', key, spec)
    if mutation == 'gcm':
        assert not (tmp_path/'admitted').exists()


def test_foreign_parent_checkpoint_refuses(tmp_path, monkeypatch):
    archive, key, spec = artifact(tmp_path, monkeypatch)
    spec['checkpoint_sha256'] = '0'*64
    with pytest.raises(ValueError, match='REVIEWED_PARENT_CHECKPOINT'):
        extract(archive, tmp_path/'admitted', key, spec)


def test_timing_selects_bounded_segment_and_full_axis():
    def timings(seconds):
        return {arm: {'financial_seconds': seconds*134, 'new_financial_transitions': 134,
                       'warmup_seconds': 100., 'completed': 8} for arm in ('CONTROL', 'VOL075')}
    assert bounds(timings(2.))['maximum'] == 0
    selected = bounds(timings(10.))
    assert 21 <= selected['maximum'] < 2156 and selected['financial_wait_seconds'] == 12600
    with pytest.raises(ValueError, match='ACTUAL_TIMING_VALUES'):
        bounds(timings(float('nan')))


@pytest.mark.parametrize('maximum', (0, 1634))
def test_exact_stage_completion_and_short_prefix_falsifier(maximum):
    request = {'maximum': maximum, 'parents': {'CONTROL': {'completed': 8}}}
    receipt = {'status': ('PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION' if maximum else
                          'COMPLETE_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'),
               'worker': {'exit_code': 0}, 'reviewer': {'exit_code': 0}}
    outcome = {'completed': 1642 if maximum else 2156, 'complete': not maximum, 'session': '2026-07-31'}
    require_continuation_stage(request, receipt, outcome, 'CONTROL')
    outcome['completed'] -= 1
    with pytest.raises(ValueError):
        require_continuation_stage(request, receipt, outcome, 'CONTROL')
    outcome['completed'] += 1
    receipt['worker']['exit_code'] = 143
    with pytest.raises(ValueError, match='SUCCESSFUL_STAGE_STOPS'):
        require_continuation_stage(request, receipt, outcome, 'CONTROL')
