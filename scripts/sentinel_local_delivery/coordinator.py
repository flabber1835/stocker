"""One resumable PAPER application handoff; no financial mutation commands."""
from __future__ import annotations

from datetime import datetime, timedelta
import time

from . import access_path_qualification, evidence, readiness
from .host import RUNTIME_KEYS, SERVICES, application_healthy
from .model import (ACCESS_PATH_SCHEMA, POST_SCHEMA_ACCESS_PATH,
                    canonical_proof_phase, digest, handoff_mode, require, utcnow)

# Source tampering is checked before every real mutation, and on final
# observation. Intent-only journal transitions do not launch an image probe.
SOURCE_CHECK_STAGES = frozenset({'NEW','DRAIN_REQUESTED','STOP_REQUESTED',
    'SCHEMA_INSTALL_REQUESTED','COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED',
    'START_REQUESTED','APPLICATIONS_STARTED'})
ACCESS_PATH_QUALIFIED_STAGES = frozenset({'COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED',
    'SHADOW_STARTED','SHADOW_VERIFIED','START_REQUESTED','APPLICATIONS_STARTED','VERIFIED'})


class Delivery:
    def __init__(self, host, journal, *, monotonic=time.monotonic, sleep=time.sleep):
        self.host, self.journal = host, journal
        self.monotonic, self.sleep = monotonic, sleep

    def _apps(self, role, *, running=None, healthy=False):
        image = self.host.request[role]['image']
        result = {}
        names=self.host.predecessor_services() if role=='predecessor' else SERVICES
        applications=self.host.containers(names)
        for service in names:
            item = applications[service]
            require(item['Image']==image, 'APPLICATION_IMAGE_CHANGED')
            if (role=='predecessor' and handoff_mode(self.host.request)=='POST_TRADE_SUCCESSOR'
                    and service=='sentinel-automation' and running is True and healthy):
                expected=self.journal.read()['artifacts'].get('predecessor_automation')
                if expected is not None:
                    require(item['Id']==expected['container'] and item['Image']==expected['image'],
                        'POST_TRADE_SUCCESSOR_PREDECESSOR_CHANGED')
                evidence.require_successor_worker_restart(self.host,item)
                result[service]=item
                continue
            if (role=='predecessor' and handoff_mode(self.host.request)=='BLOCKED_UNSENT'
                    and service=='sentinel-automation'):
                require(item['State']['Running'] is False,'BLOCKED_UNSENT_WRITER_NOT_STOPPED')
                result[service]=item
                continue
            if running is not None:
                require(item['State']['Running'] is running, 'APPLICATION_RUNNING_STATE_CHANGED')
            if healthy:
                require(item['State'].get('Health',{}).get('Status')=='healthy'
                    and not item['State']['OOMKilled'] and not item['State']['Restarting'],
                    'APPLICATION_UNHEALTHY')
            result[service] = item
        return result

    def _stopped_for_install(self):
        old=self.host.request['predecessor']['image']
        applications=self.host.containers(SERVICES,missing_ok=True)
        for service in SERVICES:
            item=applications[service]
            if item is None:
                require(service not in self.host.predecessor_services(),'PREDECESSOR_APPLICATION_MISSING')
            else:
                require(item['Image']==old and not item['State']['Running'],
                        'APPLICATION_NOT_QUIESCENT_FOR_INSTALL')

    def _unchanged(self, artifacts, *, native=True, allow_restart=False, observation=False):
        require(evidence.snapshot(self.host)==artifacts['preserved'], 'PRESERVED_STATE_CHANGED')
        if allow_restart and hasattr(self.host, 'postgres_after_restart'):
            postgres = self.host.postgres_after_restart(artifacts['postgres'])
        else:
            postgres = self.host.postgres()
            require(postgres==artifacts['postgres'], 'POSTGRES_CHANGED')
        if native:
            require(evidence.native_positions(self.host,self.host.load_values())==artifacts['native_positions'],
                    'NATIVE_HOLDINGS_OR_OPEN_ORDERS_CHANGED')
        appends=evidence.check_notification_history(self.host,artifacts['notification_history'])
        return (postgres,appends) if observation else postgres

    def _values(self, artifacts):
        current = self.host.load_values()
        old = dict(current,**artifacts['predecessor_runtime'])
        require(digest(old)==artifacts['configuration_sha256'], 'NON_RUNTIME_CONFIGURATION_CHANGED')
        candidate = self.host.candidate_values(old)
        require(current in (old,candidate), 'INSTALLED_RUNTIME_FIELDS_CHANGED')
        return current,old,candidate

    def _fresh(self, timestamp):
        from .fenced_recovery import effective_time
        timestamp = effective_time(self, timestamp)
        observed = datetime.fromisoformat(timestamp)
        require(observed.utcoffset() is not None, 'PROOF_TIME_INVALID')
        require(-5 <= (utcnow()-observed).total_seconds() <= 900, 'PROOF_HANDOFF_INTERVAL_EXPIRED')

    def _post_schema_access_path(self):
        selected = canonical_proof_phase(self.host.request)==POST_SCHEMA_ACCESS_PATH
        if selected:
            require(self.host.request['schema']==ACCESS_PATH_SCHEMA
                and handoff_mode(self.host.request)=='PRE_OPEN'
                and getattr(self.host,'supports_post_schema_access_path',False) is True
                and self.host.request==self.journal.request,
                'ACCESS_PATH_CANONICAL_BOOTSTRAP_UNSUPPORTED')
        return selected

    def _access_path_contract(self, artifacts):
        return access_path_qualification.require_contract(
            self.host.request,self.journal.subject,artifacts)

    def _access_path_installation(self, contract, installed):
        return access_path_qualification.require_installation(contract,installed)

    def _require_access_path_qualification(self, artifacts):
        return access_path_qualification.require_qualification(
            self.host.request,self.journal.subject,artifacts)

    def _qualify_access_path(self, artifacts, old, candidate):
        contract=self._access_path_contract(artifacts)
        self._fresh(artifacts['preflight_at'])
        self._stopped_for_install();self._unchanged(artifacts)
        installed=self._access_path_installation(contract,
            self.host.verify_access_path_canonical_installation(artifacts['preserved'],contract))
        proof=evidence.canonical_check(self.host,candidate,artifacts['preserved'])
        require(proof==artifacts['predecessor_canonical_proof'],'CANONICAL_ECONOMIC_PROOF_CHANGED')
        current,previous,selected=self._values(artifacts)
        require(current==previous==old and selected==candidate,'PREMATURE_RUNTIME_INSTALLATION')
        self._fresh(artifacts['preflight_at'])
        self._stopped_for_install();self._unchanged(artifacts)
        after=self._access_path_installation(contract,
            self.host.verify_access_path_canonical_installation(artifacts['preserved'],contract))
        require(after==installed,'ACCESS_PATH_CANONICAL_INSTALLATION_CHANGED')
        self._fresh(artifacts['preflight_at'])
        return dict(canonical_proof=proof,access_path_canonical_qualification=dict(
            schema='sentinel.checkpoint-access-canonical-qualification/1',authority_effect='NONE',
            request_sha256=self.journal.subject,state_sha256=contract['state_sha256'],
            contract_sha256=digest(contract),installation=installed,
            canonical_proof_sha256=digest(proof),qualified_at=utcnow().isoformat()))

    def _wait_shadow(self, *, deadline=None):
        deadline = min(self.monotonic()+180,deadline) if deadline is not None else self.monotonic()+180
        self.host.wait_application_health('sentinel-shadow', deadline=deadline,
            clock=self.monotonic)

    def _leader(self, generation, *, deadline=None):
        deadline = min(self.monotonic()+75,deadline) if deadline is not None else self.monotonic()+75
        first = None
        while True:
            require(self.monotonic()<deadline, 'LEADER_HEARTBEAT_NOT_ADVANCING')
            current = evidence.leader(self.host)
            require(self.monotonic()<deadline,'LEADER_HEARTBEAT_NOT_ADVANCING')
            if first is None:
                if current['current'] and current['holder']:
                    require(current['generation']==generation,'CURRENT_LEADERSHIP_GENERATION_CHANGED')
                    first=current
            else:
                require(current['current'] and all(current[k]==first[k] for k in ('holder','generation','fence')),
                        'LEADERSHIP_CHANGED_DURING_CHECK')
                if current['heartbeat']>first['heartbeat']:
                    return current
            self.sleep(min(3,deadline-self.monotonic()))

    def _readiness(self, receipt):
        end=readiness.cutoff(receipt,now=utcnow())
        deadline=self.monotonic()+min(readiness.SECONDS,(end-utcnow()).total_seconds())
        require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
        applications=self.host.wait_applications_health(
            deadline=min(deadline,self.monotonic()+120),clock=self.monotonic,
            expected=receipt['artifacts'].get('started_applications'))
        repair=handoff_mode(self.host.request)=='BLOCKED_UNSENT'
        if repair:
            leader=evidence.leader(self.host)
            require(leader['current'] is False,'BLOCKED_UNSENT_LEADER_IS_ACTIVE')
        else:
            leader=self._leader(receipt['artifacts']['preserved']['control']['generation'],deadline=deadline)
        require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
        readiness.cutoff(receipt,now=utcnow())
        require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
        return leader,end,deadline,applications

    def _readiness_unchanged(self, applications, leader):
        # Publication waiting must never silently admit a replacement process or
        # a new leader, including while the final preservation proof ran.
        current=self._apps('candidate',running=True,healthy=True)
        for service,before in applications.items():
            after=current[service]
            require(after['Id']==before['Id'] and after['RestartCount']==before['RestartCount']
                and after['State']['StartedAt']==before['State']['StartedAt'],
                'APPLICATION_STARTUP_PROCESS_CHANGED')
        latest=evidence.leader(self.host)
        if handoff_mode(self.host.request)=='BLOCKED_UNSENT':
            require(latest['current'] is False,'BLOCKED_UNSENT_LEADER_IS_ACTIVE')
        else:
            require(latest['current'] and all(latest[k]==leader[k] for k in ('holder','generation','fence'))
                and latest['heartbeat']>=leader['heartbeat'],'LEADERSHIP_CHANGED_DURING_CHECK')
        return latest

    def step(self):
        self.journal.require_active()
        receipt = self.journal.read(); stage = receipt['stage']; artifacts = receipt['artifacts']
        access_path=self._post_schema_access_path()
        if access_path and stage in ACCESS_PATH_QUALIFIED_STAGES:
            self._require_access_path_qualification(artifacts)
        if stage=='VERIFIED':
            return receipt
        if stage in SOURCE_CHECK_STAGES:
            self.host.verify_candidate()
        elif access_path and stage=='SCHEMA_INSTALLED':
            self.host.verify_candidate()
        values = self.host.load_values()
        if stage=='NEW':
            preflight = getattr(self.host, 'preflight_environment', None)
            if preflight is not None:
                preflight(values)
            self.host.verify_compose('predecessor')
            old = self.host.request['predecessor']
            require(values['SENTINEL_GIT_COMMIT']==old['commit']
                and all(values[k]==old['image'] for k in (
                    'SENTINEL_RUNTIME_IMAGE_DIGEST','SENTINEL_TEST_IMAGE_DIGEST',
                    'SENTINEL_RUNTIME_IMAGE_REF','SENTINEL_LOCAL_PAPER_IMAGE')), 'PREDECESSOR_RUNTIME_CHANGED')
            identity = self.host.probe(old['commit'],old['image'])
            require(values['SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256']==identity['source']
                and values['SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256']==identity['shadow_config'],
                'PREDECESSOR_SOURCE_CHANGED')
            applications=self._apps('predecessor',running=True,healthy=True)
            if handoff_mode(self.host.request)=='BLOCKED_UNSENT':
                evidence.idle(self.host,old['image'])
            state, pg = evidence.snapshot(self.host), self.host.postgres()
            candidate = self.host.candidate_values(values)
            evidence.compare_configuration(self.host,values,candidate,state)
            retained=getattr(self.host,'predecessor_canonical_proof',lambda _state:None)(state)
            extra={}
            if access_path:
                require(isinstance(retained,dict) and bool(retained),
                        'ACCESS_PATH_RETAINED_PREDECESSOR_PROOF_REQUIRED')
                contract=self.host.access_path_canonical_bootstrap(state,retained)
                extra.update(predecessor_canonical_proof=retained,
                             access_path_canonical_contract=contract)
                self._access_path_contract(dict(preserved=state,**extra))
            else:
                old_proof = retained if retained is not None else evidence.canonical_check(self.host,values,state)
                new_proof = evidence.canonical_check(self.host,candidate,state)
                require(old_proof==new_proof, 'CANONICAL_ECONOMIC_PROOF_CHANGED')
                extra['canonical_proof']=new_proof
            require(evidence.snapshot(self.host)==state and self.host.postgres()==pg,
                    'STATE_CHANGED_DURING_PREFLIGHT')
            native = evidence.native_positions(self.host,values)
            if handoff_mode(self.host.request) in {'POST_TRADE','POST_TRADE_SUCCESSOR'}:
                require(native==new_proof.get('settled_native_positions'),
                        'POST_TRADE_NATIVE_RECONCILIATION_CHANGED')
            if handoff_mode(self.host.request)=='POST_TRADE_SUCCESSOR':
                worker=applications['sentinel-automation']
                extra['predecessor_automation']=dict(container=worker['Id'],image=worker['Image'])
            return self.journal.advance(stage,'PREFLIGHT_PASS',preserved=state,postgres=pg,
                preflight_at=utcnow().isoformat(),native_positions=native,
                predecessor_runtime={key:values[key] for key in RUNTIME_KEYS},
                configuration_sha256=digest(values),notification_history=evidence.notification_history(self.host),**extra)
        current,old,candidate = self._values(artifacts)
        if stage=='PREFLIGHT_PASS':
            require(current==old, 'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            self._apps('predecessor',running=True,healthy=True)
            return self.journal.advance(stage,'DRAIN_REQUESTED',drain_target=evidence.drain_target(self.host))
        if stage=='DRAIN_REQUESTED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            self._apps('predecessor'); self._unchanged(artifacts)
            self.host.verify_compose('predecessor')
            proof=evidence.request_drain(self.host,old,artifacts['drain_target'])
            self._unchanged(artifacts,native=False)
            return self.journal.advance(stage,'DRAIN_ACKNOWLEDGED',drain_proof=proof)
        if stage=='DRAIN_ACKNOWLEDGED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            evidence.check_drain(self.host,old,artifacts['drain_target'],artifacts['drain_proof'])
            return self.journal.advance(stage,'STOP_REQUESTED')
        if stage=='STOP_REQUESTED':
            require(current==old, 'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            self._apps('predecessor')
            self._unchanged(artifacts)
            evidence.check_drain(self.host,old,artifacts['drain_target'],artifacts['drain_proof'])
            self.host.compose(old,'stop','--timeout','120',*self.host.predecessor_services(),timeout=150)
            evidence.check_stopped_drain(self.host,artifacts['drain_target'],artifacts['drain_proof'])
            self._apps('predecessor',running=False)
            self._unchanged(artifacts,native=False)
            return self.journal.advance(stage,'APPLICATIONS_STOPPED')
        if stage=='APPLICATIONS_STOPPED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            self._stopped_for_install()
            return self.journal.advance(stage,'SCHEMA_INSTALL_REQUESTED')
        if stage=='SCHEMA_INSTALL_REQUESTED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at']);self._unchanged(artifacts,native=False)
            self._stopped_for_install()
            migration=evidence.migrate_operational_schema(self.host,candidate)
            self._fresh(artifacts['preflight_at'])
            self._unchanged(artifacts,native=False)
            if not migration['complete']:
                return receipt  # Durable page progress is resumed, never reset.
            return self.journal.advance(stage,'SCHEMA_INSTALLED',operational_installation=migration['installation'])
        if stage=='SCHEMA_INSTALLED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            self._stopped_for_install()
            qualified=self._qualify_access_path(artifacts,old,candidate) if access_path else {}
            return self.journal.advance(stage,'COMPOSE_INSTALL_REQUESTED',**qualified)
        if stage=='COMPOSE_INSTALL_REQUESTED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at']);self._unchanged(artifacts,native=False)
            self._stopped_for_install()
            self.host.install_compose()
            return self.journal.advance(stage,'COMPOSE_INSTALLED')
        if stage=='COMPOSE_INSTALLED':
            self._fresh(artifacts['preflight_at']);self._unchanged(artifacts)
            self.host.verify_compose('candidate')
            applications=self.host.containers(SERVICES,missing_ok=True)
            for service in SERVICES:
                item=applications[service]
                if service=='sentinel-shadow' and item and item['Image']==self.host.request['candidate']['image']:
                    require(current==candidate,'SHADOW_WITH_WRONG_CONFIGURATION')
                elif item is not None:
                    require(item['Image']==self.host.request['predecessor']['image'] and not item['State']['Running'],
                            'UNEXPECTED_APPLICATION_DURING_INSTALL')
            # Repeating only the exact atomic identity update is safe after a
            # lost host acknowledgement; financial state remains unchanged.
            self.host.install_values(current,candidate)
            shadow=self.host.container('sentinel-shadow')
            if shadow['Image']!=self.host.request['candidate']['image'] or not shadow['State']['Running']:
                self.host.compose(candidate,'up','-d','--no-deps','--no-build','--pull','never',
                                  'sentinel-shadow',timeout=90)
            return self.journal.advance(stage,'SHADOW_STARTED')
        require(current==candidate,'SUCCESSOR_CONFIGURATION_CHANGED')
        if stage=='SHADOW_STARTED':
            self._wait_shadow()
            self._unchanged(artifacts,native=False)
            return self.journal.advance(stage,'SHADOW_VERIFIED',successor_verified_at=utcnow().isoformat(),
                successor_proof_sha256=digest(artifacts['canonical_proof']),
                successor_verification='EXACT_IMAGE_AND_UNCHANGED_SNAPSHOT')
        if stage=='SHADOW_VERIFIED':
            self._fresh(artifacts['successor_verified_at'])
            self._wait_shadow()
            applications=self.host.containers(SERVICES,missing_ok=True)
            for service in SERVICES:
                if service=='sentinel-shadow': continue
                item=applications[service]
                if item is None:
                    require(service not in self.host.predecessor_services(),'PREDECESSOR_APPLICATION_MISSING')
                    continue
                require(item['Image']==self.host.request['predecessor']['image']
                    and item['State']['Running'] is False,'PREMATURE_APPLICATION_START')
            return self.journal.advance(stage,'START_REQUESTED')
        if stage=='START_REQUESTED':
            self._fresh(artifacts['successor_verified_at'])
            end=readiness.cutoff(receipt,now=utcnow())
            deadline=self.monotonic()+min(readiness.SECONDS,(end-utcnow()).total_seconds())
            require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
            self._wait_shadow(deadline=deadline); self._unchanged(artifacts)
            hashes=self.host.candidate_config_hashes(candidate)
            applications=self.host.containers(SERVICES,missing_ok=True)
            require(application_healthy(applications.get('sentinel-shadow'),
                self.host.request['candidate']['image']),'SUCCESSOR_SHADOW_CHANGED')
            for service in SERVICES:
                if service=='sentinel-shadow': continue
                item=applications[service]
                if item is None:
                    require(service not in self.host.predecessor_services(),'PREDECESSOR_APPLICATION_MISSING')
                    continue
                require(item['Image'] in (self.host.request['predecessor']['image'],
                                          self.host.request['candidate']['image']), 'FOREIGN_APPLICATION_IMAGE')
            if not self.host.candidate_apps_ready(hashes,applications):
                readiness.cutoff(receipt,now=utcnow())
                require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
                self.host.compose(candidate,'up','-d','--no-deps','--no-build','--pull','never',
                    *SERVICES[1:],timeout=min(90,deadline-self.monotonic()))
                applications=self._apps('candidate',running=True)
            readiness.cutoff(receipt,now=utcnow())
            require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
            self._unchanged(artifacts,native=False)
            started={service:dict(Id=item['Id'],RestartCount=item['RestartCount'],
                State={'StartedAt':item['State']['StartedAt']}) for service,item in applications.items()}
            return self.journal.advance(stage,'APPLICATIONS_STARTED',started_applications=started)
        require(stage=='APPLICATIONS_STARTED','UNSUPPORTED_DELIVERY_STAGE')
        leader,end,deadline,applications=self._readiness(receipt)
        repair=handoff_mode(self.host.request)=='BLOCKED_UNSENT'
        postgres,appends=self._unchanged(artifacts,allow_restart=not repair,observation=True)
        current=(self.host.postgres_after_restart(artifacts['postgres'])
                 if not repair and hasattr(self.host,'postgres_after_restart') else self.host.postgres())
        require(current==postgres,'POSTGRES_CHANGED_DURING_FINAL_OBSERVATION')
        panel=evidence.panel(self.host,artifacts['preserved'],
            wait_until=min(end,utcnow()+timedelta(seconds=deadline-self.monotonic())))
        leader=self._readiness_unchanged(applications,leader)
        readiness.cutoff(receipt,now=utcnow())
        require(self.monotonic()<deadline,'APPLICATION_READINESS_DEADLINE')
        if handoff_mode(self.host.request) in {'PRE_OPEN','POST_TRADE'}:
            boundary=datetime.fromisoformat(panel['installation_panel_valid_until'])
            require(boundary.utcoffset() is not None and utcnow()<boundary,
                    'INSTALLATION_PANEL_EXPIRED')
        return self.journal.advance(stage,'VERIFIED',verified_at=utcnow().isoformat(),
                                    leader=leader,panel=panel,notification_appends=appends,
                                    verified_postgres=postgres,
                                    **({'operational_ready':False,'installation_scope':'FENCED_BLOCKED_UNSENT_SOFTWARE_ONLY'}
                                       if repair else
                                      {'operational_ready':False,
                                       'installation_scope':'POST_TRADE_SUCCESSOR_COMPATIBLE_APPLICATION_REPAIR'}
                                       if handoff_mode(self.host.request)=='POST_TRADE_SUCCESSOR' else {}))

    def advance(self):
        with self.host.owned():
            transitions=0
            schema_pages=0
            while transitions<15:
                before=self.journal.read()['stage']
                receipt=self.step()
                if receipt['stage']=='VERIFIED': return receipt
                if before=='SCHEMA_INSTALL_REQUESTED':
                    schema_pages+=1
                if receipt['stage']==before:
                    require(before=='SCHEMA_INSTALL_REQUESTED','DELIVERY_UNEXPECTED_PENDING_STAGE')
                    require(schema_pages<10,'OPERATIONAL_BOOTSTRAP_PAGE_LIMIT')
                    self._fresh(receipt['artifacts']['preflight_at'])
                    continue
                transitions+=1
            require(False,'DELIVERY_STAGE_LIMIT')

    def abandon_drain(self):
        """Terminal, owned recovery; never continue an installation after release."""
        with self.host.owned():
            receipt=self.journal.read();artifacts=receipt['artifacts']
            require(receipt['stage'] in {'DRAIN_REQUESTED','DRAIN_ACKNOWLEDGED','STOP_REQUESTED'},
                    'ABANDONMENT_AFTER_INSTALLATION_FORBIDDEN')
            current,old,_=self._values(artifacts)
            require(current==old,'ABANDONMENT_PREDECESSOR_ENVIRONMENT_CHANGED')
            self.host.verify_compose('predecessor')
            applications=self.host.containers(self.host.predecessor_services())
            for service in self.host.predecessor_services():
                if service=='sentinel-shadow':continue
                item=applications[service]
                require(item['Image']==self.host.request['predecessor']['image']
                    and item['State']['Running'] and not item['State']['Restarting'],
                    'ABANDONMENT_OTHER_APPLICATION_CHANGED')
            target=artifacts['drain_target']
            record=self.journal.abandonment()
            data=self.host.container('sentinel-shadow')
            if record is None:
                evidence._cooperative_target(data,target,held=False)
                observed=self.host.drain_recovery_state(target,old)
                evidence._cooperative_target(self.host.container('sentinel-shadow'),target,held=False)
                record=self.journal.begin_abandonment(target,evidence.process_identity(data),
                    data['State']['Running'],observed)
            require(data['Id']==target['container'] and data['Image']==target['image'],
                    'ABANDONMENT_TARGET_CHANGED')
            if record['phase']=='COMPLETE':
                require(data['HostConfig']['RestartPolicy']==target['restart_policy'],
                        'ABANDONMENT_RESTORED_POLICY_CHANGED')
                return record
            # A start may have completed even if its host acknowledgement was lost.
            if record['phase']=='START_REQUESTED':
                return self._finish_abandoned_start(record,data)
            evidence._cooperative_target(data,target,held=False)
            if data['HostConfig']['RestartPolicy']!=target['restart_policy']:
                self.host.run(['docker','update','--restart=unless-stopped',target['container']],timeout=15)
            data=self.host.container('sentinel-shadow')
            evidence._cooperative_target(data,target,held=False)
            require(data['HostConfig']['RestartPolicy']==target['restart_policy'],
                    'ABANDONMENT_POLICY_NOT_RESTORED')
            if data['State']['Running']:
                return self.journal.checkpoint_abandonment('COMPLETE',completion=dict(
                    process=evidence.process_identity(data),running=True,start_observed=False,
                    restart_policy=data['HostConfig']['RestartPolicy']))
            record=self.journal.checkpoint_abandonment('START_REQUESTED',
                start_before=evidence.process_identity(data))
            self.host.run(['docker','start',target['container']],timeout=30)
            return self._finish_abandoned_start(record,self.host.container('sentinel-shadow'))

    def _finish_abandoned_start(self, record, data):
        target=record['target'];before=record['start_before']
        require(data['Id']==target['container'] and data['Image']==target['image'],
                'ABANDONMENT_TARGET_CHANGED')
        require(data['HostConfig']['RestartPolicy']==target['restart_policy']
            and not data['State']['Restarting'],'ABANDONMENT_RESTORED_POLICY_CHANGED')
        process=evidence.process_identity(data)
        require(process['started_at']!=before['started_at'] and process['restart_count']==0,
                'ABANDONMENT_START_OUTCOME_UNKNOWN')
        # An exited startup can be the installed UNKNOWN/critical guard refusing.
        # Its changed start clock proves one start, never successful financial work.
        return self.journal.checkpoint_abandonment('COMPLETE',completion=dict(
            process=process,running=data['State']['Running'],start_observed=True,
            restart_policy=data['HostConfig']['RestartPolicy']))
