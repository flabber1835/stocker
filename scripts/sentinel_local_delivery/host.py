"""Explicit host operations; imports perform no subprocess or environment read."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from .model import COMPAT_DRAIN_PREDECESSOR, DeliveryRefused, atomic_json, digest, handoff_mode, read_json, require

SERVICES = ('sentinel-shadow', 'sentinel-automation', 'sentinel-panel',
            'sentinel-alert-dispatcher','sentinel-verifier','sentinel-execution-collector')
LEGACY_SERVICES = SERVICES[:4]
COMPOSE = ('docker-compose.sentinel.yml', 'docker-compose.sentinel-automation.yml',
           'docker-compose.sentinel-local-paper.yml')
RUNTIME_KEYS = frozenset({'SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST',
    'SENTINEL_TEST_IMAGE_DIGEST', 'SENTINEL_RUNTIME_IMAGE_REF', 'SENTINEL_LOCAL_PAPER_IMAGE',
    'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', 'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256'})


def _immutable_git(args):
    sha = lambda value: isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) is not None
    if len(args)==3 and args[0]=='merge-base':
        return all(sha(value) for value in args[1:])
    if len(args) in {4,5} and args[:2]==('diff','--name-only'):
        return ((len(args)==4 or args[2]=='-z') and all(sha(value) for value in args[-2:]))
    if len(args)==5 and args[:4]==('ls-tree','-r','--name-only','-z'):
        return sha(args[4])
    if len(args)==2 and args[0]=='show' and ':' in args[1]:
        commit,name=args[1].split(':',1)
        return sha(commit) and name in COMPOSE
    return False


def application_healthy(item, image):
    if not isinstance(item,dict): return False
    state=item.get('State')
    if not isinstance(state,dict): return False
    health=state.get('Health')
    return (item.get('Image')==image and state.get('Running') is True
        and isinstance(health,dict) and health.get('Status')=='healthy'
        and state.get('OOMKilled') is False and state.get('Restarting') is False)


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

    def run(self, argv, *, env=None, data=None, timeout=90, cleanup_image=None):
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
                if cleanup_image is None:self._cleanup_owned(owned_name)
                else:
                    primary=DeliveryRefused('BOUNDED_HOST_OPERATION_TIMED_OUT')
                    primary.__cause__=exc
                    try:self._cleanup_owned(owned_name,image=cleanup_image)
                    except DeliveryRefused as secondary:raise secondary from primary
                raise DeliveryRefused('BOUNDED_HOST_OPERATION_TIMED_OUT') from exc
            raise
        except OSError as exc:
            if owned_name is None or cleanup_image is None:raise
            primary=DeliveryRefused('CHILD_OPERATION_OUTCOME_UNKNOWN')
            primary.__cause__=exc
            try:self._cleanup_owned(owned_name,image=cleanup_image)
            except DeliveryRefused as secondary:raise secondary from primary
            raise primary from exc
        if result.returncode:
            # Expanded child errors may contain secrets. Keep them owner-private.
            path = self.operation_dir/('private-command-error-'+uuid.uuid4().hex+'.log')
            with path.open('xb') as stream:
                os.chmod(path, 0o600)
                stream.write(result.stdout+b'\n'+result.stderr)
                stream.flush()
                os.fsync(stream.fileno())
            primary=DeliveryRefused('CHILD_OPERATION_REFUSED: '+path.name)
            if owned_name is not None and cleanup_image is not None:
                try:self._cleanup_owned(owned_name,image=cleanup_image)
                except DeliveryRefused as secondary:raise secondary from primary
            raise primary
        return result

    def _cleanup_owned(self, name, *, image=None):
        deadline=time.monotonic()+15
        try:
            inspected = subprocess.run(['docker','inspect',name],env=self.clean,
                capture_output=True,timeout=15)
        except (OSError,subprocess.TimeoutExpired):
            if image is None:raise
            raise DeliveryRefused('PROOF_CLEANUP_OUTCOME_UNKNOWN') from None
        if inspected.returncode==0:
            item=json.loads(inspected.stdout)[0]
            require(item['Config']['Labels'].get('sentinel.local-delivery.request')
                    ==digest(self.request), 'PROOF_CLEANUP_OWNERSHIP_CHANGED')
            require(image is None or item.get('Image')==image,'PROOF_CLEANUP_IMAGE_CHANGED')
            target=name
            if image is not None:
                require(item.get('Name')=='/'+name and isinstance(item.get('Id'),str)
                    and re.fullmatch('[0-9a-f]{64}',item['Id']) is not None,
                    'PROOF_CLEANUP_TARGET_CHANGED')
                target=item['Id']
            self.run(['docker','rm','-f',target],timeout=20)
        elif image is not None:
            remaining=deadline-time.monotonic()
            require(remaining>0,'PROOF_CLEANUP_OUTCOME_UNKNOWN')
            try:
                absent=subprocess.run(['docker','container','ls','--all','--quiet','--no-trunc',
                    '--filter','name=^/'+re.escape(name)+'$'],env=self.clean,
                    capture_output=True,timeout=remaining)
            except (OSError,subprocess.TimeoutExpired):
                raise DeliveryRefused('PROOF_CLEANUP_OUTCOME_UNKNOWN') from None
            require(absent.returncode==0 and not absent.stdout.strip(),'PROOF_CLEANUP_OUTCOME_UNKNOWN')

    def git_bytes(self, *args):
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
        immutable=_immutable_git(args)
        if immutable:
            common=metadata
            if (metadata/'commondir').is_file():
                common=Path((metadata/'commondir').read_text().strip())
                if not common.is_absolute(): common=metadata/common
            for folder in {metadata,common}:
                graft=folder/'info/grafts'
                require(not graft.exists() and not graft.is_symlink(),'IMMUTABLE_GIT_GRAFTS_REFUSED')
            facts=getattr(self,'_git_object_facts',{})
            if args in facts:
                return facts[args]
        result = self.run(['git', *(['--no-replace-objects'] if immutable else []),
                          '--no-optional-locks', '--git-dir', str(metadata),
                          '--work-tree', str(self.source), *args])
        if immutable:
            self._git_object_facts={**facts,args:result.stdout}
        return result.stdout

    def git(self, *args):
        return self.git_bytes(*args).decode().strip()

    def image_metadata(self, reference, *, fresh=False):
        """Memo immutable bytes, never a mutable tag or mutation-time presence."""
        immutable=isinstance(reference,str) and re.fullmatch(r'(?:[^\s]+@)?sha256:[0-9a-f]{64}',reference)
        facts=getattr(self,'_image_metadata_facts',{})
        if immutable and not fresh and reference in facts:
            return deepcopy(facts[reference])
        values=json.loads(self.run(['docker','image','inspect',reference]).stdout)
        require(isinstance(values,list) and len(values)==1 and isinstance(values[0],dict),
                'IMAGE_INSPECTION_SHAPE')
        value=values[0]
        require(isinstance(value.get('Id'),str) and re.fullmatch(r'sha256:[0-9a-f]{64}',value['Id'])
            and isinstance(value.get('Config'),dict),'IMAGE_INSPECTION_SHAPE')
        if immutable:
            require(value['Id']==reference if reference.startswith('sha256:') else
                isinstance(value.get('RepoDigests'),list) and reference in value['RepoDigests'],
                'IMAGE_INSPECTION_SUBJECT_CHANGED')
            self._image_metadata_facts={**facts,reference:deepcopy(value),value['Id']:deepcopy(value)}
        return deepcopy(value)

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
        for path in self.compose_paths(values):
            command += ['-f',str(path)]
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

    def predecessor_services(self):
        return LEGACY_SERVICES if self.request['predecessor']['commit'] == COMPAT_DRAIN_PREDECESSOR else SERVICES

    def verify_compose(self, role):
        for name in COMPOSE:
            expected = ((self.source/name).read_bytes() if role=='candidate' else
                        self.git_bytes('show',self.request['predecessor']['commit']+':'+name))
            require((self.deployment/name).read_bytes()==expected,'INSTALLED_COMPOSE_STAGE_CHANGED')

    def compose_paths(self, values):
        """Render immutable old Git inputs or the qualified candidate inputs."""
        if values.get('SENTINEL_GIT_COMMIT') == self.request['candidate']['commit']:
            return tuple(self.source/name for name in COMPOSE)
        require(values.get('SENTINEL_GIT_COMMIT') == self.request['predecessor']['commit'],
                'COMPOSE_RUNTIME_OUTSIDE_REQUEST')
        folder = self.operation_dir/'predecessor-compose-inputs'
        require(not folder.is_symlink(),'COMPOSE_INPUT_DIRECTORY_UNSAFE')
        folder.mkdir(mode=0o700,exist_ok=True)
        paths = []
        for name in COMPOSE:
            raw = self.git_bytes('show',self.request['predecessor']['commit']+':'+name)
            target = folder/name
            require(not target.is_symlink(),'COMPOSE_INPUT_PATH_UNSAFE')
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            require(target.read_bytes()==raw,'PREDECESSOR_COMPOSE_INPUT_CHANGED')
            paths.append(target)
        return tuple(paths)

    def install_compose(self):
        """Repeatable exact qualified file installation after application stop."""
        import tempfile
        for name in COMPOSE:
            raw = (self.source/name).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == self.request['qualification']['source_files'][name],
                    'COMPOSE_SOURCE_NOT_QUALIFIED')
            target = self.deployment/name
            require(not target.is_symlink(),'COMPOSE_TARGET_UNSAFE')
            old = self.git_bytes('show',self.request['predecessor']['commit']+':'+name)
            require(target.read_bytes() in (old,raw),'COMPOSE_TARGET_CHANGED')
            fd, temporary = tempfile.mkstemp(prefix='.compose-delivery-',dir=self.deployment)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary,target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        require(all((self.deployment/name).read_bytes()==(self.source/name).read_bytes() for name in COMPOSE),
                'COMPOSE_INSTALL_INCOMPLETE')
        directory = os.open(self.deployment,os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    @contextmanager
    def private_environment(self, values):
        import tempfile
        require(all('\n' not in value and '\r' not in value for value in values.values()),
                'PRIVATE_ENVIRONMENT_MULTILINE')
        fd, name = tempfile.mkstemp(prefix='.delivery-private-env-',dir=self.operation_dir)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                os.fchmod(stream.fileno(),0o600)
                stream.write(''.join(key+'='+value+'\n' for key,value in sorted(values.items())))
                stream.flush(); os.fsync(stream.fileno())
            yield name
        finally:
            Path(name).unlink(missing_ok=True)

    def container(self, service, *, missing_ok=False):
        require(service in (*SERVICES,'sentinel-postgres'), 'SERVICE_OUTSIDE_DELIVERY_SCOPE')
        if missing_ok:
            matches=self.run(['docker','container','ls','--all','--quiet','--no-trunc',
                '--filter','name=^/sentinel-'+service+'-1$']).stdout.decode().splitlines()
            require(len(matches)<=1,'APPLICATION_CONTAINER_AMBIGUOUS')
            if not matches:
                return None
        return json.loads(self.run(['docker','inspect','sentinel-'+service+'-1']).stdout)[0]

    def wait_application_health(self, service, *, deadline, clock=time.monotonic):
        """Events replace inspection polling; only fresh exact state proves health."""
        return self._wait_health((service,),deadline=deadline,clock=clock)

    def wait_applications_health(self, *, deadline, clock=time.monotonic, expected=None):
        return self._wait_health(SERVICES,deadline=deadline,clock=clock,expected=expected)

    def _wait_health(self, services, *, deadline, clock, expected=None):
        from . import docker_health

        require(services and all(service in SERVICES for service in services),
                'SERVICE_OUTSIDE_DELIVERY_SCOPE')
        try:
            remaining = docker_health._remaining(deadline, clock)
            context = self.run(['docker','context','inspect'],
                timeout=min(docker_health.IO_SECONDS, remaining))
            require(len(context.stdout) <= docker_health.MAX_HEADERS,
                'ENGINE_CONTEXT_EXCEEDS_BOUND')
            docker_health.require_context(docker_health._json(context.stdout))
            engine = docker_health.Engine(clock=clock)
            engine.version(deadline)
            if len(services)==1:
                return docker_health.wait(engine, 'sentinel-'+services[0]+'-1',
                    self.request['candidate']['image'], deadline, clock=clock)
            values=docker_health.wait_many(engine,tuple('sentinel-'+service+'-1' for service in services),
                self.request['candidate']['image'],deadline,clock=clock,
                expected={('sentinel-'+key+'-1'):value for key,value in expected.items()} if expected else None)
            return {service:values['sentinel-'+service+'-1'] for service in services}
        except docker_health._Deadline as exc:
            raise DeliveryRefused('SHADOW_STARTUP_DEADLINE' if len(services)==1
                else 'APPLICATION_READINESS_DEADLINE') from exc
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise DeliveryRefused('ENGINE_HEALTH_OBSERVATION_UNAVAILABLE') from exc

    def containers(self, services, *, missing_ok=False):
        """One fresh boundary observation; no container state is retained."""
        services=tuple(services)
        require(services and len(services)==len(set(services))
            and all(name in SERVICES for name in services),'SERVICE_OUTSIDE_DELIVERY_SCOPE')
        names={'sentinel-'+service+'-1':service for service in services}
        identities=None
        if missing_ok:
            pattern='^/(?:'+'|'.join(re.escape(name) for name in names)+')$'
            lines=self.run(['docker','container','ls','--all','--no-trunc','--format','{{json .}}',
                '--filter','name='+pattern]).stdout.decode().splitlines()
            identities={}
            for line in lines:
                value=json.loads(line)
                require(isinstance(value,dict) and value.get('Names') in names
                    and isinstance(value.get('ID'),str) and value['ID']
                    and value['Names'] not in identities,'APPLICATION_CONTAINER_AMBIGUOUS')
                identities[value['Names']]=value['ID']
            if not identities: return dict.fromkeys(services)
            targets=list(identities.values())
        else:
            targets=list(names)
        observed=json.loads(self.run(['docker','container','inspect',*targets]).stdout)
        require(isinstance(observed,list),'APPLICATION_CONTAINER_OBSERVATION_MALFORMED')
        result=dict.fromkeys(services)
        for item in observed:
            require(isinstance(item,dict) and isinstance(item.get('Name'),str)
                and isinstance(item.get('Id'),str) and item['Id']
                and isinstance(item.get('Image'),str) and isinstance(item.get('State'),dict),
                'APPLICATION_CONTAINER_OBSERVATION_MALFORMED')
            name=item['Name'].removeprefix('/')
            require(item['Name']=='/'+name and name in names and result[names[name]] is None,
                'APPLICATION_CONTAINER_AMBIGUOUS')
            require(identities is None or identities.get(name)==item.get('Id'),
                'APPLICATION_CONTAINER_CHANGED_DURING_OBSERVATION')
            result[names[name]]=item
        expected=set(names if identities is None else identities)
        require({name for name,service in names.items() if result[service] is not None}==expected,
            'APPLICATION_CONTAINER_MISSING')
        return result

    def candidate_config_hashes(self, values):
        """Render current configuration once, before observing running roles."""
        try:
            output=self.compose(values,'config','--hash','*',timeout=90).stdout.decode()
            hashes={}
            for line in output.splitlines():
                fields=line.split()
                if (len(fields)!=2 or fields[0] in hashes
                        or re.fullmatch('[0-9a-f]{64}',fields[1]) is None):
                    return None
                hashes[fields[0]]=fields[1]
        except (DeliveryRefused,UnicodeError,ValueError,TypeError):
            return None
        return hashes if all(name in hashes for name in SERVICES) else None

    def candidate_apps_ready(self, hashes, applications):
        """Positive proof of a completed software start, never financial readiness."""
        if (not isinstance(hashes,dict) or any(not isinstance(hashes.get(name),str)
                or re.fullmatch('[0-9a-f]{64}',hashes[name]) is None for name in SERVICES)):
            return False
        image=self.request['candidate']['image']
        for service in SERVICES:
            item=applications.get(service)
            if not application_healthy(item,image): return False
            config=item.get('Config')
            if not isinstance(config,dict): return False
            labels=config.get('Labels')
            if (not isinstance(labels,dict)
                    or labels.get('com.docker.compose.project')!='sentinel'
                    or labels.get('com.docker.compose.service')!=service
                    or labels.get('com.docker.compose.config-hash')!=hashes.get(service)):
                return False
        return True

    def observe_drain(self, target, container, request, *, started_at, accept_until, deadline):
        """One owned canonical reader, exact volume read only and no network."""
        require(container['Id']==target['container'] and container['Image']==target['image'],
            'DRAIN_OBSERVER_TARGET_CHANGED')
        mounts=[item for item in container['Mounts'] if item['Destination']=='/var/lib/sentinel']
        require(len(mounts)==1 and mounts[0]['Type']=='volume'
            and mounts[0]['Name']=='sentinel_sentinel_state','DRAIN_OBSERVER_VOLUME_CHANGED')
        allowed={'SENTINEL_GIT_COMMIT','SENTINEL_RUNTIME_IMAGE_DIGEST',
            'SENTINEL_SHADOW_OBSERVATION_ID','SENTINEL_DATABASE_URL','SENTINEL_PUBLICATION_RECEIPT_KEY'}
        environment={}
        for item in container['Config']['Env']:
            key,separator,value=item.partition('=')
            if key in allowed:
                require(separator and key not in environment,'DRAIN_OBSERVER_ENVIRONMENT_AMBIGUOUS')
                environment[key]=value
        require(set(environment)==allowed and all(environment.values())
            and environment['SENTINEL_GIT_COMMIT']==self.request['predecessor']['commit']
            and environment['SENTINEL_RUNTIME_IMAGE_DIGEST']==target['image'],
            'DRAIN_OBSERVER_ENVIRONMENT_CHANGED')
        environment['SENTINEL_STATE_DIR']='/var/lib/sentinel'
        user=container['Config'].get('User') or '0'
        require(isinstance(user,str) and re.fullmatch(
            '[A-Za-z0-9_][A-Za-z0-9_.-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*)?',user) is not None,
            'DRAIN_OBSERVER_USER_INVALID')
        image=self.request['candidate']['image']
        require(re.fullmatch('sha256:[0-9a-f]{64}',image or '') is not None,
            'DRAIN_OBSERVER_IMAGE_INVALID')
        with self.private_environment(environment) as path:
            remaining=deadline-time.monotonic()
            require(0<remaining<=180,'DRAIN_ACKNOWLEDGEMENT_DEADLINE')
            result=self.run(['docker','run','--rm','-i','--pull=never','--network','none',
                '--read-only','--user',user,'--cpus','0.25','--memory','128m','--pids-limit','16',
                '--cap-drop','ALL','--security-opt','no-new-privileges:true','--env-file',path,
                '--mount','type=volume,src=sentinel_sentinel_state,dst=/var/lib/sentinel,readonly',
                '--entrypoint','python',image,'-B','-m','sentinel.shadow_drain_observer',
                '--started-at',started_at.isoformat(),'--accept-until',accept_until.isoformat(),
                '--timeout',str(remaining)],data=json.dumps(request,sort_keys=True).encode(),
                timeout=remaining,cleanup_image=image)
        acknowledgement=json.loads(result.stdout)
        require(isinstance(acknowledgement,dict),'DRAIN_OBSERVER_RESULT_MALFORMED')
        return acknowledgement

    def drain_recovery_state(self, target, values):
        """Read exact predecessor markers without starting or mutating it."""
        item=self.container('sentinel-shadow')
        require(item['Id']==target['container'] and item['Image']==target['image'],
                'ABANDONMENT_TARGET_CHANGED')
        mounts=[m for m in item['Mounts'] if m['Destination']=='/var/lib/sentinel']
        require(len(mounts)==1 and mounts[0]['Type']=='volume'
            and mounts[0]['Name']=='sentinel_sentinel_state','ABANDONMENT_STATE_VOLUME_CHANGED')
        config=json.loads(self.compose(values,'config','--format','json').stdout)
        environment=config['services']['sentinel-shadow']['environment']
        code='''import hashlib,json,math
from pathlib import Path
from sentinel import shadow_restart_recovery as recovery,shadow_service_status as status
state=Path('/var/lib/sentinel')
result={}
for kind,name in [('pending',status.PENDING_NAME),('critical',status.CRITICAL_NAME)]:
    path=state/name
    try:raw=recovery._raw(path)
    except FileNotFoundError:result[kind]=None;continue
    value=json.loads(raw)
    if kind=='pending':status._decode_pending(raw)
    else:
        assert isinstance(value,dict) and set(value)=={'schema','reason','failures','latched_at_unix'}
        assert value['schema']=='sentinel.shadow-supervisor-critical/1' and isinstance(value['reason'],str)
        assert value['failures'] is None or type(value['failures']) is int and value['failures']>=0
        assert type(value['latched_at_unix']) in {int,float} and math.isfinite(value['latched_at_unix']) and value['latched_at_unix']>0
    result[kind]={'schema':value['schema'],'sha256':hashlib.sha256(raw).hexdigest()}
print(json.dumps(result,sort_keys=True))
'''
        with self.private_environment(environment) as path:
            result=self.run(['docker','run','--rm','--pull=never','--network','none',
                '--read-only','--cpus','0.25','--memory','128m','--env-file',path,'--mount',
                'type=volume,src='+mounts[0]['Name']+',dst=/var/lib/sentinel,readonly',
                '--entrypoint','python',target['image'],'-B','-c',code],timeout=15)
        value=json.loads(result.stdout)
        require(isinstance(value,dict) and set(value)=={'pending','critical'},
                'ABANDONMENT_MARKER_OBSERVATION_MALFORMED')
        for kind,schemas in (('pending',{'sentinel.shadow-supervisor-pending/2',
                                        'sentinel.shadow-supervisor-pending/3'}),
                             ('critical',{'sentinel.shadow-supervisor-critical/1'})):
            entry=value[kind]
            require(entry is None or isinstance(entry,dict) and set(entry)=={'schema','sha256'}
                and entry['schema'] in schemas and isinstance(entry['sha256'],str)
                and re.fullmatch('[0-9a-f]{64}',entry['sha256']),
                'ABANDONMENT_MARKER_OBSERVATION_MALFORMED')
        return value

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
        require(re.fullmatch('[0-9a-f]{40}',commit or '') is not None
            and re.fullmatch('sha256:[0-9a-f]{64}',image or '') is not None,
            'IMAGE_IDENTITY_PROBE_SUBJECT_INVALID')
        selected = self.load_values() if values is None else values
        rendered = json.loads(self.compose(selected, 'config', '--format', 'json').stdout)
        environment = rendered['services']['sentinel-shadow']['environment']
        config = {key:environment[key] for key in (
            'SENTINEL_SHADOW_OBSERVATION_ID', 'SENTINEL_SHADOW_STARTING_CASH',
            'SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY')}
        canonical=json.dumps(config,sort_keys=True,separators=(',',':'),ensure_ascii=True)
        key=(image,commit,canonical)
        probes=getattr(self,'_image_identity_probes',{})
        if key in probes:
            return deepcopy(probes[key])
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
        result=json.loads(self.run(['docker','run','--rm','--pull=never','--network','none',
            '--cpus','0.5','--memory','384m','-e','SENTINEL_GIT_COMMIT='+commit,
            '-e','SENTINEL_RUNTIME_IMAGE_DIGEST='+image,'-e','SENTINEL_TEST_IMAGE_DIGEST='+image,
            '--entrypoint','python',image,'-B','-c',code,json.dumps(config,sort_keys=True)],timeout=90).stdout)
        require(isinstance(result,dict) and set(result)=={'source','shadow_config','wealth'}
            and all(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None
                    for value in result.values()),'IMAGE_IDENTITY_PROBE_MALFORMED')
        self._image_identity_probes={**probes,key:deepcopy(result)}
        return deepcopy(result)

    def verify_candidate(self):
        require(handoff_mode(self.request)!='POST_TRADE_SUCCESSOR'
            or getattr(self,'supports_post_trade_successor',False),
            'POST_TRADE_SUCCESSOR_BACKED_ADAPTER_REQUIRED')
        require(handoff_mode(self.request)=='PRE_OPEN' or getattr(self,'supports_post_trade',False),
                'POST_TRADE_BACKED_ADAPTER_REQUIRED')
        require(handoff_mode(self.request)!='BLOCKED_UNSENT' or getattr(self,'supports_blocked_unsent',False),
                'BLOCKED_UNSENT_BACKED_ADAPTER_REQUIRED')
        selected = self.request['candidate']; old = self.request['predecessor']
        qualification = self.request['qualification']
        from .qualification import validate_report
        report = validate_report(qualification['report_path'],qualification['report_sha256'],
            self.source,selected['commit'],old['commit'],git_reader=self.git)
        changed = self.git('diff','--name-only',old['commit'],selected['commit']).splitlines()
        require(sorted(changed)==sorted(self.request['allowed_delta']), 'CANDIDATE_DELTA_CHANGED')
        for name in COMPOSE:
            require((self.deployment/name).read_bytes() in ((self.source/name).read_bytes(),
                    self.git_bytes('show',old['commit']+':'+name)),
                    'INSTALLED_COMPOSE_CHANGED')
        metadata = self.image_metadata(selected['image'],fresh=True)
        require(metadata['Id']==selected['image']
            and metadata['Config']['Labels']['org.opencontainers.image.revision']==selected['commit'],
            'CANDIDATE_IMAGE_CHANGED')
        require(self.probe(selected['commit'],selected['image'])==selected['source_identity'],
                'CANDIDATE_SOURCE_IDENTITY_CHANGED')
        require(qualification['commit']==selected['commit'] and qualification['passed'] is True,
                'CANDIDATE_QUALIFICATION_ABSENT')
        require(report['source_files']==qualification['source_files'],
                'CANDIDATE_QUALIFICATION_SUBJECT_CHANGED')
        # validate_report already hashes the complete exact tracked input set.
        # The comparison above binds that freshly checked map to this request.
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
        require(all(previous.get(k)==candidate.get(k) for k in set(previous)|set(candidate)
                    if k not in RUNTIME_KEYS), 'NON_RUNTIME_CONFIGURATION_CHANGED')
        raw = ''.join(k+'='+json.dumps(v,ensure_ascii=False)+'\n' for k,v in sorted(candidate.items()))
        require(self.literal.parse_bytes(raw.encode())==candidate, 'LITERAL_ENV_ROUNDTRIP_FAILED')
        from . import environment
        environment.install(self,previous,raw.encode() if previous!=candidate else None)
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
