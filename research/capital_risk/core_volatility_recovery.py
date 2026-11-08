"""One exact failed-review artifact; no finance before independent recovery."""
import gzip
import json
from pathlib import Path
import shutil

from core_volatility_admit import authenticated_payload, digest
from core_volatility_source import need, sha, identity
from full_system_core import hosted
from full_system_benchmark import save
from seal import sha256_file

RUN = 42510840403
HEAD = 'df61c5e75f07d374bfb5c90a91e6a76f51f4205d'
ZIP = 'd6fcae3e66e1f0e35f35b8caec783b5d8347904ac84004c0c47e0d236ef03475'
CIPHER = 'be77c7d3a9d9473d31ef42332526c381e75397a3b7a07dc45ffc42bc78ca080c'
MANIFEST = 'a1e7a1c8186af55fa0a4797a4df99585be911ddd8dd47cde362694a296ed89a7'
CURRENT = 'a18d150fc7136881a641b66fba9a6a52f6b614cdf0b6c298ee67a8a7066d3a52'
CURRENT_FILE = '57d8771b5b78be19a91d842cfd4030ea0415bb2ddbc286a824ef95d7dca6cf1b'
REVIEW_LOG = 'bf2f3d468347066f2087f8478b5ae5a2a6ac85e052fecce8d0b48cdb360109fb'
SUPERSEDED = 'book/pre-event/2018-02-09-2967b3dcf161e9c84bb0551f13e280be6379a60af0775e02ec1582010e285d73.json.gz'
SUPERSEDED_FILE = '5410b1a18163df613dcbc76db5c54674eb5c253cd9fdde169d5094ebcf9f6066'


def extract_evidence(archive, root, key, spec):
    need(spec['run_id'] == RUN and spec['head'] == HEAD and spec['arm'] == 'VOL075'
         and spec['zip_sha256'] == ZIP and spec['encrypted_output']['sha256'] == CIPHER
         and spec['encrypted_output']['manifest_sha256'] == MANIFEST
         and spec['checkpoint_sha256'] == CURRENT and spec['checkpoint_file_sha256'] == CURRENT_FILE
         and spec['status'] == 'WORKER_STOPPED_PREFIX_PRESERVED', 'EXACT_FAILED_REVIEW_EVIDENCE_ONLY')
    root = Path(root)
    manifest, receipt = authenticated_payload(archive, root, key, spec)
    from core_volatility_job import inspect
    for relative, role in (('worker-inspect.json', 'worker'), ('independent-review-stop/worker-inspect.json', 'review')):
        actual = json.loads((root/relative).read_bytes())
        inspect('core-volatility-vol075-'+role+'-'+str(RUN)+'-1', value=actual,
                user=spec['container_user'], maximum=1621, continuation=True, aaap_model=True)
        need(not actual['State']['Running'] and not actual['State']['OOMKilled']
             and actual['State']['ExitCode'] == 1, 'EXACT_FAILED_BUT_POSITIVELY_STOPPED_PROCESS')
    for role in ('worker', 'reviewer'):
        need(receipt[role]['stopped'] and receipt[role]['exit_code'] == 1
             and not receipt[role]['oom_killed'], 'EXACT_FAILED_STOP_RECEIPTS')
    need(sha256_file(root/'independent-review-stop/worker.log') == REVIEW_LOG
         and sha256_file(root/SUPERSEDED) == SUPERSEDED_FILE
         and sha256_file(root/'book/checkpoint.json.gz') == CURRENT_FILE,
         'EXACT_REVIEW_FAILURE_AND_ARCHIVED_GZIP_BYTES')
    cp = json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()))
    need(cp['sha256'] == CURRENT and cp['completed'] == 232 and cp['source_cursor'] == '2018-11-30'
         and cp['sha256'] == digest({k: v for k, v in cp.items() if k != 'sha256'}), 'EXACT_UNADMITTED_CURRENT_CHECKPOINT')
    for stream, spec_ in cp['journals'].items():
        with (root/'book'/(stream+'.jsonl')).open('rb') as f:
            raw = f.read(spec_['bytes'])
        need(len(raw) == spec_['bytes'] and sha(raw) == spec_['prefix_sha256'], 'DIAGNOSTIC_COMMITTED_PREFIX')
    need(sha256_file(root/'source-bindings.json') == spec['source_bindings_sha256'], 'DIAGNOSTIC_SOURCE_COMMITMENT')
    return {'schema': 'research.core-volatility-readonly-evidence/1', 'arm': 'VOL075',
            'whole_cipher_authenticated_before_parsing': True, 'members_verified': len(manifest['members']),
            'checkpoint_sha256': CURRENT, 'completed': 232, 'financial_root_admitted': False,
            'financial_continuation_authorized': False, 'canonical_runtime_executed': False}


def financial_inventory(root):
    book = root/'book'
    names = ['checkpoint.json.gz']+[p.name for p in book.glob('*.jsonl')]
    return {n: {'bytes': (book/n).stat().st_size, 'sha256': sha256_file(book/n)} for n in sorted(names)}


def relocate(root):
    """Only one declared obsolete diagnostic moves; all financial bytes stay."""
    path = root/SUPERSEDED
    need(sha256_file(path) == SUPERSEDED_FILE, 'EXACT_SUPERSEDED_CHECKPOINT_ONLY')
    old = json.loads(gzip.decompress(path.read_bytes()))
    need(old['source_cursor'] == '2018-02-08' and old['completed'] == 27
         and old['journals']['daily']['bytes'] > 1487684, 'OLD_UNCOMMITTED_BRANCH_BEYOND_21_CLOSE_PARENT')
    before = financial_inventory(root)
    destination = root/'lineage/superseded-checkpoints'/ (SUPERSEDED_FILE+'.json.gz')
    destination.parent.mkdir(parents=True)
    need(not destination.exists(), 'NEW_SUPERSEDED_ARCHIVE_DESTINATION')
    shutil.move(str(path), str(destination))
    need(sha256_file(destination) == SUPERSEDED_FILE and financial_inventory(root) == before,
         'ALL_CURRENT_CHECKPOINT_JOURNALS_AND_INTERRUPTED_TAILS_BYTE_IDENTICAL')
    proof = {'original_path': SUPERSEDED, 'stored': destination.relative_to(root).as_posix(),
             'bytes_sha256': SUPERSEDED_FILE, 'original_source_run': RUN,
             'financial_bytes_before_and_after': before, 'financial_sessions_advanced': 0}
    save(root/'lineage/superseded-checkpoint-index.json', proof)
    return proof


def run(previous, arm, maximum):
    hosted()
    need(previous == Path('/previous') and arm == 'VOL075' and maximum == 0, 'READ_ONLY_RECOVERY_MODE_ONLY')
    from core_volatility_worker import copy_parent_book
    binding = json.loads(Path('/out/source-bindings.json').read_bytes())
    need(binding == json.loads((previous/'source-bindings.json').read_bytes())
         and binding['experiment'] == identity('VOL075'), 'EXACT_RECOVERY_PRIVATE_SOURCE')
    copy_parent_book(previous/'book', Path('/out/book'))
    evidence = Path('/out/lineage/original-output-evidence')
    evidence.mkdir(parents=True)
    for item in previous.iterdir():
        if item.name == 'book':
            continue
        if item.is_dir():
            shutil.copytree(item, evidence/item.name)
        else:
            shutil.copyfile(item, evidence/item.name)
    for item in (previous/'book').glob('*.json'):
        target = evidence/'book-status'/item.name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(item, target)
    need(sha256_file(Path('/out/book/checkpoint.json.gz')) == CURRENT_FILE, 'UNCHANGED_RECOVERY_CURRENT_CHECKPOINT')
    relocate(Path('/out'))
    from system_campaign_readonly import review
    review(Path('/out/book'), Path('/out/recovered-prefix-preflight.json'))
    proof = json.loads(Path('/out/recovered-prefix-preflight.json').read_bytes())
    need(proof['counts'] == {'formation': 126, 'daily': 232} and proof['checkpoint_sha256'] == CURRENT,
         'FULL_UNCHANGED_CANONICAL_RECOVERY_REVIEW')
    save(Path('/out/experiment-outcome.json'), dict(completed=232, session='2018-11-30', complete=False,
         financial_sessions_advanced=0, recovered_existing_prefix=True))


def review(previous, evidence, output):
    hosted()
    need(previous == Path('/previous') and evidence == Path('/evidence'), 'EXACT_RECOVERY_REVIEW_MOUNTS')
    index = json.loads((evidence/'lineage/superseded-checkpoint-index.json').read_bytes())
    need(index['original_path'] == SUPERSEDED and index['bytes_sha256'] == SUPERSEDED_FILE
         and sha256_file(previous/SUPERSEDED) == SUPERSEDED_FILE
         and sha256_file(evidence/index['stored']) == SUPERSEDED_FILE
         and not (evidence/SUPERSEDED).exists(), 'INDEPENDENT_EXACT_ARCHIVED_SUPERSEDED_GZIP')
    need(financial_inventory(evidence) == financial_inventory(previous)
         == index['financial_bytes_before_and_after'], 'INDEPENDENT_ALL_FINANCIAL_BYTES_UNCHANGED')
    def checkpoints(root):
        return {p.relative_to(root).as_posix(): sha256_file(p) for p in (root/'book').rglob('*.json.gz')}
    original = checkpoints(previous)
    original.pop(SUPERSEDED)
    need(checkpoints(evidence) == original, 'NO_OTHER_ACTIVE_CHECKPOINT_ADDED_REMOVED_OR_CHANGED')
    from system_campaign_readonly import review as canonical_review
    canonical_review(evidence/'book', output/'core-review.json')
    proof = json.loads((output/'core-review.json').read_bytes())
    need(proof['checkpoint_sha256'] == CURRENT and proof['counts'] == {'formation': 126, 'daily': 232},
         'INDEPENDENT_RECOVERED_PREFIX_COUNTS')
    save(output/'recovery-review.json', dict(passed=True, financial_sessions_advanced=0,
         financial_bytes_unchanged=True, only_declared_superseded_checkpoint_archived=True,
         superseded_index_sha256=sha256_file(evidence/'lineage/superseded-checkpoint-index.json')))
