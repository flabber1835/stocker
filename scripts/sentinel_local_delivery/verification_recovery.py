"""Explicit fresh final observation; never replay an expired installation."""
from datetime import datetime, timedelta
import re

from . import evidence, readiness
from .host import SERVICES
from .model import (canonical_proof_phase, digest, handoff_mode, require,
                    utcnow, write_new)

SECONDS = 600


def recover(delivery, recovery_id):
    host, journal = delivery.host, delivery.journal
    require(isinstance(recovery_id, str)
        and re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', recovery_id), 'RECOVERY_ID_INVALID')
    with host.owned():
        journal.require_active()
        receipt = journal.read()
        artifacts = receipt['artifacts']
        require(receipt['stage'] == 'APPLICATIONS_STARTED', 'RECOVERY_FINAL_STAGE_REQUIRED')
        require(handoff_mode(host.request) == 'PRE_OPEN'
            and canonical_proof_phase(host.request) == 'PRE_DRAIN'
            and getattr(host, 'supports_verification_recovery', False) is True
            and host.load_values().get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1',
            'RECOVERY_BACKED_PREOPEN_REQUIRED')
        require(isinstance(artifacts.get('started_applications'), dict)
            and set(artifacts['started_applications']) == set(SERVICES),
            'RECOVERY_ORIGINAL_PROCESSES_REQUIRED')
        now = utcnow()
        require(now >= readiness.original_cutoff(receipt, now=now), 'RECOVERY_NOT_EXPIRED')
        end = now + timedelta(seconds=SECONDS)
        deadline = delivery.monotonic() + SECONDS
        intent = dict(schema='sentinel.final-verification-recovery/1',
            recovery_id=recovery_id, request_sha256=journal.subject,
            original_receipt_sha256=digest(receipt), original_receipt=receipt,
            started_at=now.isoformat(), expires_at=end.isoformat(), authority_effect='NONE')
        prefix = journal.folder / ('verification-recovery-' + recovery_id)
        require(not prefix.with_suffix('.json').exists()
            and not prefix.with_suffix('.result.json').exists(), 'RECOVERY_ID_ALREADY_USED')
        write_new(prefix.with_suffix('.json'), intent)

        def budget():
            require(utcnow() < end and delivery.monotonic() < deadline, 'RECOVERY_DEADLINE')

        def installed():
            current, _, candidate = delivery._values(artifacts)
            require(current == candidate, 'RECOVERY_CANDIDATE_NOT_INSTALLED')
            return candidate

        try:
            host.verify_candidate()
            candidate = installed()
            host.verify_compose('candidate')
            hashes = host.candidate_config_hashes(candidate)
            applications = host.wait_applications_health(
                deadline=min(deadline, delivery.monotonic()+120), clock=delivery.monotonic,
                expected=artifacts['started_applications'])
            require(host.candidate_apps_ready(hashes, applications), 'RECOVERY_CONFIGURATION_CHANGED')
            delivery._unchanged(artifacts, native=False)
            budget()
            proof = evidence.canonical_check(host, candidate, artifacts['preserved'])
            require(proof == artifacts['canonical_proof'], 'CANONICAL_ECONOMIC_PROOF_CHANGED')
            proved_at = utcnow().isoformat()
            budget()
            leader = delivery._leader(artifacts['preserved']['control']['generation'], deadline=deadline)
            postgres, appends = delivery._unchanged(artifacts, observation=True)
            require(installed() == candidate, 'RECOVERY_CONFIGURATION_CHANGED')
            budget()
            # Expensive evidence precedes the short-lived published panel fact.
            panel = evidence.panel(host, artifacts['preserved'],
                wait_until=min(end, utcnow()+timedelta(seconds=readiness.SECONDS)))
            leader = delivery._readiness_unchanged(applications, leader)
            require(installed() == candidate, 'RECOVERY_CONFIGURATION_CHANGED')
            boundary = datetime.fromisoformat(panel['installation_panel_valid_until'])
            require(boundary.utcoffset() is not None and utcnow() < boundary,
                'INSTALLATION_PANEL_EXPIRED')
            require(journal.read() == receipt, 'RECOVERY_RECEIPT_CHANGED')
            budget()
            recovery = dict(intent_sha256=digest(intent), recovery_id=recovery_id,
                original_receipt_sha256=digest(receipt), started_at=now.isoformat(),
                expires_at=end.isoformat(), canonical_proof=proof, canonical_verified_at=proved_at,
                authority_effect='NONE')
            result = journal.advance('APPLICATIONS_STARTED', 'VERIFIED',
                verified_at=utcnow().isoformat(), leader=leader, panel=panel,
                notification_appends=appends, verified_postgres=postgres,
                verification_recovery=recovery)
        except Exception as exc:
            write_new(prefix.with_suffix('.result.json'), dict(intent_sha256=digest(intent),
                outcome='REFUSED', error_type=type(exc).__name__, at=utcnow().isoformat()))
            raise
        write_new(prefix.with_suffix('.result.json'), dict(intent_sha256=digest(intent),
            outcome='VERIFIED', receipt_sha256=digest(result), at=utcnow().isoformat()))
        return result
