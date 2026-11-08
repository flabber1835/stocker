"""Authenticate stopped experiment artifacts as DATA, never execute a book."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

from core_volatility_source import need, sha
from system_campaign_factual_admit import authenticate, AuthenticatedStream
from seal import sha256_file, safe_name


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii'))


def authenticated_payload(archive, root, key, spec):
    """Transport only: authenticated bytes never confer financial authority."""
    archive, root = Path(archive), Path(root)
    need(not root.exists(), 'NEW_ADMISSION_DIRECTORY')
    need(0 < archive.stat().st_size == spec['zip_bytes'] < 1024**3
         and sha256_file(archive) == spec['zip_sha256'], 'EXACT_ARCHIVE')
    asset = spec['encrypted_output']
    with zipfile.ZipFile(archive) as z:
        public = spec['public_members']
        need(len(z.namelist()) == len(set(z.namelist()))
             and set(z.namelist()) == set(public) | {asset['name']}, 'EXACT_ZIP_MEMBERS')
        for name, expected in public.items():
            safe_name(name)
            need(z.getinfo(name).file_size == expected['bytes'] < 2*1024**2, 'PUBLIC_MEMBER_LENGTH')
            need(sha(z.read(name)) == expected['sha256'], 'PUBLIC_MEMBER_HASH')
        receipt = json.loads(z.read('core-volatility-receipt.json'))
        need(receipt['schema'] == 'research.core-volatility-receipt/1'
             and receipt['status'] == spec['status'] and receipt['arm'] == spec['arm']
             and int(receipt['run_id']) == spec['run_id'] and receipt['head'] == spec['head']
             and receipt['request_sha256'] == spec['request_sha256']
             and receipt['protocol_sha256'] == spec['protocol_sha256']
             and not receipt['production_contacted'] and not receipt['original_campaign_resumed']
             and receipt['encrypted_output'] == asset, 'EXACT_PARENT_RECEIPT')
        need(z.getinfo(asset['name']).file_size == asset['bytes'], 'CIPHER_LENGTH')
        header, tag = authenticate(z, asset, key)
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        with z.open(asset['name']) as source:
            plain = AuthenticatedStream(source, asset, key, header, tag)
            with tarfile.open(fileobj=plain, mode='r|gz') as tar:
                first = tar.next()
                need(first is not None and first.name == 'manifest.json' and first.isfile()
                     and first.size < 2*1024**2, 'FIRST_MANIFEST')
                raw = tar.extractfile(first).read()
                need(sha(raw) == asset['manifest_sha256'], 'MANIFEST_HASH')
                manifest = json.loads(raw)
                need(manifest['schema'] == 'research.full-system-output/1'
                     and manifest['stage'] == 'campaign-candidate' and manifest['arm'] == spec['arm']
                     and int(manifest['run_id']) == spec['run_id'] and manifest['head'] == spec['head']
                     and manifest['request_sha256'] == spec['request_sha256']
                     and manifest['protocol_sha256'] == spec['protocol_sha256']
                     and manifest['compression'] == 'TAR_GZIP_V1', 'MANIFEST_BINDINGS')
                inventory = manifest['members']
                need(0 < len(inventory) < 5000 and sum(v['bytes'] for v in inventory.values()) <= 1024**3,
                     'MANIFEST_BOUNDS')
                seen = set()
                while item := tar.next():
                    name = safe_name(item.name)
                    need(item.isfile() and name in inventory and name not in seen, 'UNIQUE_DECLARED_MEMBER')
                    expected = inventory[name]
                    need(item.size == expected['bytes'], 'MEMBER_LENGTH')
                    target = root/name
                    need(target.resolve().is_relative_to(root.resolve()), 'MEMBER_PATH')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(item) as src, target.open('xb') as out:
                        shutil.copyfileobj(src, out, length=1024**2)
                    need(sha256_file(target) == expected['sha256'], 'MEMBER_HASH')
                    seen.add(name)
                need(seen == set(inventory), 'COMPLETE_INVENTORY')
            while plain.read(1024**2):
                pass
    return manifest, receipt


def extract(archive, root, key, spec):
    """Reviewed financial prefix: all original authority guards stay required."""
    need(not spec.get('control_equivalence', False), 'DIAGNOSTIC_NEVER_FINANCIAL_ROOT')
    need(spec['status'] in ('PAIRED_ARM_PILOT_REVIEWED_PENDING_ARTIFACT_ADMISSION',
                           'COMPLETE_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION',
                           'PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'), 'REVIEWED_STATUS_ONLY')
    root = Path(root)
    asset = spec['encrypted_output']
    manifest, receipt = authenticated_payload(archive, root, key, spec)
    inventory = manifest['members']
    need(receipt['worker']['stopped'] and not receipt['worker']['oom_killed']
         and receipt['worker']['exit_code'] == spec['worker_exit_code']
         and receipt['reviewer']['stopped'] and receipt['reviewer']['exit_code'] == 0
         and not receipt['reviewer']['oom_killed'], 'RECEIPT_POSITIVE_STOPS')
    from core_volatility_job import inspect
    for relative, role in (('worker-inspect.json', 'worker'),
                           ('independent-review-stop/worker-inspect.json', 'review')):
        v = json.loads((root/relative).read_bytes())
        name = 'core-volatility-'+spec['arm'].lower()+'-'+role+'-'+str(spec['run_id'])+'-1'
        inspect(name, value=v, user=spec['container_user'], maximum=spec['maximum'],
                continuation=spec['continuation'], aaap_model=spec.get('aaap_model', False),
                recover_prefix=spec.get('recover_prefix', False), completion_facts=spec.get('completion_facts', False),
                sonc_facts=spec.get('sonc_facts', False), cash_case=spec.get('cash_case'),
                control_replay=spec.get('control_replay', False))
        need(not v['State']['Running'] and not v['State']['OOMKilled']
             and v['State']['ExitCode'] == (spec['worker_exit_code'] if role == 'worker' else 0),
             'ACTUAL_POSITIVE_PARENT_STOP')
    proof = json.loads((root/'independent-review-stop/core-review.json').read_bytes())
    if spec.get('control_replay', False):
        from core_volatility_control_replay import ORIGINAL, PARENT, MODELS
        need(proof.get('common_input_replay_verified') is True and proof.get('diagnostic_book_authority_used') is False
             and proof.get('original_financial_parent_sha256') == ORIGINAL
             and proof.get('selected_financial_parent_sha256') == PARENT
             and proof.get('common_models') == list(MODELS), 'INDEPENDENT_COMMON_INPUT_REPLAY_REVIEW_REQUIRED')
    cp = json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()))
    need(sha256_file(root/'book/checkpoint.json.gz') == spec['checkpoint_file_sha256']
         and cp['sha256'] == spec['checkpoint_sha256'] == proof['checkpoint_sha256']
         and cp['sha256'] == digest({k: v for k, v in cp.items() if k != 'sha256'})
         and cp['source_cursor'] == spec['session'] and cp['completed'] == spec['completed']
         and proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
         and proof['counts'] == {'formation': 126, 'daily': cp['completed']}, 'REVIEWED_PARENT_CHECKPOINT')
    for stream, commitment in cp['journals'].items():
        with (root/'book'/ (stream+'.jsonl')).open('rb') as f:
            raw = f.read(commitment['bytes'])
        need(len(raw) == commitment['bytes'] and sha(raw) == commitment['prefix_sha256'], 'COMMITTED_PARENT_PREFIX')
    run = cp['run']
    need(run['checkpoint_sha256'] == digest({k: v for k, v in run.items() if k != 'checkpoint_sha256'})
         and run['state_sha256'] == digest(run['state'])
         and run['input_sha256'] == digest({'base': cp['base'], 'repairs': cp['repairs']}),
         'INNER_STATE_AND_INPUT_COMMITMENTS')
    need(sha256_file(root/'source-bindings.json') == spec['source_bindings_sha256'], 'PARENT_SOURCE_BINDING')
    return {'schema': 'research.core-volatility-artifact-admission/1', 'arm': spec['arm'],
            'manifest_sha256': asset['manifest_sha256'], 'members_verified': len(inventory),
            'logical_bytes': sum(v['bytes'] for v in inventory.values()),
            'checkpoint_sha256': cp['sha256'], 'completed': cp['completed'],
            'whole_cipher_authenticated_before_parsing': True, 'canonical_runtime_executed': False}


def hosted(spec, root, key, *, extractor=extract):
    from probe import check_context
    check_context(os.environ)
    root = Path(root).resolve()
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    need(os.name == 'posix' and root.parent == temp and root.name.startswith('core-volatility-transfer-')
         and not root.exists() and shutil.disk_usage(temp).free >= 12*1024**3, 'HOSTED_ADMISSION_PATH')
    root.mkdir(mode=0o700)
    archive = root/'parent.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh', 'api', 'repos/flabber1835/stocker/actions/artifacts/'+str(spec['artifact_id'])+'/zip'],
                       stdout=out, check=True, timeout=180)
    proof = extractor(archive, root/'admitted', key, spec)
    (root/'admission.json').write_bytes((json.dumps(proof, sort_keys=True, indent=2)+'\n').encode())
    return root/'admitted'
