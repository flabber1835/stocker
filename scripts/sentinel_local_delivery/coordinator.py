"""One resumable PAPER application handoff; no financial mutation commands."""
from __future__ import annotations

from datetime import datetime
import time

from . import evidence
from .host import RUNTIME_KEYS, SERVICES
from .model import digest, handoff_mode, require, utcnow

# Source tampering is checked before every real mutation, and on final
# observation. Intent-only journal transitions do not launch an image probe.
SOURCE_CHECK_STAGES = frozenset({'NEW','DRAIN_REQUESTED','STOP_REQUESTED',
    'SCHEMA_INSTALL_REQUESTED','COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED',
    'START_REQUESTED','APPLICATIONS_STARTED'})


class Delivery:
    def __init__(self, host, journal, *, monotonic=time.monotonic, sleep=time.sleep):
        self.host, self.journal = host, journal
        self.monotonic, self.sleep = monotonic, sleep

    def _apps(self, role, *, running=None, healthy=False):
        image = self.host.request[role]['image']
        result = {}
        names=self.host.predecessor_services() if role=='predecessor' else SERVICES
        for service in names:
            item = self.host.container(service)
            require(item['Image']==image, 'APPLICATION_IMAGE_CHANGED')
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
        for service in SERVICES:
            item=self.host.container(service,missing_ok=True)
            if item is None:
                require(service not in self.host.predecessor_services(),'PREDECESSOR_APPLICATION_MISSING')
            else:
                require(item['Image']==old and not item['State']['Running'],
                        'APPLICATION_NOT_QUIESCENT_FOR_INSTALL')

    def _unchanged(self, artifacts, *, native=True, allow_restart=False):
        require(evidence.snapshot(self.host)==artifacts['preserved'], 'PRESERVED_STATE_CHANGED')
        if allow_restart and hasattr(self.host, 'postgres_after_restart'):
            postgres = self.host.postgres_after_restart(artifacts['postgres'])
        else:
            postgres = self.host.postgres()
            require(postgres==artifacts['postgres'], 'POSTGRES_CHANGED')
        evidence.check_notification_history(self.host,artifacts['notification_history'])
        if native:
            require(evidence.native_positions(self.host,self.host.load_values())==artifacts['native_positions'],
                    'NATIVE_HOLDINGS_OR_OPEN_ORDERS_CHANGED')
        return postgres

    def _values(self, artifacts):
        current = self.host.load_values()
        old = dict(current,**artifacts['predecessor_runtime'])
        require(digest(old)==artifacts['configuration_sha256'], 'NON_RUNTIME_CONFIGURATION_CHANGED')
        candidate = self.host.candidate_values(old)
        require(current in (old,candidate), 'INSTALLED_RUNTIME_FIELDS_CHANGED')
        return current,old,candidate

    def _fresh(self, timestamp):
        observed = datetime.fromisoformat(timestamp)
        require(observed.utcoffset() is not None, 'PROOF_TIME_INVALID')
        require(-5 <= (utcnow()-observed).total_seconds() <= 900, 'PROOF_HANDOFF_INTERVAL_EXPIRED')

    def _wait_shadow(self):
        deadline = self.monotonic()+180
        while True:
            item = self.host.container('sentinel-shadow')
            require(item['Image']==self.host.request['candidate']['image'] and item['State']['Running']
                and not item['State']['OOMKilled'] and not item['State']['Restarting'],
                'SUCCESSOR_SHADOW_FAILED')
            if item['State'].get('Health',{}).get('Status')=='healthy':
                return
            require(self.monotonic()<deadline, 'SHADOW_STARTUP_DEADLINE')
            self.sleep(3)

    def _leader(self, generation):
        first = evidence.leader(self.host)
        require(first['current'] and first['holder'] and first['generation']==generation,
                'CURRENT_LEADERSHIP_ABSENT')
        deadline = self.monotonic()+75
        while True:
            require(self.monotonic()<deadline, 'LEADER_HEARTBEAT_NOT_ADVANCING')
            self.sleep(3)
            current = evidence.leader(self.host)
            require(current['current'] and all(current[k]==first[k] for k in ('holder','generation','fence')),
                    'LEADERSHIP_CHANGED_DURING_CHECK')
            if current['heartbeat']>first['heartbeat']:
                return current

    def step(self):
        receipt = self.journal.read(); stage = receipt['stage']; artifacts = receipt['artifacts']
        if stage=='VERIFIED':
            return receipt
        if stage in SOURCE_CHECK_STAGES:
            self.host.verify_candidate()
        values = self.host.load_values()
        if stage=='NEW':
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
            self._apps('predecessor',running=True,healthy=True)
            state, pg = evidence.snapshot(self.host), self.host.postgres()
            candidate = self.host.candidate_values(values)
            evidence.compare_configuration(self.host,values,candidate,state)
            retained=getattr(self.host,'predecessor_canonical_proof',lambda _state:None)(state)
            old_proof = retained if retained is not None else evidence.canonical_check(self.host,values,state)
            new_proof = evidence.canonical_check(self.host,candidate,state)
            require(old_proof==new_proof, 'CANONICAL_ECONOMIC_PROOF_CHANGED')
            require(evidence.snapshot(self.host)==state and self.host.postgres()==pg,
                    'STATE_CHANGED_DURING_PREFLIGHT')
            native = evidence.native_positions(self.host,values)
            if handoff_mode(self.host.request)=='POST_TRADE':
                require(native==new_proof.get('settled_native_positions'),
                        'POST_TRADE_NATIVE_RECONCILIATION_CHANGED')
            return self.journal.advance(stage,'PREFLIGHT_PASS',preserved=state,postgres=pg,
                canonical_proof=new_proof,preflight_at=utcnow().isoformat(),native_positions=native,
                predecessor_runtime={key:values[key] for key in RUNTIME_KEYS},
                configuration_sha256=digest(values),notification_history=evidence.notification_history(self.host))
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
            self._unchanged(artifacts,native=False)
            if not migration['complete']:
                return receipt  # Durable page progress is resumed, never reset.
            return self.journal.advance(stage,'SCHEMA_INSTALLED',operational_installation=migration['installation'])
        if stage=='SCHEMA_INSTALLED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at'])
            self._stopped_for_install()
            return self.journal.advance(stage,'COMPOSE_INSTALL_REQUESTED')
        if stage=='COMPOSE_INSTALL_REQUESTED':
            require(current==old,'PREMATURE_RUNTIME_INSTALLATION')
            self._fresh(artifacts['preflight_at']);self._unchanged(artifacts,native=False)
            self._stopped_for_install()
            self.host.install_compose()
            return self.journal.advance(stage,'COMPOSE_INSTALLED')
        if stage=='COMPOSE_INSTALLED':
            self._fresh(artifacts['preflight_at']);self._unchanged(artifacts)
            self.host.verify_compose('candidate')
            for service in SERVICES:
                item=self.host.container(service,missing_ok=True)
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
            proof=evidence.canonical_check(self.host,candidate,artifacts['preserved'])
            require(proof==artifacts['canonical_proof'],'SUCCESSOR_CANONICAL_PROOF_CHANGED')
            self._unchanged(artifacts,native=False)
            return self.journal.advance(stage,'SHADOW_VERIFIED',successor_verified_at=utcnow().isoformat(),
                                        successor_proof_sha256=digest(proof))
        if stage=='SHADOW_VERIFIED':
            self._fresh(artifacts['successor_verified_at'])
            self._wait_shadow()
            for service in SERVICES:
                if service=='sentinel-shadow': continue
                item=self.host.container(service,missing_ok=True)
                if item is None:
                    require(service not in self.host.predecessor_services(),'PREDECESSOR_APPLICATION_MISSING')
                    continue
                require(item['Image']==self.host.request['predecessor']['image']
                    and item['State']['Running'] is False,'PREMATURE_APPLICATION_START')
            return self.journal.advance(stage,'START_REQUESTED')
        if stage=='START_REQUESTED':
            self._fresh(artifacts['successor_verified_at'])
            self._wait_shadow(); self._unchanged(artifacts)
            for service in SERVICES:
                if service=='sentinel-shadow': continue
                item=self.host.container(service,missing_ok=True)
                if item is None:
                    require(service not in self.host.predecessor_services(),'PREDECESSOR_APPLICATION_MISSING')
                    continue
                require(item['Image'] in (self.host.request['predecessor']['image'],
                                          self.host.request['candidate']['image']), 'FOREIGN_APPLICATION_IMAGE')
            self.host.compose(candidate,'up','-d','--no-deps','--no-build','--pull','never',
                '--wait','--wait-timeout','120',*SERVICES[1:],timeout=150)
            self._apps('candidate',running=True,healthy=True)
            self._unchanged(artifacts,native=False)
            return self.journal.advance(stage,'APPLICATIONS_STARTED')
        require(stage=='APPLICATIONS_STARTED','UNSUPPORTED_DELIVERY_STAGE')
        self._apps('candidate',running=True,healthy=True)
        postgres=self._unchanged(artifacts,allow_restart=True)
        leader=self._leader(artifacts['preserved']['control']['generation'])
        panel=evidence.panel(self.host,artifacts['preserved'])
        appends=evidence.check_notification_history(self.host,artifacts['notification_history'])
        current=(self.host.postgres_after_restart(artifacts['postgres'])
                 if hasattr(self.host,'postgres_after_restart') else self.host.postgres())
        require(current==postgres,'POSTGRES_CHANGED_DURING_FINAL_OBSERVATION')
        return self.journal.advance(stage,'VERIFIED',verified_at=utcnow().isoformat(),
                                    leader=leader,panel=panel,notification_appends=appends,
                                    verified_postgres=postgres)

    def advance(self):
        with self.host.owned():
            for _ in range(15):
                before=self.journal.read()['stage']
                receipt=self.step()
                if receipt['stage']=='VERIFIED': return receipt
                if receipt['stage']==before: return receipt
            require(False,'DELIVERY_STAGE_LIMIT')
