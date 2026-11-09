"""Explicit fresh final observation; never replay an expired installation."""
from datetime import datetime, timedelta
import re

from . import evidence, readiness
from .host import SERVICES
from .model import (canonical_proof_phase, digest, handoff_mode, require,
                    utcnow, write_new)

SECONDS = 600


def _completed_post_trade(artifacts, *, now):
    """Reuse only the exact positively reconciled completion already preserved."""
    state = artifacts.get('preserved')
    require(isinstance(state, dict), 'RECOVERY_POST_TRADE_COMPLETION_REQUIRED')
    cycle, plan = state.get('cycle'), state.get('plan')
    reconciliation, control = state.get('reconciliation'), state.get('control')
    require(isinstance(cycle, dict) and isinstance(plan, dict)
        and isinstance(reconciliation, dict) and isinstance(control, dict)
        and cycle.get('state') == 'SUCCEEDED' and cycle.get('historical_state_only') is False
        and cycle.get('completed_at') is not None
        and cycle.get('failure_code') is None and cycle.get('failure_detail') is None
        and isinstance(cycle.get('cycle_id'), str) and bool(cycle['cycle_id'])
        and isinstance(plan.get('plan_id'), str) and bool(plan['plan_id'])
        and cycle.get('plan_id') == plan['plan_id']
        and type(control.get('generation')) is int
        and cycle.get('control_generation') == control['generation']
        and reconciliation.get('seq') is not None
        and str(reconciliation['seq']).isdigit() and int(reconciliation['seq']) > 0
        and str(reconciliation['seq']) == str(cycle.get('last_clean_reconciliation_id')),
        'RECOVERY_POST_TRADE_COMPLETION_REQUIRED')
    try:
        completed = datetime.fromisoformat(cycle['completed_at'])
    except (TypeError, ValueError):
        require(False, 'RECOVERY_POST_TRADE_COMPLETION_CLOCK_INVALID')
    require(completed.utcoffset() is not None and completed <= now+timedelta(seconds=5),
        'RECOVERY_POST_TRADE_COMPLETION_CLOCK_INVALID')


def recover(delivery, recovery_id):
    host, journal = delivery.host, delivery.journal
    require(isinstance(recovery_id, str)
        and re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', recovery_id), 'RECOVERY_ID_INVALID')
    with host.owned():
        journal.require_active()
        receipt = journal.read()
        artifacts = receipt['artifacts']
        require(receipt['stage'] == 'APPLICATIONS_STARTED', 'RECOVERY_FINAL_STAGE_REQUIRED')
        require(host.request == journal.request, 'RECOVERY_REQUEST_CHANGED')
        mode = handoff_mode(host.request)
        require(mode in {'PRE_OPEN', 'POST_TRADE'}
            and canonical_proof_phase(host.request) == 'PRE_DRAIN'
            and getattr(host, 'supports_verification_recovery', False) is True
            and host.load_values().get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1',
            'RECOVERY_BACKED_PREOPEN_REQUIRED')
        if mode == 'POST_TRADE':
            require(getattr(host, 'supports_post_trade', False) is True
                and getattr(host, 'supports_post_trade_verification_recovery', False) is True,
                'RECOVERY_POST_TRADE_BACKED_ADAPTER_REQUIRED')
            _completed_post_trade(artifacts, now=utcnow())
        require(isinstance(artifacts.get('started_applications'), dict)
            and set(artifacts['started_applications']) == set(SERVICES),
            'RECOVERY_ORIGINAL_PROCESSES_REQUIRED')
        now = utcnow()
        require(now >= readiness.original_cutoff(receipt, now=now), 'RECOVERY_NOT_EXPIRED')
        end = now + timedelta(seconds=SECONDS)
        deadline = delivery.monotonic() + SECONDS
        intent = dict(schema='sentinel.final-verification-recovery/1',
            recovery_id=recovery_id, request_sha256=journal.subject, handoff_mode=mode,
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
                authority_effect='NONE', handoff_mode=mode)
            restricted = {}
            if panel.get('installation_review_pending') is True:
                scope = mode+'_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW'
                require(panel.get('operational_ready') is False and panel.get('installation_scope') == scope,
                    'RECOVERY_REVIEW_SCOPE_INVALID')
                restricted = dict(operational_ready=False, installation_scope=scope)
            result = journal.advance('APPLICATIONS_STARTED', 'VERIFIED',
                verified_at=utcnow().isoformat(), leader=leader, panel=panel,
                notification_appends=appends, verified_postgres=postgres,
                verification_recovery=recovery, **restricted)
        except Exception as exc:
            write_new(prefix.with_suffix('.result.json'), dict(intent_sha256=digest(intent),
                outcome='REFUSED', error_type=type(exc).__name__, at=utcnow().isoformat()))
            raise
        write_new(prefix.with_suffix('.result.json'), dict(intent_sha256=digest(intent),
            outcome='VERIFIED', receipt_sha256=digest(result), at=utcnow().isoformat()))
        return result
