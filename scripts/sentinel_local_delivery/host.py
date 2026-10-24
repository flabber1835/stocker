"""Explicit host operations; imports perform no subprocess or environment read."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from .model import DeliveryRefused, atomic_json, digest, read_json, require

SERVICES = ('sentinel-shadow', 'sentinel-automation', 'sentinel-panel',
            'sentinel-alert-dispatcher')
COMPOSE = ('docker-compose.sentinel.yml', 'docker-compose.sentinel-automation.yml',
           'docker-compose.sentinel-local-paper.yml')
RUNTIME_KEYS = frozenset({'SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST',
    'SENTINEL_TEST_IMAGE_DIGEST', 'SENTINEL_RUNTIME_IMAGE_REF', 'SENTINEL_LOCAL_PAPER_IMAGE',
    'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', 'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256'})


class Host:
    def __init__(self, request, operation_dir):
        self.request = request
        self.source = Path(request['source']).resolve()
        self.deployment = Path(request['deployment']).resolve()
        self.operation_dir = Path(operation_dir).resolve()
        self.clean = {key:value for key,value in os.environ.items()
                      if key in {'HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TZ'}}
        spec = importlib.util.spec_from_file_location('literal_delivery_env', self.source/'scripts/sentinel_env.py')
        self.literal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.literal)

    def run(self, argv, *, env=None, data=None, timeout=90):
        argv=list(argv)
        owned_name=None
        if argv[:2]==['docker','run']:
            owned_name='sentinel-delivery-probe-'+uuid.uuid4().hex
            argv[2:2]=['--name',owned_name,'--label',
                'sentinel.local-delivery.request='+digest(self.request)]
        try:
            result = subprocess.run(argv, env=self.clean if env is None else env,
                input=data, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if owned_name is not None:
                self._cleanup_owned(owned_name)
                raise DeliveryRefused('BOUNDED_HOST_OPERATION_TIMED_OUT') from exc
            raise
        if result.returncode:
            # Expanded child errors may contain secrets. Keep them owner-private.
            path = self.operation_dir/'private-command-error.log'
            with path.open('wb') as stream:
                os.chmod(path, 0o600)
                stream.write(result.stdout+b'\n'+result.stderr)
            raise DeliveryRefused('CHILD_OPERATION_REFUSED')
        return result

    def _cleanup_owned(self, name):
        inspected = subprocess.run(['docker','inspect',name],env=self.clean,
            capture_output=True,timeout=15)
        if inspected.returncode==0:
            item=json.loads(inspected.stdout)[0]
            require(item['Config']['Labels'].get('sentinel.local-delivery.request')
                    ==digest(self.request), 'PROOF_CLEANUP_OWNERSHIP_CHANGED')
            self.run(['docker','rm','-f',name],timeout=20)

    def git(self, *args):
        metadata = self.source/'.git'
        if metadata.is_file():
            text = metadata.read_text().strip()
            require(text.startswith('gitdir: '), 'GIT_METADATA_SHAPE')
            raw = text.removeprefix('gitdir: ')
            if os.name != 'nt' and re.match(r'^[A-Za-z]:[\\/]', raw):
                raw = '/mnt/'+raw[0].lower()+'/'+raw[3:].replace('\\','/')
            metadata = Path(raw)
            if not metadata.is_absolute():
                metadata = self.source/metadata
        result = self.run(['git', '--no-optional-locks', '--git-dir', str(metadata),
                          '--work-tree', str(self.source), *args])
        return result.stdout.decode().strip()

    def load_values(self):
        values = self.literal.operational_values(self.literal.load(self.deployment/'.env', required=True))
        require(values.get('ALPACA_BASE_URL') == 'https://paper-api.alpaca.markets'
            and values.get('SENTINEL_LOCAL_PAPER_MODE') == 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
            and re.fullmatch(r'PA[A-Za-z0-9]+', values.get('SENTINEL_LOCAL_PAPER_ACCOUNT_ID',''))
            and values.get('SENTINEL_PAPER_BUY_POLICY') == 'PROTECTED_LIMIT_DAY_V1'
            and values.get('SENTINEL_PAPER_BUY_CAP_BPS') == '100'
            and not values.get('SENTINEL_PAPER_DEBUG_WINDOW'), 'LOCAL_PAPER_ENVELOPE_CHANGED')
        return values

    def compose(self, values, *args, timeout=90):
        command = ['docker','compose','--profile','*','--project-name','sentinel',
                   '--project-directory',str(self.deployment),'--env-file','/dev/null']
        for name in COMPOSE:
            command += ['-f',str(self.deployment/name)]
        arguments = list(args)
        owned_name = None
        if arguments and arguments[0]=='run':
            owned_name = 'sentinel-delivery-proof-'+uuid.uuid4().hex
            arguments[1:1] = ['--name',owned_name,'--label',
                'sentinel.local-delivery.request='+digest(self.request)]
        try:
            return self.run(command+arguments,env=dict(self.clean, **values),timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if owned_name is not None:
                # The timed-out CLI may have left its one-off proof running.
                # Scope cleanup to this invocation's random name and request.
                self._cleanup_owned(owned_name)
            raise DeliveryRefused('BOUNDED_HOST_OPERATION_TIMED_OUT') from exc

    def sql(self, statement):
        result = self.run(['docker','exec','sentinel-sentinel-postgres-1','psql',
            '-XqAt','-v','ON_ERROR_STOP=1','-U','sentinel','-d','sentinel','-c',
            "BEGIN READ ONLY; SET LOCAL statement_timeout='15000ms'; "
            "SET LOCAL lock_timeout='1000ms'; SET LOCAL work_mem='4MB'; "
            "SET LOCAL max_parallel_workers_per_gather=0; "+statement+'; ROLLBACK;'],timeout=25)
        return json.loads(result.stdout)

    def container(self, service):
        require(service in (*SERVICES,'sentinel-postgres'), 'SERVICE_OUTSIDE_DELIVERY_SCOPE')
        return json.loads(self.run(['docker','inspect','sentinel-'+service+'-1']).stdout)[0]

    def postgres(self):
        data = self.container('sentinel-postgres')
        mounts = [m for m in data['Mounts'] if m['Destination']=='/var/lib/postgresql/data']
        require(data['State']['Running'] and len(mounts)==1
            and mounts[0]['Type']=='volume' and mounts[0]['Name']=='sentinel_sentinel_pgdata',
            'POSTGRES_IDENTITY_CHANGED')
        require(data['Config']['Cmd']==['postgres','-c','archive_mode=off','-c','archive_command='],
                'POSTGRES_DURABILITY_POLICY_CHANGED')
        actual = dict(container=data['Id'],image=data['Image'],started=data['State']['StartedAt'],
                      volume=mounts[0]['Name'],source=mounts[0]['Source'],command=data['Config']['Cmd'])
        require(actual==self.request['predecessor']['postgres'], 'POSTGRES_PHYSICAL_IDENTITY_CHANGED')
        return actual

    def probe(self, commit, image, values=None):
        selected = self.load_values() if values is None else values
        rendered = json.loads(self.compose(selected, 'config', '--format', 'json').stdout)
        environment = rendered['services']['sentinel-shadow']['environment']
        config = {key:environment[key] for key in (
            'SENTINEL_SHADOW_OBSERVATION_ID', 'SENTINEL_SHADOW_STARTING_CASH',
            'SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY')}
        code = '''import hashlib,json,re,sys
from decimal import Decimal
from sentinel import identity,shadow_runtime
config=json.loads(sys.argv[1])
name=config['SENTINEL_SHADOW_OBSERVATION_ID'].strip()
cash=Decimal(config['SENTINEL_SHADOW_STARTING_CASH'].strip())
assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}',name)
assert cash.is_finite() and cash>0
assert config['SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY']==shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY
r=identity.rehearsal_identity()
assert r['environment']['compatible'] is True
c=dict(schema='sentinel.shadow-reviewed-config/1',observation_id=name,starting_cash=format(cash.normalize(),'f'),execution_model=shadow_runtime.SHADOW_EXECUTION_MODEL,cutoff_policy=shadow_runtime.SHADOW_CUTOFF_POLICY,publication_timing_policy=shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,validated_source_identity_sha256=r['identity_hash'])
print(json.dumps(dict(source=r['identity_hash'],shadow_config=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest(),wealth=r['environment']['wealth_core_source']['hash'])))
'''
        return json.loads(self.run(['docker','run','--rm','--pull=never','--network','none',
            '--cpus','0.5','--memory','384m','-e','SENTINEL_GIT_COMMIT='+commit,
            '-e','SENTINEL_RUNTIME_IMAGE_DIGEST='+image,'-e','SENTINEL_TEST_IMAGE_DIGEST='+image,
            '--entrypoint','python',image,'-B','-c',code,json.dumps(config,sort_keys=True)],timeout=90).stdout)

    def verify_candidate(self):
        selected = self.request['candidate']; old = self.request['predecessor']
        require(self.git('rev-parse','HEAD')==selected['commit']
                and not self.git('status','--porcelain'), 'CANDIDATE_SOURCE_NOT_CLEAN')
        require(self.git('merge-base',old['commit'],selected['commit'])==old['commit'],
                'CANDIDATE_NOT_DESCENDANT')
        changed = self.git('diff','--name-only',old['commit'],selected['commit']).splitlines()
        require(sorted(changed)==sorted(self.request['allowed_delta']), 'CANDIDATE_DELTA_CHANGED')
        for name in COMPOSE:
            require((self.source/name).read_bytes()==(self.deployment/name).read_bytes(),
                    'INSTALLED_COMPOSE_CHANGED')
        metadata = json.loads(self.run(['docker','image','inspect',selected['image']]).stdout)[0]
        require(metadata['Id']==selected['image']
            and metadata['Config']['Labels']['org.opencontainers.image.revision']==selected['commit'],
            'CANDIDATE_IMAGE_CHANGED')
        require(self.probe(selected['commit'],selected['image'])==selected['source_identity'],
                'CANDIDATE_SOURCE_IDENTITY_CHANGED')
        qualification = self.request['qualification']
        from .qualification import validate_report
        report = validate_report(qualification['report_path'],qualification['report_sha256'],
            self.source,selected['commit'],old['commit'])
        require(qualification['commit']==selected['commit'] and qualification['passed'] is True,
                'CANDIDATE_QUALIFICATION_ABSENT')
        require(report['source_files']==qualification['source_files'],
                'CANDIDATE_QUALIFICATION_SUBJECT_CHANGED')
        for name, expected in qualification['source_files'].items():
            require(hashlib.sha256((self.source/name).read_bytes()).hexdigest()==expected,
                    'QUALIFIED_SOURCE_BYTES_CHANGED')
        return selected['source_identity']

    def candidate_values(self, values):
        selected = self.request['candidate']; identity = selected['source_identity']
        result = dict(values,SENTINEL_GIT_COMMIT=selected['commit'],
            SENTINEL_RUNTIME_IMAGE_DIGEST=selected['image'],SENTINEL_TEST_IMAGE_DIGEST=selected['image'],
            SENTINEL_RUNTIME_IMAGE_REF=selected['image'],SENTINEL_LOCAL_PAPER_IMAGE=selected['image'],
            SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256=identity['source'],
            SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256=identity['shadow_config'])
        require(all(values.get(k)==result.get(k) for k in set(values)|set(result) if k not in RUNTIME_KEYS),
                'NON_RUNTIME_CONFIGURATION_CHANGED')
        return result

    def install_values(self, previous, candidate):
        require(self.load_values()==previous, 'ENVIRONMENT_CHANGED_BEFORE_INSTALL')
        require(all(previous.get(k)==candidate.get(k) for k in set(previous)|set(candidate)
                    if k not in RUNTIME_KEYS), 'NON_RUNTIME_CONFIGURATION_CHANGED')
        raw = ''.join(k+'='+json.dumps(v,ensure_ascii=False)+'\n' for k,v in sorted(candidate.items()))
        require(self.literal.parse_bytes(raw.encode())==candidate, 'LITERAL_ENV_ROUNDTRIP_FAILED')
        # The private temporary file is in the same directory for atomic replace.
        import tempfile
        fd, name = tempfile.mkstemp(prefix='.env.local-delivery-',dir=self.deployment)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            Path(name).replace(self.deployment/'.env')
        finally:
            if Path(name).exists(): Path(name).unlink()
        path = self.deployment/'local-delivery.json'
        metadata = read_json(path)
        metadata.update(commit=self.request['candidate']['commit'],image=self.request['candidate']['image'],
                        identity=self.request['candidate']['source_identity'])
        atomic_json(path,metadata)

    @contextmanager
    def owned(self):
        import fcntl
        path = self.deployment/'.local-delivery.lock'
        require(not path.is_symlink(), 'DELIVERY_LOCK_PATH_UNSAFE')
        with path.open('a+b') as stream:
            os.chmod(path,0o600)
            try:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeliveryRefused('ANOTHER_DELIVERY_OWNS_HOST') from exc
            try:
                yield
            finally:
                fcntl.flock(stream,fcntl.LOCK_UN)
