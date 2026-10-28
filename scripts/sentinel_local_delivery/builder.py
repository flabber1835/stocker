"""Offline source-only images and immutable inputs for local PAPER handoff."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess

from .host import Host
from .model import Journal, REVIEWED_HOST_ARTIFACTS, read_json, require, utcnow, write_new
from .qualification import clean_candidate, git, sha256_file, source_files, validate_report

BUILD_SCHEMA = 'sentinel.local-paper-build/1'


def safe_directory(path, *, create=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and not path.is_symlink(),
            'DELIVERY_DIRECTORY_UNSAFE')
    require(not any(parent.is_symlink() for parent in path.parents), 'DELIVERY_DIRECTORY_UNSAFE')
    if create:
        path.mkdir(mode=0o700,parents=False,exist_ok=True)
    require(path.is_dir(), 'DELIVERY_DIRECTORY_ABSENT')
    return path.resolve()


def baseline(path):
    """Read an already completed receipt; no new baseline can be asserted."""
    value = read_json(path)
    require(isinstance(value,dict), 'PREDECESSOR_RECEIPT_SHAPE')
    if value.get('stage') == 'VERIFIED':
        require(Path(path).name == 'receipt.json', 'PREDECESSOR_JOURNAL_REQUIRED')
        journal = Journal(Path(path).parent)
        require(journal.read() == value, 'PREDECESSOR_RECEIPT_CHANGED')
        selected = journal.request['candidate']
        artifacts = value['artifacts']
        result = dict(commit=selected['commit'],image=selected['image'],
            postgres=artifacts['postgres'],system=artifacts['preserved']['system'])
    else:
        # The first generic delivery consumes the existing completed installer
        # receipt as an immutable witness. Later deliveries use the journal.
        require(value.get('stage') == 'APPLICATIONS_HEALTHY_LEADERSHIP_ADVANCING'
                and value.get('leadership_advancing') is True and value.get('completed_at'),
                'PREDECESSOR_INSTALLATION_NOT_COMPLETE')
        require(datetime.fromisoformat(value['completed_at']).utcoffset() is not None,
                'PREDECESSOR_COMPLETION_TIME_INVALID')
        result = dict(commit=value['commit'],image=value['image'],
            postgres=value['postgres'],system=value['preserved']['system'])
    require(re.fullmatch(r'[0-9a-f]{40}', result['commit']) is not None
            and re.fullmatch(r'sha256:[0-9a-f]{64}', result['image']) is not None,
            'PREDECESSOR_RUNTIME_INVALID')
    pg = result['postgres']
    require(isinstance(pg,dict) and set(pg) == {
        'command','container','image','source','started','volume'}
        and pg['volume'] == 'sentinel_sentinel_pgdata'
        and pg['command'] == ['postgres','-c','archive_mode=off','-c','archive_command=']
        and isinstance(result['system'],str) and result['system'].isdigit(),
        'PREDECESSOR_POSTGRES_INVALID')
    return result


def allowed_delta(path, expected_sha):
    require(sha256_file(path) == expected_sha, 'APPROVED_DELTA_CHANGED')
    names = read_json(path)
    require(isinstance(names,list) and names and len(names) == len(set(names)), 'APPROVED_DELTA_SHAPE')
    for name in names:
        require(isinstance(name,str)
            and (name.startswith(('sentinel/','scripts/','tests/','docs/','tools/'))
                 or name in REVIEWED_HOST_ARTIFACTS)
            and '\\' not in name and '..' not in name.split('/')
            and '/.env' not in name and not name.endswith('.env'), 'APPROVED_DELTA_PATH')
    return sorted(names)


def _changed(source, predecessor, commit, approved):
    actual = git(source,'diff','--name-only',predecessor,commit).splitlines()
    require(sorted(actual) == approved, 'CANDIDATE_DELTA_CHANGED')
    statuses = git(source,'diff','--name-status','--no-renames',predecessor,commit).splitlines()
    require(statuses and all(line.startswith(('A\t','M\t')) for line in statuses),
            'SOURCE_LAYER_REFUSES_DELETIONS_OR_RENAMES')
    require(not any(name.startswith(('sentinel/requirements.','sentinel/requirements-')) for name in actual),
            'SOURCE_LAYER_CANNOT_CHANGE_DEPENDENCIES')
    return actual


def _inspect(host, reference):
    values = json.loads(host.run(['docker','image','inspect',reference]).stdout)
    require(isinstance(values,list) and len(values) == 1, 'IMAGE_INSPECTION_SHAPE')
    return values[0]


def _economic(host, commit, image):
    code = ('import json\nfrom sentinel.authority import canonical_sha256\n'
        'from sentinel.strategy import production_strategy\n'
        'print(json.dumps(dict(strategy=canonical_sha256(production_strategy()[1]))))\n')
    output = host.run(['docker','run','--rm','--pull=never','--network','none',
        '--cpus','0.5','--memory','384m','-e','SENTINEL_GIT_COMMIT='+commit,
        '-e','SENTINEL_RUNTIME_IMAGE_DIGEST='+image,'-e','SENTINEL_TEST_IMAGE_DIGEST='+image,
        '--entrypoint','python',image,'-B','-c',code],timeout=90)
    return json.loads(output.stdout)['strategy']


def _foundation_preserved(before, after, commit):
    require(after['RootFS']['Layers'][:len(before['RootFS']['Layers'])] == before['RootFS']['Layers'],
            'BUILT_IMAGE_FOUNDATION_CHANGED')
    old_config, new_config = before['Config'], after['Config']
    for name in set(old_config)|set(new_config):
        if name in {'Env','Labels'}:
            continue
        require(old_config.get(name) == new_config.get(name), 'BUILT_RUNTIME_CONFIGURATION_CHANGED')
    def environment(config):
        return dict(item.split('=',1) for item in config.get('Env') or [])
    expected = dict(environment(old_config),SENTINEL_IMAGE_SOURCE_REVISION=commit)
    require(environment(new_config) == expected, 'BUILT_RUNTIME_ENVIRONMENT_CHANGED')
    labels = dict(old_config.get('Labels') or {})
    labels['org.opencontainers.image.revision'] = commit
    require(new_config.get('Labels') == labels, 'BUILT_RUNTIME_LABELS_CHANGED')


def build(*, source, deployment, predecessor_receipt, qualification, qualification_sha256,
          approved_delta, approved_delta_sha256, operation_dir, commit, host_type=Host,
          baseline_reader=baseline, foundation_reference=None, predecessor_receipt_options=None):
    options=predecessor_receipt_options or {}
    require(options in ({},{'allow_started':True}), 'BUILD_PREDECESSOR_OPTIONS_INVALID')
    source, deployment = safe_directory(source), safe_directory(deployment)
    folder = safe_directory(operation_dir,create=True)
    require(not folder.is_relative_to(source), 'BUILD_EVIDENCE_INSIDE_QUALIFIED_SOURCE')
    require(not (folder/'build.json').exists() and not (folder/'build-started.json').exists(),
            'BUILD_ALREADY_STARTED_INSPECT_RETAINED_EVIDENCE')
    old = baseline_reader(predecessor_receipt)
    report = validate_report(qualification,qualification_sha256,source,commit,old['commit'])
    approved = allowed_delta(approved_delta,approved_delta_sha256)
    changed = _changed(source,old['commit'],commit,approved)
    host = host_type(dict(source=str(source),deployment=str(deployment),
        predecessor=old,candidate=dict(commit=commit)),folder)
    foundation_tag = foundation_reference or 'sentinel-local-paper:'+old['commit'][:8]
    tag = 'sentinel-local-paper:'+commit[:8]
    require(tag != foundation_tag, 'LOCAL_IMAGE_TAG_COLLISION')
    with host.owned():
        foundation = _inspect(host,foundation_tag)
        require(foundation['Id'] == old['image']
            and foundation['Config'].get('Labels',{}).get('org.opencontainers.image.revision') == old['commit'],
            'FOUNDATION_IMAGE_CHANGED')
        context = folder/'source-context'
        context.mkdir(mode=0o700)
        names = [name for name in report['source_files'] if name.startswith('sentinel/')]
        require(bool(names), 'RUNTIME_SOURCE_ABSENT')
        for name in names:
            original, target = source/name, context/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(original,target)
            target.chmod(0o644)
            require(sha256_file(target) == report['source_files'][name], 'BUILD_CONTEXT_SOURCE_CHANGED')
            for parent in target.parents:
                if parent == context:
                    break
                parent.chmod(0o755)
        dockerfile = ('FROM '+foundation_tag+'\nARG SOURCE_GIT_SHA\n'
            'LABEL org.opencontainers.image.revision=${SOURCE_GIT_SHA}\n'
            'ENV SENTINEL_IMAGE_SOURCE_REVISION=${SOURCE_GIT_SHA}\n'
            'COPY sentinel/ /app/sentinel/\n')
        (context/'Dockerfile').write_text(dockerfile,encoding='utf-8')
        command = ['docker','build','--network','none','--pull=false','--progress','plain',
            '--build-arg','SOURCE_GIT_SHA='+commit,'-t',tag,str(context)]
        write_new(folder/'build-started.json',dict(schema=BUILD_SCHEMA,commit=commit,
            qualification_sha256=qualification_sha256,foundation=old['image'],command=command,
            at=utcnow().isoformat()))
        log = folder/'build.log'
        with log.open('xb') as stream:
            completed = subprocess.run(command,env=host.clean,stdout=stream,
                stderr=subprocess.STDOUT,timeout=300)
        require(completed.returncode == 0, 'SOURCE_ONLY_BUILD_FAILED_INSPECT_LOG')
        clean_candidate(source,commit,old['commit'])
        require(source_files(source) == report['source_files'], 'SOURCE_CHANGED_DURING_BUILD')
        require(_inspect(host,foundation_tag)['Id'] == old['image'], 'FOUNDATION_TAG_CHANGED_DURING_BUILD')
        image = _inspect(host,tag)
        _foundation_preserved(foundation,image,commit)
        identity = host.probe(commit,image['Id'])
        old_identity = host.probe(old['commit'],old['image'])
        strategy = _economic(host,commit,image['Id'])
        require(identity['wealth'] == old_identity['wealth']
                and strategy == _economic(host,old['commit'],old['image']), 'ECONOMIC_RUNTIME_CHANGED')
        result = dict(schema=BUILD_SCHEMA,at=utcnow().isoformat(),source=str(source),
            deployment=str(deployment),commit=commit,image=image['Id'],tag=tag,
            source_identity=identity,strategy_sha256=strategy,foundation=old,
            predecessor_receipt=dict(path=str(Path(predecessor_receipt).resolve()),
                sha256=sha256_file(predecessor_receipt),**options),
            qualification=dict(report_path=str(Path(qualification).resolve()),report_sha256=qualification_sha256),
            allowed_delta=approved,changed_files=changed,context=str(context),
            log=str(log),log_sha256=sha256_file(log),command=command)
        write_new(folder/'build.json',result)
        return result
