"""Read-only evidence for one guarded local PAPER application handoff.

The host owns literal configuration, process execution and server-enforced SQL
read bounds. These readers never select a financial subject from a release
constant, mutate controls, or invoke preparation, orders or maintenance.
"""
from __future__ import annotations

import json

from . import checks
from .model import require


_BINDING_KEYS = ('deployment_id', 'broker', 'broker_account_id', 'takeover_epoch')
_NOTIFICATION_GROUPS = frozenset({
    'alerts', 'delivered_alerts', 'events', 'fanouts', 'recipients', 'delivered_recipients'})


def compare_configuration(host, previous, candidate, state):
    """Compare rendered account/automation contracts in both exact images.

    This command parses configuration only: no database, credentials, volumes or
    broker network are passed to the fingerprint processes. Compose output stays
    private to the host and is never included in evidence records.
    """
    services = ('sentinel-shadow', 'sentinel-automation', 'sentinel-panel',
                'sentinel-alert-dispatcher', 'sentinel-authorized-cli')
    rendered = [json.loads(host.compose(values, 'config', '--format', 'json').stdout)
                for values in (previous, candidate)]
    environments = []
    for configuration, role in zip(rendered, ('predecessor', 'candidate')):
        require(all(configuration['services'][service]['image'] == host.request[role]['image']
                    for service in services), 'Rendered application image does not match the reviewed role')
        panel_environment = configuration['services']['sentinel-panel']['environment']
        require('ALPACA_API_KEY' not in panel_environment and 'ALPACA_SECRET_KEY' not in panel_environment,
                'Panel unexpectedly receives broker credentials')
        environment = configuration['services']['sentinel-automation']['environment']
        environments.append({key: value for key, value in environment.items()
            if key.startswith('SENTINEL_AUTOMATION_') or key == 'SENTINEL_PAPER_DEBUG_WINDOW'})
    require(environments[0] == environments[1], 'Automation configuration changed between images')
    for role in ('predecessor', 'candidate'):
        result = host.run(['docker', 'run', '--rm', '-i', '--pull=never', '--network', 'none',
            '--cpus', '0.5', '--memory', '384m', '--entrypoint', 'python', host.request[role]['image'],
            '-B', '-c', checks.AUTOMATION_CONFIG], data=json.dumps(environments[0]).encode(), timeout=60)
        require(result.stdout.decode().strip() == state['control']['config_sha256'],
                'Image automation fingerprint does not match current control')


def snapshot(host):
    """Select exactly one current, prepared future cycle and its source closure."""
    current = host.sql(checks.SNAPSHOT_SQL)
    require(isinstance(current, dict) and current.get('candidate_count') == 1,
            'Exactly one current-generation future WAITING_OPEN plan is required')
    control, cycle, plan = current['control'], current['cycle'], current['plan']
    bound = current.get('binding')
    values = host.load_values()
    require(current['system'] == host.request['predecessor']['system'],
            'PostgreSQL physical system identity changed')
    require(current['archive_mode'] == 'off'
            and current['archive_command'] in ('', '(disabled)')
            and current['fsync'] == 'on' and current['full_page_writes'] == 'on',
            'Database durability or suspended archive policy changed')
    require(control['enabled'] is True and control['kill_switch_engaged'] is False
            and control['authority_verdict'] == 'PASS'
            and control['broker'] == 'alpaca'
            and control['broker_account_id'] == values['SENTINEL_LOCAL_PAPER_ACCOUNT_ID'],
            'Current control does not match the enabled local PAPER account')
    require(isinstance(bound, dict) and bound.get('ownership_state') == 'SENTINEL_OWNED'
            and all(bound.get(key) == control.get(key) for key in _BINDING_KEYS),
            'Durable account binding does not match current control')
    require(current['ready'] is True and cycle['plan_id'] == plan['plan_id']
            and cycle['control_generation'] == control['generation'],
            'Saved plan is not ready with sufficient future execution margin')
    for key in (*_BINDING_KEYS, 'certificate_sha256', 'rollout_mode',
                'rollout_version', 'config_sha256'):
        require(cycle[key] == control[key], 'Plan/control binding changed: '+key)
    require(current['inflight'] == 0 and current['other_active'] == 0,
            'An uncertain command or another active financial cycle exists')
    require(current['jobs_active'] == 0 and current['job_live_owners'] == 0,
            'Source acquisition/preparation remains active; leave it uninterrupted')
    source, publication = current['source_binding'], current['publication']
    require(publication['window_end'] == cycle['decision_session']
            and isinstance(source, dict) and source['job_state'] == 'PUBLISHED'
            and source['job_publication'] == publication['version'],
            'Current plan source publication is incomplete')
    require(current['authority_md5'] is not None
            and current['push_subscriptions']['active'] > 0
            and current['push_policy_md5'] is not None,
            'Prepared sizing authority or notification policy is absent')
    return current


def canonical_check(host, values, state):
    """Return the complete current-image proof for exact predecessor comparison."""
    bound = {key: state['binding'][key] for key in _BINDING_KEYS}
    bound.update(ownership_state=state['binding']['ownership_state'],
                 notes=state['binding'].get('notes') or '')
    expected = dict(plan=state['plan']['plan_id'], version=state['publication']['version'],
        account=state['control']['broker_account_id'], binding=bound,
        config=state['control']['config_sha256'],
        decision=state['cycle']['decision_session'], effective=state['cycle']['effective_session'])
    result = host.compose(values, 'run', '--rm', '--no-deps', '--pull', 'never',
        '--entrypoint', 'python', 'sentinel-authorized-cli', '-B', '-c', checks.CANONICAL,
        json.dumps(expected, sort_keys=True), timeout=300)
    proof = json.loads(result.stdout)
    require(isinstance(proof, dict) and proof.get('transaction_read_only') is True,
            'Canonical evidence did not confirm server read-only execution')
    require(proof.get('plan') == expected['plan'], 'Canonical proof returned a different plan')
    return proof


def native_positions(host, values):
    """GET-only exact PAPER account identity, zero open orders, native quantities."""
    require(values.get('ALPACA_BASE_URL') == 'https://paper-api.alpaca.markets'
            and bool(values.get('SENTINEL_LOCAL_PAPER_ACCOUNT_ID')),
            'Native observation requires the explicit local PAPER account')
    result = host.compose(values, 'run', '--rm', '--no-deps', '--pull', 'never',
        '--entrypoint', 'python', 'sentinel-authorized-cli', '-B', '-c',
        checks.NATIVE_POSITIONS, timeout=60)
    positions = json.loads(result.stdout)
    require(isinstance(positions, dict), 'Native positions result is malformed')
    return positions


def notification_history(host):
    current = host.sql(checks.NOTIFICATION_SQL)
    require(isinstance(current, dict) and set(current) == _NOTIFICATION_GROUPS
            and all(isinstance(records, dict) for records in current.values()),
            'Notification history is incomplete')
    return current


def check_notification_history(host, previous):
    """Allow append/progress while retaining payloads, acks and delivered receipts."""
    require(isinstance(previous, dict) and set(previous) == _NOTIFICATION_GROUPS
            and all(isinstance(records, dict) for records in previous.values()),
            'Predecessor notification history is incomplete')
    current = notification_history(host)
    for group, records in previous.items():
        require(all(current[group].get(key) == value for key, value in records.items()),
                'Existing notification history changed: '+group)
    return {group: len(set(current[group])-set(previous[group])) for group in previous}


def leader(host):
    return host.sql("SELECT json_build_object('holder',holder_id,'fence',fence_token,"
        "'generation',control_generation,'heartbeat',heartbeat_at,"
        "'current',heartbeat_at>clock_timestamp()-interval '60 seconds' "
        "AND expires_at>clock_timestamp()) FROM sentinel_automation_lease WHERE id=1")


def idle(host, image):
    """Sample exact-image healthy IDLE and absence of a pending/active child."""
    data = host.container('sentinel-shadow')
    require(data['Image'] == image and data['State']['Running'] is True
            and data['State'].get('Health', {}).get('Status') == 'healthy'
            and not data['State']['Restarting'] and not data['State']['OOMKilled'],
            'The exact shadow runtime is not healthy')
    result = host.run(['docker', 'exec', data['Id'], 'python', '-B', '-c', checks.IDLE], timeout=15)
    return json.loads(result.stdout)


def panel(host, state):
    """Require a current green page with the same saved plan and healthy sender."""
    data = host.container('sentinel-panel')
    expected = dict(plan=state['plan']['plan_id'],
        decision=state['cycle']['decision_session'], effective=state['cycle']['effective_session'])
    result = host.run(['docker', 'exec', data['Id'], 'python', '-B', '-c', checks.PANEL,
        json.dumps(expected, sort_keys=True)], timeout=35)
    return json.loads(result.stdout)
