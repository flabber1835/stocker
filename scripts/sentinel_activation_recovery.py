"""Explicit operator recovery at the existing killed activation checkpoint."""
from datetime import date
import re


def validate(value):
    import sentinel_autonomous_deploy as core
    if (not isinstance(value, dict) or set(value) != {
            'blocked_cycle_id', 'decision_session', 'actor', 'reason', 'confirmed'}
            or value['confirmed'] is not True
            or any(not isinstance(value[k], str) or not value[k].strip()
                   for k in ('blocked_cycle_id', 'decision_session', 'actor', 'reason'))
            or re.fullmatch('[0-9a-f]{64}', value['blocked_cycle_id']) is None
            or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['decision_session']) is None):
        raise core.DeployRefused('activation unsent recovery confirmation is malformed')
    try:
        date.fromisoformat(value['decision_session'])
    except ValueError as exc:
        raise core.DeployRefused('activation recovery decision is malformed') from exc
    return dict(value)


def authorize_requested(obj, certificate, decision_session):
    import sentinel_autonomous_deploy as core
    from sentinel_phase_records import publish_immutable
    requested = getattr(obj, 'requested_unsent_recovery', None)
    if requested is None:
        return
    value = validate(requested)
    if value['decision_session'] != decision_session:
        raise core.DeployRefused('activation recovery decision differs from current shadow')
    obj._require_activation_writers_stopped()
    status = obj._automation_status()
    if (status.get('enabled') is not True or status.get('kill_switch_engaged') is not True
            or status.get('certificate_sha256') != certificate):
        raise core.DeployRefused('activation recovery lost its exact enabled kill fence')
    obj.phase('recovery: authorize the explicitly confirmed unsent cycle before kill release')
    completed = obj._authorized_cli([
        'authorize-unsent-paper-recovery', '--confirm-paper-account', obj.cfg.account_id,
        '--confirm-deployment-id', obj.cfg.deployment_id,
        '--confirm-certificate-sha256', certificate,
        '--decision-session', value['decision_session'],
        '--blocked-cycle-id', value['blocked_cycle_id'], '--confirm-old-writer-fenced',
        '--confirm-authorize-unsent-paper-recovery', '--actor', value['actor'],
        '--reason', value['reason']], capture=True)
    result = core._json_output(completed, label='unsent recovery authorization')
    auth = result.get('authorization') or {}
    if not isinstance(auth, dict) or not isinstance(auth.get('binding'), dict):
        raise core.DeployRefused('activation recovery receipt is malformed')
    binding = auth.get('binding') or {}
    if (result.get('broker_contacted') is not False
            or type(result.get('generation')) is not int or result['generation'] < 1
            or auth.get('schema') != 'sentinel.unsent-recovery/1'
            or auth.get('blocked_cycle_id') != value['blocked_cycle_id']
            or auth.get('decision_session') != decision_session
            or binding.get('certificate_sha256') != certificate
            or binding.get('deployment_id') != obj.cfg.deployment_id
            or binding.get('broker_account_id') != obj.cfg.account_id):
        raise core.DeployRefused('activation recovery receipt does not match the requested scope')
    after = obj._automation_status()
    if (after.get('enabled') is not True or after.get('kill_switch_engaged') is not True
            or after.get('certificate_sha256') != certificate
            or after.get('control_generation') != result.get('generation')):
        raise core.DeployRefused('activation recovery did not retain its authorized kill fence')
    publish_immutable(obj.attempt_dir/'unsent-recovery-authorization.json', result)
