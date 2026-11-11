"""One explicit requalification of an interrupted, stopped PRE_OPEN roll."""
from datetime import datetime, timedelta
import re

from . import environment, evidence
from .model import (canonical_proof_phase, digest, handoff_mode, read_json,
                    require, utcnow, write_new)

CERTIFICATE = 'fenced-preflight-recovery.json'


def effective_time(delivery, timestamp):
    path = delivery.journal.folder / CERTIFICATE
    if not path.exists() and not path.is_symlink():
        return timestamp
    value = read_json(path)
    receipt = delivery.journal.read()
    original = value['original']
    count = len(original['history'])
    require(value['schema'] == 'sentinel.fenced-preflight-recovery/1'
        and value['request_sha256'] == delivery.journal.subject
        and value['original_sha256'] == digest(original)
        and original['stage'] == 'COMPOSE_INSTALLED'
        and original['request_sha256'] == delivery.journal.subject
        and count > 0 and receipt['history'][:count] == original['history']
        and all(receipt['artifacts'].get(k) == v for k, v in original['artifacts'].items())
        and value['authority_effect'] == 'NONE',
        'FENCED_RECOVERY_IDENTITY_CHANGED')
    return value['proved_at'] if timestamp == original['artifacts']['preflight_at'] else timestamp


def recover(delivery, recovery_id):
    require(isinstance(recovery_id, str)
        and re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', recovery_id), 'RECOVERY_ID_INVALID')
    host, journal = delivery.host, delivery.journal
    with host.owned():
        journal.require_active()
        receipt = journal.read()
        artifacts = receipt['artifacts']
        require(receipt['stage'] == 'COMPOSE_INSTALLED', 'FENCED_RECOVERY_STOPPED_STAGE_REQUIRED')
        require(handoff_mode(host.request) == 'PRE_OPEN'
            and canonical_proof_phase(host.request) == 'PRE_DRAIN'
            and getattr(host, 'supports_verification_recovery', False) is True,
            'RECOVERY_BACKED_PREOPEN_REQUIRED')
        current, old, candidate = delivery._values(artifacts)
        require(current == old and current.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1',
            'FENCED_RECOVERY_PREDECESSOR_REQUIRED')
        now = utcnow()
        original_at = datetime.fromisoformat(artifacts['preflight_at'])
        require(original_at.utcoffset() is not None
            and now > original_at + timedelta(seconds=900), 'FENCED_RECOVERY_NOT_EXPIRED')
        path = journal.folder / CERTIFICATE
        require(not path.exists() and not path.is_symlink(), 'FENCED_RECOVERY_ALREADY_USED')
        intent = journal.folder / ('fenced-recovery-' + recovery_id + '.json')
        write_new(intent, dict(schema='sentinel.fenced-recovery-intent/1',
            request_sha256=journal.subject, original_sha256=digest(receipt), at=now.isoformat(),
            authority_effect='NONE'))
        deadline = delivery.monotonic() + 600

        def unchanged():
            require(delivery.monotonic() < deadline and utcnow() < now+timedelta(seconds=600),
                'FENCED_RECOVERY_DEADLINE')
            require(journal.read() == receipt, 'FENCED_RECOVERY_RECEIPT_CHANGED')
            require(delivery._values(artifacts)[0] == old, 'FENCED_RECOVERY_CONFIGURATION_CHANGED')
            delivery._stopped_for_install()
            delivery._unchanged(artifacts)
            evidence.check_stopped_drain(host, artifacts['drain_target'], artifacts['drain_proof'])

        host.verify_candidate()
        host.verify_compose('candidate')
        unchanged()
        environment.install(host, old)
        proof = evidence.canonical_check(host, candidate, artifacts['preserved'])
        require(proof == artifacts['canonical_proof'], 'CANONICAL_ECONOMIC_PROOF_CHANGED')
        unchanged()
        value = dict(schema='sentinel.fenced-preflight-recovery/1', recovery_id=recovery_id,
            request_sha256=journal.subject, original=receipt, original_sha256=digest(receipt),
            started_at=now.isoformat(), proved_at=utcnow().isoformat(), authority_effect='NONE')
        write_new(path, value)
    # Ordinary resume reacquires ownership and repeats mutation-boundary checks.
    return delivery.advance()
