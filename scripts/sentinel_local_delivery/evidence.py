"""Read-only evidence for one guarded local PAPER application handoff.

The host owns literal configuration, process execution and server-enforced SQL
read bounds. These readers never select a financial subject from a release
constant, mutate controls, or invoke preparation, orders or maintenance.
"""
from __future__ import annotations

import json
import time

from . import checks
from .model import COMPAT_DRAIN_PREDECESSOR, DeliveryRefused, digest, handoff_mode, require


_BINDING_KEYS = ('deployment_id', 'broker', 'broker_account_id', 'takeover_epoch')
_NOTIFICATION_GROUPS = frozenset({
    'alerts', 'delivered_alerts', 'events', 'fanouts', 'recipients', 'delivered_recipients'})
# Host readers stay stdlib-only. A regression binds this complete contract to
# the runtime read_projection.SUBJECT_ENV without importing runtime dependencies.
_VERIFICATION_SUBJECT_ENV = frozenset({
    'SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST', 'SENTINEL_IMAGE_SOURCE_REVISION',
    'SENTINEL_TEST_IMAGE_DIGEST', 'SENTINEL_REVIEWED_DEPLOYMENT_MODE',
    'SENTINEL_SHADOW_OBSERVATION_ID', 'SENTINEL_SHADOW_STARTING_CASH',
    'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256', 'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256',
    'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256', 'SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256',
    'SENTINEL_LOCAL_PAPER_MODE', 'SENTINEL_LOCAL_PAPER_ACCOUNT_ID',
    'SENTINEL_AUTHORIZED_RUNTIME', 'SENTINEL_RUNTIME_BACKUP_AUTHORITY',
    'SENTINEL_RECOVERED_ORDER_AUTHORITY', 'SENTINEL_PAPER_BUY_POLICY',
    'SENTINEL_PAPER_BUY_CAP_BPS', 'SENTINEL_PAPER_DEBUG_WINDOW',
    'SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY'})
_PAPER_SUBJECT_ENV = frozenset({
    'SENTINEL_PAPER_BUY_POLICY', 'SENTINEL_PAPER_BUY_CAP_BPS', 'SENTINEL_PAPER_DEBUG_WINDOW'})
_ROLE_AUTHORITY_ENV = frozenset({
    'SENTINEL_AUTHORIZED_RUNTIME', 'SENTINEL_RUNTIME_BACKUP_AUTHORITY',
    'SENTINEL_RECOVERED_ORDER_AUTHORITY'})


def _require_verification_subject(configuration):
    services = configuration['services']
    environments = {name: services[name]['environment'] for name in (
        'sentinel-panel', 'sentinel-verifier', 'sentinel-shadow', 'sentinel-authorized-cli')}
    panel, verifier = environments['sentinel-panel'], environments['sentinel-verifier']
    for key in sorted(_VERIFICATION_SUBJECT_ENV):
        require(panel.get(key, '') == verifier.get(key, ''), 'VERIFICATION_SUBJECT_MISMATCH: '+key)
    for key in sorted(_VERIFICATION_SUBJECT_ENV - _PAPER_SUBJECT_ENV - _ROLE_AUTHORITY_ENV):
        require(panel.get(key, '') == environments['sentinel-shadow'].get(key, ''),
                'VERIFICATION_BOOK_SUBJECT_MISMATCH: '+key)
    for key in sorted(_PAPER_SUBJECT_ENV):
        require(panel.get(key, '') == environments['sentinel-authorized-cli'].get(key, ''),
                'VERIFICATION_PAPER_SUBJECT_MISMATCH: '+key)


def compare_configuration(host, previous, candidate, state):
    """Compare rendered account/automation contracts in both exact images.

    This command parses configuration only: no database, credentials, volumes or
    broker network are passed to the fingerprint processes. Compose output stays
    private to the host and is never included in evidence records.
    """
    rendered = [json.loads(host.compose(values, 'config', '--format', 'json').stdout)
                for values in (previous, candidate)]
    environments = []
    for configuration, role in zip(rendered, ('predecessor', 'candidate')):
        services = (*host.predecessor_services(),'sentinel-authorized-cli') if role=='predecessor' else (
            'sentinel-shadow','sentinel-automation','sentinel-panel','sentinel-alert-dispatcher',
            'sentinel-authorized-cli','sentinel-verifier','sentinel-execution-collector')
        require(all(configuration['services'][service]['image'] == host.request[role]['image']
                    for service in services), 'Rendered application image does not match the reviewed role')
        panel_environment = configuration['services']['sentinel-panel']['environment']
        require('ALPACA_API_KEY' not in panel_environment and 'ALPACA_SECRET_KEY' not in panel_environment,
                'Panel unexpectedly receives broker credentials')
        if role=='candidate':
            sender=configuration['services']['sentinel-alert-dispatcher']['environment']
            collector=configuration['services']['sentinel-execution-collector']['environment']
            verifier=configuration['services']['sentinel-verifier']['environment']
            require(not sender.get('ALPACA_API_KEY') and not sender.get('ALPACA_SECRET_KEY')
                and not collector.get('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY')
                and not verifier.get('ALPACA_API_KEY') and not verifier.get('ALPACA_SECRET_KEY'),
                'New operational roles have excessive credentials')
            _require_verification_subject(configuration)
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
    mode = handoff_mode(host.request)
    if mode=='POST_TRADE':
        require(getattr(host,'supports_post_trade',False)
            and host.load_values().get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY')=='REQUIRED_V1',
            'POST_TRADE_BACKED_ADAPTER_REQUIRED')
    current = host.sql(checks.snapshot_sql(mode))
    require(isinstance(current, dict) and current.get('candidate_count') == 1,
            'Exactly one current-generation plan matching the handoff mode is required')
    control, cycle, plan = current['control'], current['cycle'], current['plan']
    bound = current.get('binding')
    values = host.load_values()
    require(current['system'] == host.request['predecessor']['system'],
            'PostgreSQL physical system identity changed')
    if values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') == 'REQUIRED_V1':
        require(current['archive_mode'] == 'on' and bool(current['archive_command'])
            and 'archive_command='+current['archive_command'] in host.request['predecessor']['postgres']['command'],
            'Backed database archive policy changed')
    else:
        require(not values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY')
            and current['archive_mode'] == 'off'
            and current['archive_command'] in ('', '(disabled)'),
            'Database suspended archive policy changed')
    require(current['fsync'] == 'on' and current['full_page_writes'] == 'on',
            'Database durability changed')
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
    if mode=='POST_TRADE':
        require(cycle.get('state')=='SUCCEEDED' and cycle.get('completed_at') is not None
            and cycle.get('failure_code') is None and cycle.get('failure_detail') is None
            and isinstance(current.get('reconciliation'),dict)
            and str(current['reconciliation']['seq'])==str(cycle.get('last_clean_reconciliation_id')),
            'POST_TRADE_POSITIVE_RECONCILIATION_REQUIRED')
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
    if handoff_mode(host.request)=='POST_TRADE':
        expected.update(handoff_mode='POST_TRADE',reconciliation_id=state['reconciliation']['seq'])
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


def drain_target(host):
    data=host.container('sentinel-shadow')
    require(data['Image']==host.request['predecessor']['image'] and data['State']['Running'],
            'DRAIN_PREDECESSOR_CHANGED')
    return dict(container=data['Id'],image=data['Image'],restart_policy=data['HostConfig']['RestartPolicy'])


def _compat_barrier(host, values, target):
    config=json.loads(host.compose(values,'config','--format','json').stdout)
    env=config['services']['sentinel-shadow']['environment']
    private={'SENTINEL_PUBLICATION_RECEIPT_KEY':env['SENTINEL_PUBLICATION_RECEIPT_KEY'],
             'SENTINEL_STATE_DIR':'/var/lib/sentinel'}
    container=host.container('sentinel-shadow')
    require(container['Id']==target['container'] and container['Image']==target['image'],
            'COMPATIBILITY_DRAIN_CONTAINER_CHANGED')
    require(container['HostConfig']['RestartPolicy']=={'Name':'no','MaximumRetryCount':0},
            'COMPAT_RESTART_HOLD_CHANGED')
    mounts=[item for item in container['Mounts'] if item['Destination']=='/var/lib/sentinel']
    require(len(mounts)==1 and mounts[0]['Type']=='volume' and mounts[0]['Name']=='sentinel_sentinel_state',
            'COMPATIBILITY_DRAIN_STATE_VOLUME_CHANGED')
    with host.private_environment(private) as path:
        result=host.run(['docker','run','--rm','--pull=never','--network','none','--read-only',
            '--cpus','0.25','--memory','128m','--env-file',path,'--mount',
            'type=volume,src='+mounts[0]['Name']+',dst=/var/lib/sentinel,readonly',
            '--entrypoint','python',host.request['candidate']['image'],'-B','-c',checks.READ_COMPAT_DRAIN,
            host.request['operation_id'],digest(host.request),target['container'],target['image']],timeout=15)
    value=json.loads(result.stdout)
    container=host.container('sentinel-shadow')
    require(container['Id']==target['container'] and container['Image']==target['image'],
            'COMPATIBILITY_DRAIN_CONTAINER_CHANGED')
    require(container['HostConfig']['RestartPolicy']=={'Name':'no','MaximumRetryCount':0},
            'COMPAT_RESTART_HOLD_CHANGED')
    require(not container['State']['Running'] and not container['State']['Restarting'],
            'COMPATIBILITY_BARRIER_NOT_STOPPED')
    return dict(method='EXACT_B2_KERNEL_BARRIER',acknowledgement=value)


def request_drain(host, values, target):
    """Consume an incarnation-bound acknowledgement, never a sampled IDLE."""
    data=host.container('sentinel-shadow')
    require(data['Id']==target['container'] and data['Image']==target['image'],'DRAIN_TARGET_CHANGED')
    if host.request['predecessor']['commit']==COMPAT_DRAIN_PREDECESSOR:
        if not data['State']['Running']:
            return _compat_barrier(host,values,target)
        policy=target['restart_policy']
        require(policy=={'Name':'unless-stopped','MaximumRetryCount':0},'COMPAT_RESTART_POLICY_UNREVIEWED')
        require(data['HostConfig']['RestartPolicy'] in (policy,{'Name':'no','MaximumRetryCount':0}),
                'COMPAT_RESTART_POLICY_CHANGED')
        source=host.source/'sentinel/shadow_drain_compat.py'
        raw=source.read_bytes()
        import hashlib
        require(hashlib.sha256(raw).hexdigest()==host.request['qualification']['source_files']['sentinel/shadow_drain_compat.py'],
                'COMPATIBILITY_HELPER_NOT_QUALIFIED')
        host.run(['docker','update','--restart=no',target['container']],timeout=15)
        require(host.container('sentinel-shadow')['HostConfig']['RestartPolicy']=={'Name':'no','MaximumRetryCount':0},
                'COMPAT_RESTART_HOLD_NOT_INSTALLED')
        response=None
        try:
            result=host.run(['docker','exec','-i',target['container'],'python','-B','-',
                host.request['operation_id'],digest(host.request),target['container'],target['image']],data=raw,timeout=15)
            response=json.loads(result.stdout)
        except DeliveryRefused:
            # tini may tear down docker exec after the exact frozen parent dies.
            # Only an authenticated finite barrier AND stopped container admits it.
            pass
        if response=={'status':'BUSY_BEFORE_BARRIER'}:
            host.run(['docker','update','--restart=unless-stopped',target['container']],timeout=15)
            require(host.container('sentinel-shadow')['HostConfig']['RestartPolicy']==policy,
                    'COMPAT_RESTART_POLICY_NOT_RESTORED')
            require(False,'DRAIN_BUSY_BEFORE_BARRIER')
        return _compat_barrier(host,values,target)
    request=json.loads(host.run(['docker','exec',target['container'],'python','-B','-m','sentinel.shadow_drain',
        'request','--operation-id',host.request['operation_id'],'--request-sha256',digest(host.request)],timeout=15).stdout)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        result=host.run(['docker','exec',target['container'],'python','-B','-m','sentinel.shadow_drain',
            'acknowledged','--operation-id',host.request['operation_id'],'--request-sha256',digest(host.request)],timeout=15)
        acknowledgement=json.loads(result.stdout)
        if acknowledgement is not None:
            require(acknowledgement['request']==request,'DRAIN_REQUEST_REPLACED')
            return dict(method='COOPERATIVE',acknowledgement=acknowledgement)
        time.sleep(2)
    require(False,'DRAIN_ACKNOWLEDGEMENT_DEADLINE')


def check_drain(host, values, target, proof):
    data=host.container('sentinel-shadow')
    require(data['Id']==target['container'] and data['Image']==target['image'],'DRAIN_TARGET_CHANGED')
    if proof['method']=='EXACT_B2_KERNEL_BARRIER':
        require(_compat_barrier(host,values,target)==proof,'COMPATIBILITY_BARRIER_CHANGED')
    else:
        require(proof['method']=='COOPERATIVE','DRAIN_METHOD_UNREVIEWED')
        if not data['State']['Running']:
            # A stopped exact container cannot admit work; finite request still
            # binds the stage, rather than pretending its old live ack is fresh.
            from datetime import datetime,timezone
            expiry=datetime.fromisoformat(proof['acknowledgement']['request']['expires_at'])
            require(datetime.now(timezone.utc)<expiry,'DRAIN_ACKNOWLEDGEMENT_EXPIRED')
            return
        result=host.run(['docker','exec',target['container'],'python','-B','-m','sentinel.shadow_drain',
            'acknowledged','--operation-id',host.request['operation_id'],'--request-sha256',digest(host.request)],timeout=15)
        require(json.loads(result.stdout)==proof['acknowledgement'],'DRAIN_ACKNOWLEDGEMENT_CHANGED')


def migrate_operational_schema(host, candidate):
    result=host.compose(candidate,'run','--rm','--no-deps','--pull','never','--entrypoint','python',
        'sentinel-authorized-cli','-B','-c',checks.INSTALL_OPERATIONAL_SCHEMA,timeout=150)
    value=json.loads(result.stdout)
    require(isinstance(value,dict) and set(value)=={'installation','complete'}
        and type(value['complete']) is bool and isinstance(value['installation'],dict),
        'OPERATIONAL_MIGRATION_RESULT_MALFORMED')
    return value


def panel(host, state):
    """Require a current green page with the same saved plan and healthy sender."""
    data = host.container('sentinel-panel')
    expected = dict(plan=state['plan']['plan_id'],
        decision=state['cycle']['decision_session'], effective=state['cycle']['effective_session'])
    if handoff_mode(host.request)=='POST_TRADE':
        expected['handoff_mode']='POST_TRADE'
    result = host.run(['docker', 'exec', data['Id'], 'python', '-B', '-c', checks.PANEL,
        json.dumps(expected, sort_keys=True)], timeout=35)
    return json.loads(result.stdout)
