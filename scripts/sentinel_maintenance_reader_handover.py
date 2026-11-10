#!/usr/bin/env python3
"""Qualified, resumable replacement of the one PAPER user-systemd reader.

Source selectors are authenticated configuration, never process readiness.
The existing target pass flock fences every stop, including rollback.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import subprocess
import tempfile
import time

import sentinel_env
from sentinel_backup_lock import _lock_path
from sentinel_lock_ownership import owns_exclusive_flock
from sentinel_local_delivery import environment, qualification
from sentinel_local_delivery.host import RUNTIME_KEYS, SERVICES, application_healthy
from sentinel_local_delivery.model import DeliveryRefused, canonical, digest, read_json, require

UNIT = 'sentinel-paper-backup-maintenance.service'
DROPIN = 'zz-sentinel-qualified-reader.conf'
SCHEMA = 'sentinel.maintenance-reader-handover/2'
PURPOSE = b'sentinel-maintenance-reader-handover-v1\0'
PHASES = ('PREPARED', 'STOP_REQUESTED', 'STOPPED', 'DROPIN_INSTALLED',
          'HOST_SELECTED', 'DEPLOYMENT_SELECTED', 'START_REQUESTED', 'STARTED', 'VERIFIED',
          'ROLLBACK_REQUESTED', 'ROLLBACK_RESTORED', 'ROLLBACK_START_REQUESTED', 'ROLLED_BACK')
ALLOWED_ENV = RUNTIME_KEYS | {'SENTINEL_IMAGE_SOURCE_REVISION', 'SENTINEL_BACKUP_SHARED_INTEGRITY'}
REQUEST_FIELDS = {'operation_id','deployment','source','image','commit','old_source','old_commit',
    'old_environment_sha256','old_script_sha256','qualification','qualification_sha256',
    'application_receipt','application_receipt_sha256','deployment_environment_sha256',
    'new_environment_sha256','new_script_sha256','pass_lock','postgres','system',
    'application_containers','old_runtime_pointer_sha256','new_runtime_pointer_sha256',
    'old_unit','old_reader','dropin','new_dropin','selectors','host_tool'}
HOST_TOOL_FIELDS = {'source','commit','executable_sha256','qualification','qualification_sha256'}
HOST_DELTA = frozenset({'scripts/sentinel_maintenance_reader_handover.py',
    'tests/scripts/test_sentinel_maintenance_reader_handover.py','docs/operation-owned-integrity-work.md'})
TOOL_PATH = 'scripts/sentinel_maintenance_reader_handover.py'


def safe_path(value):
    path = Path(value)
    require(path.is_absolute() and path.resolve() == path
        and not any(p.is_symlink() for p in (path, *path.parents)), 'READER_PATH_UNSAFE')
    return path


def raw_file(path, *, optional=False):
    path = safe_path(path)
    if optional and not path.exists():
        return None
    raw = environment._selection_bytes(path, 1024*1024)
    require(path.stat().st_uid == os.getuid(), 'READER_FILE_OWNER_CHANGED')
    return raw


def file_sha(path):
    return hashlib.sha256(raw_file(path)).hexdigest()


def runtime_pointer(root, values):
    raw = raw_file(root/'artifacts/sentinel/deployment/validated-runtime.env', optional=True)
    if raw is None:
        return values.get('SENTINEL_RUNTIME_IMAGE_REF'), None
    prefix = b'SENTINEL_RUNTIME_IMAGE_REF='
    require(raw.startswith(prefix) and len(raw.splitlines()) == 1, 'READER_RUNTIME_POINTER_INVALID')
    return raw[len(prefix):].decode('ascii').strip(), hashlib.sha256(raw).hexdigest()


def replace_exact(path, old, new):
    """Compare-and-replace only retained bytes; tolerate a crash after replace."""
    path = safe_path(path)
    current = raw_file(path, optional=True)
    require(current in (old, new), 'READER_FILE_DRIFT')
    if current == new:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_path(path.parent)
    if new is None:
        path.unlink()
    else:
        fd, temporary = tempfile.mkstemp(prefix='.reader-handover-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(new); stream.flush(); os.fsync(stream.fileno())
            # A last check prevents replacing a concurrent, unrelated edit.
            require(raw_file(path, optional=True) == current, 'READER_FILE_DRIFT')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def signed(value, key):
    require(isinstance(key, str) and len(key.encode()) >= 32, 'READER_KEY_INVALID')
    return hmac.new(key.encode(), PURPOSE+canonical(value), hashlib.sha256).hexdigest()


def selection(path, binding, key):
    record = read_json(path)
    require(isinstance(record, dict) and set(record) == {'value', 'signature'}, 'READER_SELECTION_SHAPE')
    value = record['value']
    require(isinstance(value, dict) and set(value) == {
        'schema', 'deployment', 'source', 'commit', 'script_sha256', 'environment_sha256'}
        and value['schema'] == 'sentinel.native-maintenance-reader/1'
        and value['deployment'] == str(binding) and isinstance(record['signature'], str)
        and hmac.compare_digest(record['signature'], environment.reader_signature(value, key)),
        'READER_SELECTION_SIGNATURE')
    return value


def selection_raw(value, binding, key):
    value = dict(value, deployment=str(binding))
    return canonical(dict(value=value, signature=environment.reader_signature(value, key)))+b'\n'


def qualified_host(executable, report_path, report_sha256, application_commit):
    """Authenticate this host command separately from the unchanged reader image."""
    executable = safe_path(Path(executable).absolute())
    source = safe_path(executable.parents[1])
    require(executable == source/TOOL_PATH, 'READER_HOST_EXECUTABLE_SUBSTITUTED')
    commit = qualification.git(source,'rev-parse','HEAD')
    report_path = safe_path(report_path)
    report = read_json(report_path)
    require(report.get('schema') == qualification.OPERATIONAL_SCHEMA
        and report.get('source_scope') == qualification.OPERATIONAL_SCOPE,
        'READER_HOST_QUALIFICATION_SCOPE_REQUIRED')
    qualification.validate_report(report_path,report_sha256,source,commit,application_commit)
    changes = qualification.git(source,'diff','--name-status','--no-renames',application_commit,commit).splitlines()
    require(len(changes) == len(HOST_DELTA) and all(row.startswith('M\t') for row in changes)
        and {row[2:] for row in changes} == HOST_DELTA, 'READER_HOST_DELTA_REFUSED')
    executable_sha = qualification.sha256_file(executable)
    require(HOST_DELTA <= report['source_files'].keys()
        and report['source_files'][TOOL_PATH] == executable_sha, 'READER_HOST_EXECUTABLE_UNQUALIFIED')
    return dict(source=str(source),commit=commit,executable_sha256=executable_sha,
        qualification=str(report_path),qualification_sha256=report_sha256)


def environment_transition(old, new, app, commit, image):
    """Preserve every non-provenance value, including secret and media policy."""
    require({k:v for k,v in old.items() if k not in ALLOWED_ENV}
        == {k:v for k,v in new.items() if k not in ALLOWED_ENV}, 'READER_ENV_POLICY_CHANGED')
    require(new.get('SENTINEL_BACKUP_SHARED_INTEGRITY') == 'REQUIRED_V1', 'READER_SHARED_PROOF_REQUIRED')
    for values in (old, new, app):
        require(values.get('ALPACA_BASE_URL', sentinel_env.PAPER_URL) == sentinel_env.PAPER_URL
            and values.get('SENTINEL_LOCAL_PAPER_MODE') == 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
            and values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1'
            and re.fullmatch(r'PA[A-Za-z0-9]+', values.get('SENTINEL_LOCAL_PAPER_ACCOUNT_ID', ''))
            and values.get('SENTINEL_PUBLICATION_RECEIPT_KEY') == old.get('SENTINEL_PUBLICATION_RECEIPT_KEY')
            and len(values.get('SENTINEL_PUBLICATION_RECEIPT_KEY', '').encode()) >= 32,
            'READER_PAPER_POLICY_CHANGED')
    for key in ('SENTINEL_LOCAL_PAPER_ACCOUNT_ID', 'SENTINEL_POSTGRES_PASSWORD'):
        require(bool(old.get(key)) and old[key] == app.get(key), 'READER_APP_AUTHORITY_CHANGED')
    require(new.get('SENTINEL_GIT_COMMIT') == app.get('SENTINEL_GIT_COMMIT') == commit
        and all(new.get(k) == image for k in ('SENTINEL_RUNTIME_IMAGE_DIGEST',
            'SENTINEL_TEST_IMAGE_DIGEST', 'SENTINEL_RUNTIME_IMAGE_REF', 'SENTINEL_LOCAL_PAPER_IMAGE'))
        and app.get('SENTINEL_RUNTIME_IMAGE_DIGEST') == image
        and new.get('SENTINEL_IMAGE_SOURCE_REVISION', commit) == commit
        and ('SENTINEL_IMAGE_SOURCE_REVISION' not in old
            or new.get('SENTINEL_IMAGE_SOURCE_REVISION') == commit),
        'READER_RUNTIME_CHANGED')
    for key in ('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', 'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256'):
        require(new.get(key) == app.get(key), 'READER_SOURCE_IDENTITY_CHANGED')


@contextmanager
def pass_fence(path, wait_seconds):
    require(type(wait_seconds) is int and 0 <= wait_seconds <= 3660, 'READER_WAIT_INVALID')
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = path.parent.stat()
    require(directory.st_uid == os.getuid() and stat.S_IMODE(directory.st_mode) == 0o700,
        'READER_LOCK_DIRECTORY_UNSAFE')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid(),
            'READER_LOCK_UNSAFE')
        deadline = time.monotonic()+wait_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, 'READER_PASS_BUSY')
                time.sleep(min(0.1, max(0, deadline-time.monotonic())))
        require(owns_exclusive_flock(fd), 'READER_PASS_OWNERSHIP_UNPROVEN')
        named = path.stat()
        require((named.st_dev,named.st_ino) == (info.st_dev,info.st_ino), 'READER_PASS_LOCK_REPLACED')
        yield
    finally:
        os.close(fd)


def owns_loop_lock(reader, path):
    """Observe the existing supervisor flock, bound to its process incarnation."""
    process = Path('/proc')/str(reader['pid'])
    try:
        before = (process/'stat').read_bytes().rpartition(b')')[2].split()[19]
        target = Path(path).stat()
        descriptors = list((process/'fdinfo').iterdir())
        require(len(descriptors) <= 4096, 'READER_FD_BOUND')
        found = False
        for descriptor in descriptors:
            lines = descriptor.read_text().splitlines()
            for line in lines:
                parts = line.split()
                if len(parts) != 9 or parts[:1] != ['lock:'] or parts[2:5] != ['FLOCK','ADVISORY','WRITE']:
                    continue
                major, minor, inode = parts[6].split(':')
                if (int(parts[5]) == reader['pid'] and int(major,16) == os.major(target.st_dev)
                    and int(minor,16) == os.minor(target.st_dev) and int(inode) == target.st_ino
                    and parts[7:] == ['0','EOF']):
                    found = True
        after = (process/'stat').read_bytes().rpartition(b')')[2].split()[19]
        return found and int(before) == int(after) == reader['start_ticks']
    except (OSError, ValueError, IndexError):
        return False


class Native:
    """Fixed unit and read-only runtime readers; no arbitrary command surface."""
    def __init__(self):
        self.clean = {k:v for k,v in os.environ.items() if k in {'HOME','USER','LOGNAME','PATH','LANG','LC_ALL'}}
        self.home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        require(os.getuid() != 0 and self.clean.get('HOME') == str(self.home), 'READER_USER_SESSION_REQUIRED')
        self.dropin = self.home/'.config/systemd/user'/f'{UNIT}.d'/DROPIN
        runtime = safe_path(Path('/run/user')/str(os.getuid()))
        info, bus = runtime.stat(), safe_path(runtime/'bus').stat()
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
            and bus.st_uid == os.getuid() and stat.S_ISSOCK(bus.st_mode), 'READER_USER_BUS_UNSAFE')
        self.bus = dict(self.clean,XDG_RUNTIME_DIR=str(runtime),
            DBUS_SESSION_BUS_ADDRESS='unix:path='+str(runtime/'bus'))

    def run(self, args, timeout=30):
        result = subprocess.run(args, env=self.bus if args[0] == 'systemctl' else self.clean,
            capture_output=True, timeout=timeout)
        require(result.returncode == 0, 'READER_HOST_COMMAND_FAILED')
        return result.stdout.decode().strip()

    def unit(self):
        fields = self.run(['systemctl','--user','show',UNIT,'--no-pager',
            '-p','MainPID','-p','ActiveState','-p','SubState','-p','WorkingDirectory',
            '-p','ExecStart','-p','Restart','-p','KillMode','-p','FragmentPath','-p','DropInPaths'])
        value = dict(line.split('=',1) for line in fields.splitlines())
        require(set(value) == {'MainPID','ActiveState','SubState','WorkingDirectory','ExecStart',
            'Restart','KillMode','FragmentPath','DropInPaths'}, 'READER_UNIT_SHAPE')
        match = re.search(r'argv\[\]=(.*?) ; ignore_errors=', value['ExecStart'])
        require(match is not None, 'READER_UNIT_COMMAND_INVALID')
        argv = shlex.split(match.group(1))
        require(argv[:2] == ['/usr/bin/env','-i']
            and argv[-3:] == ['/bin/bash','scripts/sentinel-backup-maintenance.sh','--loop'],
            'READER_UNIT_COMMAND_INVALID')
        assignments = dict(arg.split('=',1) for arg in argv[2:-3] if '=' in arg)
        require(len(assignments) == len(argv[2:-3]) and set(assignments) <= {
            'HOME','USER','LOGNAME','LANG','PATH','WSL_DISTRO_NAME'}
            and assignments.get('HOME') == str(self.home)
            and assignments.get('USER') == assignments.get('LOGNAME') == pwd.getpwuid(os.getuid()).pw_name
            and assignments.get('PATH') == '/usr/sbin:/usr/bin:/sbin:/bin'
            and value['Restart'] == 'on-failure' and value['KillMode'] == 'control-group',
            'READER_UNIT_POLICY_CHANGED')
        fragment = self.home/'.config/systemd/user'/UNIT
        require(value['FragmentPath'] == str(fragment), 'READER_UNIT_OWNER_CHANGED')
        paths = shlex.split(value['DropInPaths'])
        require(len(paths) <= 128 and len(paths) == len(set(paths)), 'READER_UNIT_DROPINS_INVALID')
        for path in paths:
            require(Path(path).parent == self.dropin.parent, 'READER_UNIT_DROPINS_INVALID')
        static = {str(fragment):file_sha(fragment)}
        static.update({p:file_sha(p) for p in paths if p != str(self.dropin)})
        return dict(pid=int(value['MainPID']), active=value['ActiveState'], sub=value['SubState'],
            root=value['WorkingDirectory'], argv=argv, static=static,
            stable=raw_file(self.dropin, optional=True).decode() if self.dropin.exists() else None)

    def control(self, verb):
        require(verb in {'start','stop','daemon-reload'}, 'READER_UNIT_OPERATION_INVALID')
        args = ['systemctl','--user',verb]
        if verb != 'daemon-reload': args.append(UNIT)
        self.run(args, timeout=45)

    def reader(self, deployment, root, *, required):
        found = environment.readers(Path(deployment), required=required, selected_root=Path(root))
        if not found: return None
        value = asdict(found[0]); value['groups'] = list(value['groups'])
        require(value['uid'] == os.getuid() and value['gid'] == os.getgid()
            and value['groups'] == sorted(os.getgroups()), 'READER_CREDENTIALS_CHANGED')
        return value

    def ready(self, request, root, *, previous=None):
        deadline = time.monotonic()+15
        delay = 0.1
        while True:
            unit = self.unit()
            reader = self.reader(request['deployment'], root, required=False)
            if (reader is not None and unit['pid'] == reader['pid'] and unit['active'] == 'active'
                and unit['sub'] == 'running' and unit['root'] == root
                and (previous is None or (reader['pid'],reader['start_ticks']) !=
                     (previous['pid'],previous['start_ticks']))
                and owns_loop_lock(reader, Path(request['pass_lock']).with_suffix('.maintenance-loop'))):
                return reader
            require(time.monotonic() < deadline, 'READER_START_NOT_READY')
            time.sleep(min(delay,max(0,deadline-time.monotonic())))
            delay = min(1.0,delay*2)

    def inspect_image(self, image):
        values = json.loads(self.run(['docker','image','inspect',image]))
        require(isinstance(values,list) and len(values) == 1, 'READER_IMAGE_INVALID')
        return values[0]

    def host_tool(self, commit, report_path, report_sha256):
        return qualified_host(__file__,report_path,report_sha256,commit)

    def runtime_facts(self, image, *, require_healthy=True):
        from sentinel_backed_local_patch import postgres_facts
        targets = ['sentinel-'+service+'-1' for service in SERVICES]
        containers = json.loads(self.run(['docker','container','inspect',*targets,'sentinel-sentinel-postgres-1']))
        require(len(containers) == len(targets)+1 and all(
            application_healthy(item,image) if require_healthy else item.get('Image') == image
            for item in containers[:-1]), 'READER_APPLICATION_NOT_HEALTHY')
        pg = postgres_facts(containers[-1])
        system = self.run(['docker','exec','sentinel-sentinel-postgres-1','psql','-XqAt',
            '-v','ON_ERROR_STOP=1','-U','sentinel','-d','sentinel','-c',
            "BEGIN READ ONLY; SET LOCAL statement_timeout='5000ms'; SELECT system_identifier::text FROM pg_control_system(); COMMIT;"])
        return dict(postgres=pg,system=system,application_containers=[
            dict(id=v['Id'],started=v['State']['StartedAt']) for v in containers[:-1]])

    def final(self, request, *, restoring=False):
        require(all(request[k] == v for k,v in self.runtime_facts(
            request['image'],require_healthy=not restoring).items()),
            'READER_RUNTIME_AUTHORITY_DRIFT')
        for root, name, expected in ((request['deployment'],'.env',request['deployment_environment_sha256']),
                (request['old_source'],'.env',request['old_environment_sha256']),
                (request['source'],'.env',request['new_environment_sha256'])):
            require(file_sha(Path(root)/name) == expected, 'READER_ENVIRONMENT_DRIFT')
        for root,key in ((request['old_source'],'old_runtime_pointer_sha256'),
                         (request['source'],'new_runtime_pointer_sha256')):
            require(runtime_pointer(Path(root),sentinel_env.load(Path(root)/'.env',required=True))[1]
                == request[key], 'READER_RUNTIME_POINTER_CHANGED')

    def assets(self, spec, *, restoring=False):
        """Authenticate immutable staged inputs and the already VERIFIED app."""
        from sentinel_backed_local_patch import predecessor_witness
        deployment, source = safe_path(spec['deployment']), safe_path(spec['source'])
        app = sentinel_env.load(deployment/'.env', required=True)
        old_root = safe_path(spec['old_source'])
        old = sentinel_env.load(old_root/'.env', required=True)
        new = sentinel_env.load(source/'.env', required=True)
        commit, image = spec['commit'], spec['image']
        require(re.fullmatch('[0-9a-f]{40}',commit) and re.fullmatch('sha256:[0-9a-f]{64}',image),
            'READER_CANDIDATE_INVALID')
        environment_transition(old,new,app,commit,image)
        require(file_sha(old_root/'.env') == spec['old_environment_sha256'], 'READER_OLD_ENV_CHANGED')
        require(qualification.git(old_root,'rev-parse','HEAD') == spec['old_commit']
            and not qualification.git(old_root,'status','--porcelain','--untracked-files=no')
            and file_sha(old_root/'scripts/sentinel_backup_maintenance.py') == spec['old_script_sha256'],
            'READER_OLD_SOURCE_CHANGED')
        require(file_sha(spec['application_receipt']) == spec['application_receipt_sha256'],
            'READER_APPLICATION_RECEIPT_CHANGED')
        witness = predecessor_witness(Path(spec['application_receipt']), inspect_image=self.inspect_image)
        record = read_json(spec['application_receipt'])
        app_request = read_json(Path(spec['application_receipt']).parent/'request.json')
        require(record.get('stage') == 'VERIFIED' and app_request['deployment'] == str(deployment)
            and witness['git_commit'] == commit and witness['runtime_image'] == image,
            'READER_VERIFIED_APPLICATION_REQUIRED')
        identity = app_request['candidate']['source_identity']
        require(app.get('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256') == identity['source']
            and app.get('SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256') == identity['shadow_config'],
            'READER_APPLICATION_SOURCE_IDENTITY_CHANGED')
        report = read_json(spec['qualification'])
        require(report.get('schema') == qualification.OPERATIONAL_SCHEMA
            and report.get('source_scope') == qualification.OPERATIONAL_SCOPE,
            'READER_QUALIFICATION_SCOPE_REQUIRED')
        qualification.validate_report(spec['qualification'], spec['qualification_sha256'], source,
            commit, report.get('predecessor_commit'))
        required = {'scripts/sentinel_maintenance_reader_handover.py',
            'scripts/sentinel_backup_maintenance.py', 'scripts/sentinel_backup_shared_integrity.py',
            'scripts/sentinel_backup_integrity_report.py', 'sentinel/backup_maintenance_integrity.py'}
        require(required <= report['source_files'].keys(), 'READER_QUALIFICATION_INPUTS_MISSING')
        host_tool = self.host_tool(commit,spec['host_tool']['qualification'],spec['host_tool']['qualification_sha256'])
        inspected = self.inspect_image(image)
        require(inspected['Id'] == image
            and inspected['Config']['Labels']['org.opencontainers.image.revision'] == commit,
            'READER_IMAGE_REVISION_CHANGED')
        selected_image, new_pointer = runtime_pointer(source,new)
        old_image, old_pointer = runtime_pointer(old_root,old)
        require(selected_image == image and re.fullmatch(r'(?:[^\s]+@)?sha256:[0-9a-f]{64}',old_image or ''),
            'READER_RUNTIME_POINTER_CHANGED')
        require(self.inspect_image(old_image)['Config']['Labels']['org.opencontainers.image.revision']
            == spec['old_commit'], 'READER_OLD_IMAGE_REVISION_CHANGED')
        runtime = self.runtime_facts(image,require_healthy=not restoring)
        require(runtime['postgres'] == witness['postgres'] and runtime['system'] == witness['system'],
            'READER_POSTGRES_CHANGED')
        lock = _lock_path(dict(old,SENTINEL_BASE_BACKUP_LOCK_ROOT=old.get('SENTINEL_BACKUP_DIR','')))
        require(lock is not None, 'READER_PASS_TARGET_UNAVAILABLE')
        return dict(deployment_environment_sha256=file_sha(deployment/'.env'),
            new_environment_sha256=file_sha(source/'.env'), new_script_sha256=file_sha(
                source/'scripts/sentinel_backup_maintenance.py'), pass_lock=str(lock),
            old_runtime_pointer_sha256=old_pointer,new_runtime_pointer_sha256=new_pointer,
            host_tool=host_tool,**runtime)


def render_dropin(root, argv):
    require(re.fullmatch(r'/[A-Za-z0-9_./-]+',root) is not None, 'READER_SYSTEMD_PATH_UNSUPPORTED')
    require(all(re.fullmatch(r'[A-Za-z0-9_=/.:+-]+',arg) for arg in argv), 'READER_SYSTEMD_ARG_UNSUPPORTED')
    return '[Service]\nWorkingDirectory='+root+'\nExecStart=\nExecStart='+' '.join(argv)+'\n'


class Handover:
    def __init__(self, operation_dir, platform=None):
        self.directory = safe_path(operation_dir)
        self.platform = platform or Native()
        self.path = self.directory/'receipt.json'

    def key(self, deployment):
        return sentinel_env.load(safe_path(deployment)/'.env', required=True).get('SENTINEL_PUBLICATION_RECEIPT_KEY')

    @contextmanager
    def exclusive(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with pass_fence(self.directory/'.operation.lock',0): yield

    def write(self, value):
        envelope = dict(value=value, signature=signed(value,self.key(value['request']['deployment'])))
        replace_exact(self.path, raw_file(self.path,optional=True), canonical(envelope)+b'\n')

    def read(self):
        envelope = read_json(self.path)
        require(isinstance(envelope,dict) and set(envelope) == {'value','signature'}, 'READER_JOURNAL_SHAPE')
        value = envelope['value']
        require(isinstance(value,dict) and set(value) == {'schema','request','phase','history','reader'}
            and value['schema'] == SCHEMA and value['phase'] in PHASES
            and isinstance(value['request'],dict) and set(value['request']) == REQUEST_FIELDS
            and isinstance(value['request']['host_tool'],dict)
            and set(value['request']['host_tool']) == HOST_TOOL_FIELDS
            and isinstance(envelope['signature'],str) and hmac.compare_digest(envelope['signature'],
                signed(value,self.key(value['request']['deployment']))), 'READER_JOURNAL_SIGNATURE')
        history = value['history']
        require(isinstance(history,list) and 1 <= len(history) <= 32, 'READER_JOURNAL_HISTORY')
        prior = digest(value['request'])
        previous_phase = None
        for entry in history:
            require(set(entry) == {'phase','previous'} and entry['phase'] in PHASES
                and entry['previous'] == prior, 'READER_JOURNAL_HISTORY')
            phase = entry['phase']
            require((previous_phase is None and phase == 'PREPARED')
                or (previous_phase is not None and phase == 'ROLLBACK_REQUESTED'
                    and previous_phase not in {'VERIFIED','ROLLED_BACK'} and not previous_phase.startswith('ROLLBACK'))
                or (previous_phase is not None and previous_phase not in {'VERIFIED','ROLLED_BACK'}
                    and PHASES.index(phase) == PHASES.index(previous_phase)+1),
                'READER_JOURNAL_TRANSITION')
            prior = digest(entry)
            previous_phase = phase
        require(history[-1]['phase'] == value['phase'], 'READER_JOURNAL_HISTORY')
        return value

    def advance(self, value, phase, *, reader=None):
        value['phase'] = phase
        value['history'].append(dict(phase=phase,previous=digest(value['history'][-1])))
        if reader is not None: value['reader'] = reader
        self.write(value)

    def prepare(self, *, deployment, source, image, qualification_path, qualification_sha256,
                application_receipt, operation_id, host_qualification_path, host_qualification_sha256):
        with self.exclusive():
            require(not self.path.exists(), 'READER_OPERATION_EXISTS')
            deployment, source = safe_path(deployment), safe_path(source)
            require(re.fullmatch('[a-z0-9][a-z0-9-]{0,79}',operation_id), 'READER_OPERATION_ID_INVALID')
            key = self.key(deployment)
            hp, dp = deployment.parent/environment.HOST_READER_SELECTION, deployment/environment.READER_SELECTION
            host = selection(hp,deployment.parent,key); selected = selection(dp,deployment,key)
            require({k:v for k,v in host.items() if k != 'deployment'} == {
                k:v for k,v in selected.items() if k != 'deployment'}, 'READER_SELECTORS_DISAGREE')
            old = safe_path(selected['source'])
            require(source != old and all(not self.directory.is_relative_to(p) for p in (old,source,deployment)),
                'READER_OPERATION_SCOPE_INVALID')
            require(environment.selected_reader(deployment,sentinel_env.load(deployment/'.env',required=True))[0] == old,
                'READER_SELECTED_SOURCE_CHANGED')
            spec = dict(operation_id=operation_id, deployment=str(deployment), source=str(source),
                image=image, commit=qualification.git(source,'rev-parse','HEAD'), old_source=str(old),
                old_commit=selected['commit'], old_environment_sha256=selected['environment_sha256'],
                old_script_sha256=selected['script_sha256'], qualification=str(safe_path(qualification_path)),
                qualification_sha256=qualification_sha256, application_receipt=str(safe_path(application_receipt)),
                application_receipt_sha256=file_sha(application_receipt),host_tool=dict(
                    qualification=str(safe_path(host_qualification_path)),qualification_sha256=host_qualification_sha256))
            spec.update(self.platform.assets(spec))
            unit = self.platform.unit(); reader = self.platform.reader(str(deployment),str(old),required=True)
            require(unit['pid'] == reader['pid'] and unit['root'] == str(old) and unit['active'] == 'active'
                and unit['sub'] == 'running' and owns_loop_lock(reader,Path(spec['pass_lock']).with_suffix('.maintenance-loop')),
                'READER_CURRENT_OWNER_UNPROVEN')
            if unit['stable'] is not None:
                require(unit['stable'] == render_dropin(str(old),unit['argv']), 'READER_STABLE_DROPIN_UNOWNED')
            spec.update(old_unit=unit, old_reader=reader, dropin=str(self.platform.dropin),
                new_dropin=render_dropin(str(source),unit['argv']), selectors=[])
            new_value = dict(selected,source=str(source),commit=spec['commit'],
                script_sha256=spec['new_script_sha256'],environment_sha256=spec['new_environment_sha256'])
            for path,binding in ((hp,deployment.parent),(dp,deployment)):
                spec['selectors'].append(dict(path=str(path),old=raw_file(path).decode(),
                    new=selection_raw(new_value,binding,key).decode()))
            value = dict(schema=SCHEMA,request=spec,phase='PREPARED',reader=None,
                history=[dict(phase='PREPARED',previous=digest(spec))])
            self.write(value)
            return value

    def validate_assets(self, request, *, restoring=False):
        facts = self.platform.assets(request,restoring=restoring)
        require(all(request.get(k) == v for k,v in facts.items()), 'READER_STAGED_ASSET_DRIFT')
        require(str(self.platform.dropin) == request['dropin'], 'READER_UNIT_OWNER_CHANGED')

    def unit_matches(self, request, *, new, stopped=False):
        unit = self.platform.unit(); old = request['old_unit']
        require(unit['static'] == old['static'] and unit['argv'] == old['argv']
            and unit['root'] == request['source' if new else 'old_source']
            and unit['stable'] == (request['new_dropin'] if new else old['stable']), 'READER_UNIT_DRIFT')
        if stopped: require(unit['pid'] == 0 and unit['active'] in {'inactive','failed'}, 'READER_UNIT_NOT_STOPPED')
        return unit

    def selectors(self, request, mode):
        for item in request['selectors']:
            current = raw_file(item['path'])
            allowed = (item[mode].encode(),) if mode in {'old','new'} else (item['old'].encode(),item['new'].encode())
            require(current in allowed, 'READER_SELECTOR_DRIFT')

    def stopped(self, request):
        require(self.platform.reader(request['deployment'],request['old_source'],required=False) is None
            and self.platform.reader(request['deployment'],request['source'],required=False) is None,
            'READER_PROCESS_STILL_RUNNING')

    def resume(self, wait_seconds=0):
        with self.exclusive():
            value = self.read(); request = value['request']
            self.validate_assets(request,restoring=value['phase'].startswith('ROLLBACK') or value['phase'] == 'ROLLED_BACK')
            if value['phase'].startswith('ROLLBACK'):
                return self._rollback(value,wait_seconds)
            if value['phase'] == 'ROLLED_BACK':
                self.unit_matches(request,new=False); self.selectors(request,'old')
                require(self.platform.reader(request['deployment'],request['old_source'],required=True) == value['reader']
                    and owns_loop_lock(value['reader'],Path(request['pass_lock']).with_suffix('.maintenance-loop')),
                    'READER_RESTORED_PROCESS_CHANGED')
                return value
            if value['phase'] == 'VERIFIED':
                self.unit_matches(request,new=True); self.selectors(request,'new')
                require(self.platform.reader(request['deployment'],request['source'],required=True) == value['reader'],
                    'READER_SUCCESSOR_CHANGED')
                require(owns_loop_lock(value['reader'],Path(request['pass_lock']).with_suffix('.maintenance-loop')),
                    'READER_LOOP_LOCK_UNPROVEN')
                return value
            if PHASES.index(value['phase']) <= PHASES.index('DEPLOYMENT_SELECTED'):
                with pass_fence(request['pass_lock'],wait_seconds):
                    if value['phase'] in {'PREPARED','STOP_REQUESTED'}:
                        self.selectors(request,'old')
                        unit = self.unit_matches(request,new=False)
                        if unit['pid']:
                            require(unit['pid'] == request['old_reader']['pid']
                                and self.platform.reader(request['deployment'],request['old_source'],required=True)
                                    == request['old_reader'], 'READER_CURRENT_PROCESS_CHANGED')
                            if value['phase'] == 'PREPARED': self.advance(value,'STOP_REQUESTED')
                            self.platform.control('stop')
                        else:
                            require(value['phase'] == 'STOP_REQUESTED', 'READER_CURRENT_PROCESS_CHANGED')
                        self.unit_matches(request,new=False,stopped=True); self.stopped(request)
                        self.advance(value,'STOPPED')
                    if value['phase'] == 'STOPPED':
                        self.stopped(request)
                        unit = self.platform.unit()
                        require(unit['static'] == request['old_unit']['static']
                            and unit['argv'] == request['old_unit']['argv'] and unit['pid'] == 0
                            and unit['root'] in {request['old_source'],request['source']}
                            and unit['stable'] in (request['old_unit']['stable'],request['new_dropin']),
                            'READER_UNIT_DRIFT')
                        replace_exact(request['dropin'],
                            None if request['old_unit']['stable'] is None else request['old_unit']['stable'].encode(),
                            request['new_dropin'].encode())
                        self.platform.control('daemon-reload')
                        self.unit_matches(request,new=True,stopped=True)
                        self.advance(value,'DROPIN_INSTALLED')
                    for index,phase in ((0,'HOST_SELECTED'),(1,'DEPLOYMENT_SELECTED')):
                        if value['phase'] == ('DROPIN_INSTALLED' if index == 0 else 'HOST_SELECTED'):
                            self.unit_matches(request,new=True,stopped=True); self.stopped(request)
                            self.selectors(request,'either')
                            item = request['selectors'][index]
                            replace_exact(item['path'],item['old'].encode(),item['new'].encode())
                            self.advance(value,phase)
                    self.unit_matches(request,new=True,stopped=True); self.selectors(request,'new')
                    self.advance(value,'START_REQUESTED')
            try:
                self.unit_matches(request,new=True); self.selectors(request,'new')
                if value['phase'] == 'START_REQUESTED':
                    if not self.platform.unit()['pid']: self.platform.control('start')
                    reader = self.platform.ready(request,request['source'],previous=request['old_reader'])
                    self.advance(value,'STARTED',reader=reader)
                require(self.platform.reader(request['deployment'],request['source'],required=True) == value['reader'],
                    'READER_SUCCESSOR_CHANGED')
                self.unit_matches(request,new=True); self.selectors(request,'new')
                require(owns_loop_lock(value['reader'],Path(request['pass_lock']).with_suffix('.maintenance-loop')),
                    'READER_LOOP_LOCK_UNPROVEN')
                self.platform.final(request)
                self.advance(value,'VERIFIED')
                return value
            except (DeliveryRefused,subprocess.TimeoutExpired,OSError):
                self._rollback(value,wait_seconds)
                raise

    def rollback(self, wait_seconds=0):
        with self.exclusive():
            value = self.read(); self.validate_assets(value['request'],restoring=True)
            return self._rollback(value,wait_seconds)

    def _rollback(self, value, wait_seconds):
        request = value['request']
        require(value['phase'] != 'VERIFIED', 'READER_COMPLETED_ROLLBACK_REFUSED')
        if value['phase'] == 'ROLLED_BACK': return value
        if value['phase'] not in {'ROLLBACK_RESTORED','ROLLBACK_START_REQUESTED'}:
            if value['phase'] != 'ROLLBACK_REQUESTED': self.advance(value,'ROLLBACK_REQUESTED')
            with pass_fence(request['pass_lock'],wait_seconds):
                self.selectors(request,'either')
                unit = self.platform.unit(); old = request['old_unit']
                require(unit['static'] == old['static'] and unit['argv'] == old['argv']
                    and unit['root'] in {request['source'],request['old_source']}
                    and unit['stable'] in (old['stable'],request['new_dropin']), 'READER_UNIT_DRIFT')
                if unit['pid']:
                    root = unit['root']
                    reader = self.platform.reader(request['deployment'],root,required=True)
                    expected = request['old_reader'] if root == request['old_source'] else value['reader']
                    # A failed start may have produced a process before STARTED was persisted.
                    if expected is None:
                        require(root == request['source'] and reader['pid'] == unit['pid']
                            and (reader['pid'],reader['start_ticks']) !=
                                (request['old_reader']['pid'],request['old_reader']['start_ticks'])
                            and owns_loop_lock(reader,Path(request['pass_lock']).with_suffix('.maintenance-loop')),
                            'READER_ROLLBACK_PROCESS_UNOWNED')
                    else: require(reader == expected and unit['pid'] == expected['pid'], 'READER_ROLLBACK_PROCESS_CHANGED')
                    self.platform.control('stop')
                self.stopped(request)
                for item in request['selectors']:
                    replace_exact(item['path'],item['new'].encode(),item['old'].encode())
                replace_exact(request['dropin'],request['new_dropin'].encode(),
                    None if old['stable'] is None else old['stable'].encode())
                self.platform.control('daemon-reload'); self.unit_matches(request,new=False,stopped=True)
                self.advance(value,'ROLLBACK_RESTORED')
                self.advance(value,'ROLLBACK_START_REQUESTED')
        self.unit_matches(request,new=False); self.selectors(request,'old')
        if value['phase'] == 'ROLLBACK_RESTORED': self.advance(value,'ROLLBACK_START_REQUESTED')
        if not self.platform.unit()['pid']: self.platform.control('start')
        reader = self.platform.ready(request,request['old_source'],previous=request['old_reader'])
        self.platform.final(request,restoring=True)
        self.advance(value,'ROLLED_BACK',reader=reader)
        return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prepare = commands.add_parser('prepare')
    for name in ('deployment','source','image','qualification','qualification-sha256','application-receipt',
                 'operation-id','host-qualification','host-qualification-sha256'):
        prepare.add_argument('--'+name,required=True)
    for name in ('prepare','resume','rollback','status'):
        sub = prepare if name == 'prepare' else commands.add_parser(name)
        sub.add_argument('--operation-dir',required=True)
        if name in {'resume','rollback'}: sub.add_argument('--pass-wait-seconds',type=int,default=0)
    args = parser.parse_args(argv)
    try:
        operation = Handover(args.operation_dir)
        if args.command == 'prepare':
            value = operation.prepare(deployment=args.deployment,source=args.source,image=args.image,
                qualification_path=args.qualification,qualification_sha256=args.qualification_sha256,
                application_receipt=args.application_receipt,operation_id=args.operation_id,
                host_qualification_path=args.host_qualification,
                host_qualification_sha256=args.host_qualification_sha256)
        elif args.command == 'resume': value = operation.resume(args.pass_wait_seconds)
        elif args.command == 'rollback': value = operation.rollback(args.pass_wait_seconds)
        else: value = operation.read()
        print(json.dumps(dict(schema=SCHEMA,operation_id=value['request']['operation_id'],
            phase=value['phase'],reader=value['reader']),sort_keys=True))
        return 0
    except (DeliveryRefused,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print('REFUSED: '+(str(exc) if isinstance(exc,DeliveryRefused) else type(exc).__name__))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
