"""Explicit owner-authorized backed PAPER application roll; no broker writes.

Reuse the qualified source-layer builder and the existing digest-linked drain /
application handoff. The historical archive-off command retains its own guards.
"""
from contextlib import contextmanager, ExitStack
from datetime import date
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace

from sentinel_local_delivery import builder, checks, cli, environment
from sentinel_local_delivery.coordinator import Delivery
from sentinel_local_delivery.host import Host, SERVICES, RUNTIME_KEYS
from sentinel_local_delivery.model import ACCESS_PATH_SCHEMA, DeliveryRefused, Journal, read_json, require, digest
from sentinel_local_delivery.qualification import sha256_file
from sentinel_lock_ownership import owns_exclusive_flock

COMPOSE = ('docker-compose.sentinel.yml', 'docker-compose.sentinel-backup.yml',
           'docker-compose.sentinel-automation.yml')
IMAGE_SERVICES = (*SERVICES, 'sentinel', 'sentinel-authorized-cli')
_AUTOMATION_ENTRY = b'    entrypoint: ["python", "-m", "sentinel.automation_supervisor"]\n'
_WORKER_READ_MOUNT = b'    volumes:\n      - sentinel_state:/var/lib/sentinel:ro\n'


def _allowed_worker_mount(name, previous, candidate):
    """Only the documented literal read-only state observation addition."""
    return (name=='docker-compose.sentinel-automation.yml'
        and previous.count(_AUTOMATION_ENTRY)==candidate.count(_AUTOMATION_ENTRY)==1
        and candidate.count(_AUTOMATION_ENTRY+_WORKER_READ_MOUNT)==1
        and candidate.replace(_AUTOMATION_ENTRY+_WORKER_READ_MOUNT,_AUTOMATION_ENTRY,1)==previous)


def immutable_image_overlay(folder, image):
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', image), 'BACKED_OVERLAY_IMAGE_INVALID')
    path = folder/('application-images-'+image.removeprefix('sha256:')+'.json')
    raw = (json.dumps({'services': {name: {'image': image, 'pull_policy': 'never'}
        for name in IMAGE_SERVICES}}, sort_keys=True, separators=(',', ':'))+'\n').encode()
    require(not path.is_symlink(), 'BACKED_IMAGE_OVERLAY_UNSAFE')
    if not path.exists():
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    require(path.read_bytes()==raw, 'BACKED_IMAGE_OVERLAY_CHANGED')
    return path


def postgres_facts(item):
    mounts = [m for m in item['Mounts'] if m['Destination']=='/var/lib/postgresql/data']
    require(item['State']['Running'] and len(mounts)==1
        and mounts[0]['Type']=='volume' and mounts[0]['Name']=='sentinel_sentinel_pgdata',
        'BACKED_POSTGRES_VOLUME_CHANGED')
    require('archive_mode=on' in item['Config']['Cmd'], 'BACKED_ARCHIVE_OFF_REFUSED')
    return dict(container=item['Id'], image=item['Image'], started=item['State']['StartedAt'],
        volume=mounts[0]['Name'], source=mounts[0]['Source'], command=item['Config']['Cmd'])


def require_same_postgres_storage(before, after):
    """An observed process restart cannot replace the database or its backing."""
    keys={'container','image','started','volume','source','command'}
    require(set(before)==set(after)==keys
        and all(before[k]==after[k] for k in keys-{'started'}),
        'BACKED_POSTGRES_STORAGE_CHANGED')
    if before['started'] != after['started']:
        from datetime import datetime, timezone, timedelta
        old, new = (datetime.fromisoformat(value.replace('Z','+00:00'))
                    for value in (before['started'],after['started']))
        require(old.utcoffset() is not None and new.utcoffset() is not None
            and old<new<=datetime.now(timezone.utc)+timedelta(seconds=5),
            'BACKED_POSTGRES_RESTART_TIME_INVALID')


def _require_access_path_completion(journal, record):
    if journal.request.get('schema') == ACCESS_PATH_SCHEMA:
        from sentinel_local_delivery.access_path_qualification import require_qualification
        require_qualification(journal.request,journal.subject,record['artifacts'])


def predecessor_witness(path, *, inspect_image=None, trail=(), allow_started=False):
    """Consume completed receipts without asserting another activation."""
    seen = set(trail)
    links = []
    expected_sha256 = None
    while True:
        path = Path(path)
        require(path.is_absolute() and '..' not in path.parts
            and not any(item.is_symlink() for item in (path,*path.parents)),
            'BACKED_PREDECESSOR_PATH_UNSAFE')
        selected = path.resolve()
        require(selected not in seen, 'BACKED_PREDECESSOR_CHAIN_INVALID')
        seen.add(selected)
        actual_sha256 = sha256_file(path)
        if links:
            require(actual_sha256==expected_sha256, 'BACKED_PREDECESSOR_ANCHOR_CHANGED')
        record = read_json(selected)
        if record.get('schema')=='sentinel.activation-receipt/1':
            anchor = _activation_witness(selected, record, inspect_image)
            break
        unfinished=record.get('stage')=='APPLICATIONS_STARTED'
        require(selected.name=='receipt.json' and (record.get('stage')=='VERIFIED'
            or (allow_started and unfinished)), 'BACKED_VERIFIED_PREDECESSOR_REQUIRED')
        journal = Journal(selected.parent)
        require(journal.read()==record, 'BACKED_PREDECESSOR_JOURNAL_CHANGED')
        _require_access_path_completion(journal,record)
        request = journal.request
        if unfinished:
            require(record['artifacts'].get('successor_proof_sha256')
                ==digest(record['artifacts']['canonical_proof']), 'BACKED_STARTED_CANONICAL_PROOF_CHANGED')
        built = builder.operation_build(selected.parent)
        candidate = request['candidate']
        require(built.get('schema')==builder.BUILD_SCHEMA
            and built.get('commit')==candidate['commit'] and built.get('image')==candidate['image']
            and built.get('source_identity')==candidate['source_identity']
            and built.get('source')==request['source'] and built.get('deployment')==request['deployment']
            and built.get('foundation')==request['predecessor'], 'BACKED_PREDECESSOR_BUILD_CHANGED')
        qualification = built['qualification']
        require(qualification['report_path']==request['qualification']['report_path']
            and qualification['report_sha256']==request['qualification']['report_sha256']
            and sha256_file(qualification['report_path'])==qualification['report_sha256'],
            'BACKED_PREDECESSOR_QUALIFICATION_CHANGED')
        report = read_json(qualification['report_path'])
        require(report.get('commit')==candidate['commit'] and report.get('final') is True
            and report.get('source_files_unchanged') is True
            and report.get('source_files')==request['qualification']['source_files'],
            'BACKED_PREDECESSOR_QUALIFICATION_SUBJECT_CHANGED')
        links.append((request, record['artifacts'], unfinished))
        prior = built['predecessor_receipt']
        path, expected_sha256 = prior['path'], prior['sha256']
        allow_started = prior.get('allow_started') is True

    roots = dict.fromkeys(anchor['roots'])
    for request, artifacts, unfinished in reversed(links):
        anchor = _extend_predecessor(anchor, roots, request, artifacts, unfinished)
    anchor['roots'] = tuple(roots)
    return anchor


def _activation_witness(selected, record, inspect_image):
    require(selected.name=='activation-receipt.json'
        and record.get('operational_ready') is True
        and record.get('activation_mode')=='dual' and record.get('completed_at'),
        'BACKED_ACTIVE_PREDECESSOR_REQUIRED')
    root = selected.parents[5]
    require((root/'.git').exists(), 'BACKED_PREDECESSOR_ROOT_INVALID')
    image=record['runtime_image']
    if inspect_image is not None:
        inspected=inspect_image(image)
        require(inspected['Config']['Labels']['org.opencontainers.image.revision']==record['git_commit'],
            'BACKED_PREDECESSOR_RUNTIME_CHANGED')
        image=inspected['Id']
    return dict(git_commit=record['git_commit'],runtime_image=image,
        control_generation=record['control_generation'],certificate_sha256=record['certificate_sha256'],
        roots=(root,),postgres=None,system=None,foundation_reference=record['runtime_image'])


def _extend_predecessor(anchor, roots, request, artifacts, unfinished):
    foundation = request['predecessor']
    require(foundation['commit']==anchor['git_commit']
        and foundation['image']==anchor['runtime_image'], 'BACKED_PREDECESSOR_FOUNDATION_CHANGED')
    pg, preserved = artifacts['postgres'],artifacts['preserved']
    require(pg==foundation['postgres'] and preserved['system']==foundation['system']
        and 'archive_mode=on' in pg['command']
        and (anchor['postgres'] is None or preserved['system']==anchor['system']),
        'BACKED_PREDECESSOR_PRESERVATION_CHANGED')
    if anchor['postgres'] is not None and pg!=anchor['postgres']:
        require_same_postgres_storage(anchor['postgres'],pg)
    root=Path(request['source']).resolve()
    require((root/'.git').exists(), 'BACKED_PREDECESSOR_ROOT_INVALID')
    roots[root] = None
    observed=artifacts.get('verified_postgres',pg)
    if observed!=pg:
        require_same_postgres_storage(pg,observed)
    lineage={}
    if request.get('handoff_mode')=='BLOCKED_UNSENT':
        proof=artifacts['canonical_proof']
        require(artifacts.get('operational_ready') is False
            and artifacts.get('successor_proof_sha256')==digest(proof)
            and proof.get('operational_ready') is False and proof.get('plan') is None
            and isinstance(proof.get('recovery_predecessors'),dict)
            and proof.get('cycle_id')==preserved['cycle']['cycle_id'],
            'BACKED_REPAIR_RECEIPT_MALFORMED')
        lineage=dict(repair_predecessor=dict(generation=preserved['control']['generation'],
            cycle_id=proof['cycle_id'],fingerprints=proof['recovery_predecessors'],
            binding={key:preserved['control'][key] for key in (
                'deployment_id','broker','broker_account_id','takeover_epoch','certificate_sha256',
                'rollout_mode','rollout_version','config_sha256')},
            decision=preserved['cycle']['decision_session'],effective=preserved['cycle']['effective_session']))
    candidate = request['candidate']
    return dict(anchor,git_commit=candidate['commit'],runtime_image=candidate['image'],
        control_generation=preserved.get('control',{}).get('generation',anchor['control_generation']),
        postgres=observed,system=preserved['system'],
        foundation_reference='sentinel-local-paper:'+candidate['commit'][:8],unfinished=unfinished,
        preserved=preserved,native_positions=artifacts['native_positions'],
        notification_history=artifacts['notification_history'],**lineage)


class BackedHost(Host):
    supports_verification_recovery = True
    supports_post_trade_verification_recovery = True
    supports_dashboard_ack_progress = True
    supports_post_trade = True
    supports_blocked_unsent = True
    supports_post_trade_successor = True
    supports_post_schema_access_path = True

    def preflight_environment(self, values):
        environment.install(self, values)

    def __init__(self, request, operation_dir, *, predecessor_receipt=None, allow_started=False):
        super().__init__(request,operation_dir)
        present = any((self.operation_dir/name).exists() or (self.operation_dir/name).is_symlink()
            for name in ('build.json','build-reference.json'))
        built = builder.operation_build(self.operation_dir) if present else None
        self.predecessor_receipt = Path(predecessor_receipt or built['predecessor_receipt']['path'])
        self.allow_started_predecessor=(allow_started or (built is not None
            and built['predecessor_receipt'].get('allow_started') is True))
        witness=predecessor_witness(self.predecessor_receipt,
            inspect_image=lambda ref:builder._inspect(self,ref),allow_started=self.allow_started_predecessor)
        self.predecessor_roots=witness['roots']
        self.predecessor_root=self.predecessor_roots[0]

    def load_values(self):
        values = super().load_values()
        require(values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY')=='REQUIRED_V1', 'BACKED_POLICY_REQUIRED')
        reference=values['SENTINEL_RUNTIME_IMAGE_REF']
        require(re.fullmatch(r'(?:[^\s]+@)?sha256:[0-9a-f]{64}',reference), 'BACKED_IMMUTABLE_IMAGE_REQUIRED')
        expected=values['SENTINEL_RUNTIME_IMAGE_DIGEST']
        require(isinstance(expected,str) and re.fullmatch(r'sha256:[0-9a-f]{64}',expected)
            and expected==values['SENTINEL_TEST_IMAGE_DIGEST'], 'BACKED_RUNTIME_FACTS_DIFFER')
        if reference.startswith('sha256:'):
            require(reference==expected,'BACKED_RUNTIME_FACTS_DIFFER')
        resolved=getattr(self,'_immutable_runtime_ids',{})
        if reference in resolved:
            actual=resolved[reference]
        else:
            metadata=builder._inspect(self,reference)
            actual=metadata['Id']
            require(isinstance(actual,str) and re.fullmatch(r'sha256:[0-9a-f]{64}',actual)
                and (actual==reference if reference.startswith('sha256:') else
                     isinstance(metadata.get('RepoDigests'),list) and reference in metadata['RepoDigests']),
                'BACKED_IMMUTABLE_IMAGE_RESOLUTION_CHANGED')
            require(actual==expected,'BACKED_RUNTIME_FACTS_DIFFER')
            self._immutable_runtime_ids={**resolved,reference:actual}
        require(actual==values['SENTINEL_RUNTIME_IMAGE_DIGEST']==values['SENTINEL_TEST_IMAGE_DIGEST'],
            'BACKED_RUNTIME_FACTS_DIFFER')
        # Resolve an immutable RepoDigest into its actual local image identity.
        # This field selects the same bytes; no certificate supplies the value.
        values.update(SENTINEL_RUNTIME_IMAGE_REF=actual,SENTINEL_LOCAL_PAPER_IMAGE=actual)
        return values

    def install_values(self, previous, candidate):
        """Canonical ACTIVE roots do not own archive-off installer metadata."""
        metadata = self.deployment/'local-delivery.json'
        if metadata.exists() or metadata.is_symlink():
            require(isinstance(read_json(metadata),dict), 'BACKED_ARCHIVE_METADATA_MALFORMED')
            return super().install_values(previous,candidate)
        require(getattr(self,'_values_install_owned',False) is True, 'BACKED_INSTALL_OWNER_REQUIRED')
        require((self.deployment/'.git').exists() and not (self.deployment/'.git').is_symlink(),
            'BACKED_CANONICAL_DEPLOYMENT_REQUIRED')
        require(not (self.deployment/'.env').is_symlink(), 'BACKED_ENVIRONMENT_PATH_UNSAFE')
        built=builder.operation_build(self.operation_dir)
        anchor=built['predecessor_receipt']
        require(Path(anchor['path'])==self.predecessor_receipt
            and sha256_file(self.predecessor_receipt)==anchor['sha256'], 'BACKED_PREDECESSOR_ANCHOR_CHANGED')
        require(Journal(self.operation_dir).request==self.request
            and built['foundation']==self.request['predecessor']
            and built['commit']==self.request['candidate']['commit']
            and built['image']==self.request['candidate']['image']
            and built['source_identity']==self.request['candidate']['source_identity']
            and Path(built['source']).resolve()==self.source
            and Path(built['deployment']).resolve()==self.deployment,
            'BACKED_INSTALL_BUILD_CHANGED')
        witness=predecessor_witness(self.predecessor_receipt,
            inspect_image=lambda ref:builder._inspect(self,ref),
            allow_started=self.allow_started_predecessor)
        require(witness['git_commit']==self.request['predecessor']['commit']
            and witness['runtime_image']==self.request['predecessor']['image'],
            'BACKED_INSTALL_ACTIVE_ANCHOR_CHANGED')
        require(candidate==self.candidate_values(previous)
            and all(previous.get(k)==candidate.get(k) for k in set(previous)|set(candidate)
                    if k not in RUNTIME_KEYS), 'NON_RUNTIME_CONFIGURATION_CHANGED')
        # The preceding failed host may already have atomically selected these
        # exact bytes before discovering that archive-only metadata was absent.
        if previous==candidate:
            environment.install(self,previous)
            return
        raw=''.join(k+'='+json.dumps(v,ensure_ascii=False)+'\n' for k,v in sorted(candidate.items()))
        require(self.literal.parse_bytes(raw.encode())==candidate, 'LITERAL_ENV_ROUNDTRIP_FAILED')
        environment.install(self,previous,raw.encode())

    def compose_paths(self, values):
        require(values['SENTINEL_GIT_COMMIT'] in {
            self.request['predecessor']['commit'],self.request['candidate']['commit']},
            'BACKED_COMPOSE_RUNTIME_OUTSIDE_REQUEST')
        role = ('candidate' if values['SENTINEL_GIT_COMMIT']==self.request['candidate']['commit']
                else 'predecessor')
        image = self.request[role]['image']
        require(values['SENTINEL_RUNTIME_IMAGE_DIGEST']==image
            and values['SENTINEL_LOCAL_PAPER_IMAGE']==image, 'BACKED_IMAGE_SELECTOR_CHANGED')
        overlay = immutable_image_overlay(self.operation_dir, image)
        return (*tuple(self.source/name for name in COMPOSE), overlay)

    def verify_compose(self, role):
        require(role in {'predecessor','candidate'},'BACKED_COMPOSE_ROLE_INVALID')
        for name in COMPOSE:
            original=self.git_bytes('show',self.request['predecessor']['commit']+':'+name)
            candidate=(self.source/name).read_bytes()
            if candidate!=original:
                require(_allowed_worker_mount(name,original,candidate)
                    and name in self.request['allowed_delta']
                    and sha256_file(self.source/name)==self.request['qualification']['source_files'][name],
                    'BACKED_COMPOSITION_CHANGE_REFUSED')
            expected=original if role=='predecessor' else candidate
            colocated_addition=(role=='predecessor' and candidate!=original
                and self.source.resolve()==self.deployment.resolve())
            accepted=(original,candidate) if colocated_addition else (expected,)
            require((self.deployment/name).read_bytes() in accepted,'BACKED_COMPOSITION_CHANGE_REFUSED')

    def install_compose(self):
        # Resume accepts only the exact predecessor or qualified candidate file.
        for name in COMPOSE:
            original=self.git_bytes('show',self.request['predecessor']['commit']+':'+name)
            candidate=(self.source/name).read_bytes()
            target=self.deployment/name
            require(not target.is_symlink() and target.read_bytes() in (original,candidate),
                'BACKED_COMPOSITION_CHANGE_REFUSED')
            if candidate==original:
                continue
            require(_allowed_worker_mount(name,original,candidate)
                and name in self.request['allowed_delta']
                and sha256_file(self.source/name)==self.request['qualification']['source_files'][name],
                'BACKED_COMPOSITION_CHANGE_REFUSED')
            fd,temporary=tempfile.mkstemp(prefix='.compose-delivery-',dir=self.deployment)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(candidate);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        directory=os.open(self.deployment,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        self.verify_compose('candidate')

    def postgres(self):
        actual=postgres_facts(self.container('sentinel-postgres'))
        require(actual==self.request['predecessor']['postgres'], 'BACKED_POSTGRES_IDENTITY_CHANGED')
        return actual

    def postgres_after_restart(self, expected):
        require(expected==self.request['predecessor']['postgres'], 'BACKED_POSTGRES_WITNESS_CHANGED')
        actual=postgres_facts(self.container('sentinel-postgres'))
        require_same_postgres_storage(expected,actual)
        return actual

    def repair_core_exposure(self, state):
        """Read one scalar from the exact already-verified current record."""
        require(self.request.get('handoff_mode')=='BLOCKED_UNSENT',
            'BLOCKED_UNSENT_EXPOSURE_SCOPE_REQUIRED')
        receipt=Journal(self.operation_dir).read()
        proof=receipt['artifacts']['canonical_proof']
        book=proof.get('book') or {}
        decision=state['cycle']['decision_session']
        require(receipt['stage']=='APPLICATIONS_STARTED'
            and receipt['artifacts'].get('successor_proof_sha256')==digest(proof)
            and receipt['artifacts']['preserved']==state
            and isinstance(decision,str) and date.fromisoformat(decision).isoformat()==decision
            and book.get('session')==decision
            and book.get('state_sha256')==proof.get('book_state_sha256')
            and all(isinstance(book.get(key),str) and re.fullmatch('[0-9a-f]{64}',book[key])
                for key in ('record_sha256','state_sha256')),
            'BLOCKED_UNSENT_EXPOSURE_PROOF_CHANGED')
        observation=self.load_values().get('SENTINEL_SHADOW_OBSERVATION_ID','primary')
        require(isinstance(observation,str) and re.fullmatch('[A-Za-z0-9_.-]+',observation),
            'BLOCKED_UNSENT_EXPOSURE_OBSERVATION_INVALID')
        rows=self.sql("SELECT json_agg(x) FROM (SELECT session::text AS session,"
            "state->>'record_sha256' AS record_sha256,state->>'state_sha256' AS state_sha256,"
            "state->'state'->'last_decision'->>'session' AS decision_session,"
            "CASE WHEN length(state->'state'->'last_decision'->>'target_core_exposure')<=128 "
            "THEN state->'state'->'last_decision'->>'target_core_exposure' END AS core_exposure "
            "FROM sentinel_processed_sessions WHERE cursor_name LIKE 'shadow-observation:v1:"
            +observation+":%' AND session='"+decision+"' AND state->>'record_sha256'='"
            +book['record_sha256']+"' AND state->>'state_sha256'='"+book['state_sha256']+"' LIMIT 2) x")
        require(isinstance(rows,list) and len(rows)==1,'BLOCKED_UNSENT_EXPOSURE_RECORD_AMBIGUOUS')
        row=rows[0]
        require(row.get('session')==row.get('decision_session')==decision
            and all(row.get(key)==book[key] for key in ('record_sha256','state_sha256'))
            and isinstance(row.get('core_exposure'),str),
            'BLOCKED_UNSENT_EXPOSURE_RECORD_CHANGED')
        try:
            value=Decimal(row['core_exposure'])
        except (InvalidOperation,TypeError,KeyError) as exc:
            raise DeliveryRefused('BLOCKED_UNSENT_EXPOSURE_INVALID') from exc
        require(value.is_finite() and 0<=value<=1,'BLOCKED_UNSENT_EXPOSURE_INVALID')
        return str(value)

    def predecessor_canonical_proof(self, state):
        """Reuse an unchanged predecessor fact, never a candidate startup fact."""
        built=builder.operation_build(self.operation_dir)
        anchor=built['predecessor_receipt']
        require(str(self.predecessor_receipt)==anchor['path']
            and sha256_file(self.predecessor_receipt)==anchor['sha256'],
            'BACKED_PREDECESSOR_ANCHOR_CHANGED')
        if self.predecessor_receipt.name!='receipt.json':
            return None
        prior=Journal(self.predecessor_receipt.parent)
        record=prior.read()
        require(record['stage'] in ('VERIFIED','APPLICATIONS_STARTED'),
            'BACKED_PREDECESSOR_PROOF_STAGE_CHANGED')
        _require_access_path_completion(prior,record)
        selected=prior.request['candidate'];old=self.request['predecessor']
        require(selected['commit']==old['commit'] and selected['image']==old['image'],
            'BACKED_PREDECESSOR_PROOF_RUNTIME_CHANGED')
        artifacts=record['artifacts']
        preserved=artifacts['preserved']
        comparison=state
        if 'issuer_evidence' not in preserved:
            issuer=state.get('issuer_evidence')
            if not (isinstance(issuer,dict) and set(issuer)=={'count','md5'}
                    and type(issuer['count']) is int and issuer['count']==0
                    and issuer['md5']==checks.EMPTY_ISSUER_EVIDENCE_MD5):
                return None
            # A predecessor cannot attest rows which its snapshot did not name.
            # Only their proven absence adds no old-image canonical fact.
            comparison={key:value for key,value in state.items() if key!='issuer_evidence'}
        if preserved!=comparison:
            return None
        proof=artifacts['canonical_proof']
        require(isinstance(proof,dict) and proof and
            artifacts.get('successor_proof_sha256')==digest(proof),
            'BACKED_PREDECESSOR_CANONICAL_PROOF_CHANGED')
        return proof

    def access_path_canonical_bootstrap(self, state, retained):
        from sentinel_local_delivery.access_path_bootstrap import preflight
        return preflight(self,state,retained)

    def verify_access_path_canonical_installation(self, state, contract):
        from sentinel_local_delivery.access_path_bootstrap import post_schema
        return post_schema(self,state,contract)

    @contextmanager
    def owned(self):
        values=self.load_values()
        authority=Path(values['SENTINEL_AUTHORITY_ARTIFACTS_DIR'])
        go_roots=tuple(dict.fromkeys((self.deployment,*self.predecessor_roots)))
        paths=[authority/'activation-coordinator.lock',authority/'autonomous-deploy.lock',
            *(root/'artifacts/sentinel/go-validation/go-validation.lock'
              for root in go_roots)]
        with ExitStack() as stack:
            for path in dict.fromkeys(paths):
                require(path.is_absolute() and not path.is_symlink(), 'BACKED_OWNER_LOCK_PATH')
                path.parent.mkdir(parents=True,exist_ok=True)
                handle=stack.enter_context(path.open('a+'))
                try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError as exc:raise DeliveryRefused('ANOTHER_CANONICAL_OWNER_IS_ACTIVE') from exc
                require(owns_exclusive_flock(handle.fileno()), 'BACKED_OWNER_NOT_PROVEN')
            with super().owned():
                self._values_install_owned=True
                try:yield
                finally:self._values_install_owned=False


def require_started_state(host, record, values, pg, image):
    from sentinel_local_delivery import evidence
    require(record.get('unfinished') is True and getattr(host,'allow_started_predecessor',False),
        'BACKED_STARTED_PREDECESSOR_NOT_SELECTED')
    require_same_postgres_storage(record['postgres'],pg)
    host.request['predecessor'].update(postgres=pg,system=record['system'])
    require(evidence.snapshot(host)==record['preserved'], 'BACKED_STARTED_FINANCIAL_STATE_CHANGED')
    require(evidence.native_positions(host,values)==record['native_positions'],
        'BACKED_STARTED_NATIVE_POSITIONS_CHANGED')
    evidence.check_notification_history(host,record['notification_history'])
    applications=host.containers(SERVICES)
    for service in SERVICES:
        item=applications[service]
        require(item['Image']==image and item['State']['Running']
            and item['State'].get('Health',{}).get('Status')=='healthy'
            and not item['State']['OOMKilled'] and not item['State']['Restarting'],
            'BACKED_STARTED_APPLICATION_UNHEALTHY')


def recovered_baseline_generation(host, record, state):
    """Derive only the two-event recovery edge from a not-ready repair receipt."""
    from sentinel_local_delivery import evidence
    expected=dict(record.get('repair_predecessor') or {})
    require(bool(expected) and state['generation']==expected['generation']+2
        and state['certificate']==expected['binding']['certificate_sha256']
        and state.get('enabled') is True and state.get('killed') is False,
        'BACKED_REPAIR_RECOVERY_LINEAGE_REQUIRED')
    subject=SimpleNamespace(request=dict(host.request,handoff_mode='PRE_OPEN',
        predecessor=dict(host.request['predecessor'],system=record['system'],postgres=record['postgres'])),
        load_values=host.load_values,sql=host.sql)
    current=evidence.snapshot(subject)
    require(current['control']['generation']==state['generation']
        and current['cycle']['decision_session']==expected['decision']
        and current['cycle']['effective_session']==expected['effective'],
        'BACKED_REPAIR_RECOVERY_READY_SUBJECT_CHANGED')
    expected.update(ready_cycle_id=current['cycle']['cycle_id'],plan_id=current['plan']['plan_id'])
    result=host.compose(host.load_values(),'run','--rm','--no-deps','--pull','never',
        '--entrypoint','python','sentinel-authorized-cli','-B','-c',checks.RECOVERY_LINEAGE,
        json.dumps(expected,sort_keys=True),timeout=60)
    proof=json.loads(result.stdout)
    require(proof==dict(generation=state['generation'],blocked_cycle_id=expected['cycle_id'],
        certificate=expected['binding']['certificate_sha256'],fingerprints=expected['fingerprints'],
        kind='ROLLING_PUBLICATION_ADVANCE_MISCLASSIFIED',binding=expected['binding']),
        'BACKED_REPAIR_RECOVERY_PROOF_CHANGED')
    return proof['generation']


def active_baseline(path, host, *, blocked_unsent=False):
    record=predecessor_witness(path,inspect_image=lambda ref:builder._inspect(host,ref),
        allow_started=getattr(host,'allow_started_predecessor',False))
    values=host.load_values()
    reference=record['runtime_image']
    image=builder._inspect(host,reference)
    require(image['Config']['Labels']['org.opencontainers.image.revision']==record['git_commit']
        and values['SENTINEL_GIT_COMMIT']==record['git_commit']
        and values['SENTINEL_RUNTIME_IMAGE_DIGEST']==image['Id'], 'BACKED_PREDECESSOR_RUNTIME_CHANGED')
    state=host.sql("SELECT json_build_object('system',(SELECT system_identifier::text FROM pg_control_system()),"
        "'generation',generation,'certificate',certificate_sha256,'enabled',enabled,'killed',kill_switch_engaged,"
        "'plain_kill',EXISTS(SELECT 1 FROM sentinel_automation_events e WHERE e.generation=c.generation "
        "AND e.action='KILL_ENGAGED' AND e.detail->>'schema' IS DISTINCT FROM 'sentinel.unsent-recovery/1')) "
        "FROM sentinel_automation_control c WHERE id=1")
    expected_generation=record['control_generation']+(1 if blocked_unsent else 0)
    if not blocked_unsent and state['generation']!=expected_generation and record.get('repair_predecessor'):
        expected_generation=recovered_baseline_generation(host,record,state)
    require(state['generation']==expected_generation
        and state['certificate']==record['certificate_sha256'], 'BACKED_PREDECESSOR_AUTHORITY_CHANGED')
    if blocked_unsent:
        require(not record.get('unfinished') and state.get('enabled') is True
            and state.get('killed') is True and state.get('plain_kill') is True,
            'BLOCKED_UNSENT_PLAIN_KILL_REQUIRED')
    pg=postgres_facts(host.container('sentinel-postgres'))
    require(record['postgres'] is None or state['system']==record['system'],
        'BACKED_VERIFIED_POSTGRES_CHANGED')
    if record['postgres'] is not None and not record.get('unfinished'):
        require_same_postgres_storage(record['postgres'],pg)
    if record.get('unfinished'):
        require_started_state(host,record,values,pg,image['Id'])
    # The primary command must equal the unchanged canonical backed Compose graph.
    configuration=json.loads(host.compose(values,'config','--format','json').stdout)
    require(pg['command']==configuration['services']['sentinel-postgres']['command'],
        'BACKED_POSTGRES_COMPOSITION_CHANGED')
    return dict(commit=record['git_commit'],image=image['Id'],postgres=pg,system=state['system'])


def main(argv=None):
    args=cli.parser(backed=True).parse_args(argv)
    folder=Path(args.operation_dir).resolve()
    try:
        if args.command=='build':
            folder=builder.safe_directory(folder,create=True)
            def factory(request,op):return BackedHost(request,op,predecessor_receipt=args.predecessor_receipt,
                allow_started=args.allow_started_predecessor)
            draft=factory(dict(source=args.source,deployment=args.deployment,handoff_mode=args.handoff_mode),folder)
            witness=predecessor_witness(args.predecessor_receipt,
                inspect_image=lambda ref:builder._inspect(draft,ref),allow_started=args.allow_started_predecessor)
            # The draft graph needs only the two already bound source revisions.
            draft.request.update(predecessor=dict(commit=witness['git_commit'],
                image=builder._inspect(draft,witness['runtime_image'])['Id']),candidate=dict(commit=args.commit))
            result=builder.build(source=args.source,deployment=args.deployment,
                predecessor_receipt=args.predecessor_receipt,qualification=args.qualification,
                qualification_sha256=args.qualification_sha256,approved_delta=args.allowed_delta,
                approved_delta_sha256=args.allowed_delta_sha256,operation_dir=folder,commit=args.commit,
                host_type=factory,baseline_reader=lambda path:active_baseline(path,draft,
                    blocked_unsent=args.handoff_mode=='BLOCKED_UNSENT'),
                foundation_reference=witness['foundation_reference'],
                predecessor_receipt_options={'allow_started':True} if args.allow_started_predecessor else None)
            output=dict(build_record=str(folder/'build.json'),build_sha256=sha256_file(folder/'build.json'),
                commit=result['commit'],image=result['image'])
        elif args.command=='prepare':
            folder=builder.safe_directory(args.operation_dir,create=True)
            built=builder.pinned_build(args.build_record,args.build_sha256)
            host=BackedHost(dict(source=built['source'],deployment=built['deployment'],
                predecessor=built['foundation'],candidate=dict(commit=built['commit']),handoff_mode=args.handoff_mode),folder,
                predecessor_receipt=built['predecessor_receipt']['path'],
                allow_started=built['predecessor_receipt'].get('allow_started') is True)
            cli.prepare(operation_dir=folder,build_record=args.build_record,build_sha256=args.build_sha256,
                operation_id=args.operation_id,host_type=BackedHost,
                baseline_reader=lambda path:active_baseline(path,host,
                    blocked_unsent=args.handoff_mode=='BLOCKED_UNSENT'),handoff_mode=args.handoff_mode,
                canonical_proof_phase=args.canonical_proof_phase)
            output=cli.status(folder)
        elif args.command=='status':output=cli.status(folder)
        else:
            journal=Journal(folder);host=BackedHost(journal.request,folder)
            built=builder.operation_build(folder)
            require(sha256_file(built['predecessor_receipt']['path'])==built['predecessor_receipt']['sha256']
                and built['foundation']==journal.request['predecessor'], 'BACKED_WITNESS_CHANGED')
            delivery=Delivery(host,journal)
            if args.command=='abandon-drain':
                delivery.abandon_drain()
            elif args.command=='recover-fenced-preflight':
                from sentinel_local_delivery.fenced_recovery import recover
                recover(delivery, args.recovery_id)
            elif args.command=='recover-verification':
                from sentinel_local_delivery.verification_recovery import recover
                recover(delivery, args.recovery_id)
            elif args.one_stage:
                with host.owned():delivery.step()
            else:delivery.advance()
            output=cli.status(folder)
        print(json.dumps(output,sort_keys=True));return 0
    except (DeliveryRefused,OSError,ValueError,KeyError,TypeError) as exc:
        print('Backed local patch refused: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
