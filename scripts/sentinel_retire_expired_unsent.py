"""Qualified host maintenance for an exact enrolled, positively unsent key set.

The embedded program runs in the existing authorized image. It constructs only
the canonical read-only preparation broker and preserves every command key.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


PROGRAM = r'''
import asyncio,json,os,sys
from dataclasses import asdict
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sentinel import authority,binding,schema
from sentinel.automation import store as automation,unsent_recovery
from sentinel.automation_runtime import config_from_env
from sentinel.cli._shared import require_authorized_runtime
from sentinel.cli.automation import _automation_authority,_automation_control_binding
from sentinel.config import SentinelConfig,build_execution_broker
from sentinel.execution import feed_inputs,issuer_admission,journal
from sentinel.execution import reconcile as reconciliation
from sentinel.execution.guarded import PaperPreparationGrant
from sentinel.execution.states import CommandState
from sentinel.feed import calendar,store
from sentinel.feed.rolling_contract import digest
from sentinel.paper.inspection import build_security_resolver,_recovery_account_identity_or_refuse
from sentinel.paper.preparation import _default_paper_strategy
from sentinel.paper.targets import _action_lookup
from sentinel.paper.validation import _guard_broker

def require(condition,reason):
    if not condition:raise RuntimeError(reason)

def now():return datetime.now(timezone.utc)

def event_digest(history):
    return digest([{k:str(v) if isinstance(v,(datetime,Decimal)) else v for k,v in row.items()}
                   for row in history])

def economics(command):
    raw=asdict(command)
    for key in ('state','detail','broker_order_id','filled_quantity','filled_average_price'):
        raw.pop(key,None)
    return json.loads(json.dumps(raw,sort_keys=True,default=str))

def closure_detail(expected,command,retained):
    return 'EXPIRED_UNSENT_RETIRED_V1: '+json.dumps(dict(
        operation_id=expected['operation_id'],keyset_sha256=expected['keyset_sha256'],
        enrollment_sha256=expected['enrollment_sha256'],proof_sha256=digest(retained),
        economics_sha256=digest(economics(command))),sort_keys=True,separators=(',',':'))

def fence(conn,expected,owner):
    current=automation.load_control(conn)
    require(current.enabled and current.kill_switch_engaged and current.generation==expected['generation'],
            'EXACT_ENABLED_KILL_GENERATION_REQUIRED')
    require(binding.require(conn).identity==owner.identity,'ACCOUNT_BINDING_CHANGED')
    require(current.binding.broker_account_id==expected['account']
        and current.binding.deployment_id==expected['deployment']
        and current.binding.takeover_epoch==owner.takeover_epoch
        and current.binding.broker==owner.broker
        and current.binding.certificate_sha256==expected['certificate_sha256'],'CONTROL_BINDING_CHANGED')
    certificate=authority.load_active_signed_certificate(conn,allow_expired_observation_safety=True)
    require(certificate.certificate_sha256==expected['certificate_sha256'],'ACTIVE_CERTIFICATE_CHANGED')
    row=conn.execute('SELECT COALESCE(holder_id IS NOT NULL AND expires_at>clock_timestamp(),false) '
                     'FROM sentinel_automation_lease WHERE id=1').fetchone()
    require(row is not None and row[0] is False,'CURRENT_LEADER_MUST_BE_ABSENT')
    return current

def validate_command(conn,command,retained,expected,observation,evaluated):
    require(not command.is_recovered and command.filled_quantity==0 and command.broker_order_id is None,
            'COMMAND_MAY_HAVE_BEEN_SUBMITTED')
    require(command.client_key==retained['client_key'] and command.identity.plan_id==retained['plan_id'],
            'RETAINED_COMMAND_IDENTITY_CHANGED')
    require(not any(order.client_key==command.client_key for order in observation.orders),'NATIVE_ORDER_EXISTS')
    require(not conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_fills WHERE client_key=%s)',
                            (command.client_key,)).fetchone()[0],'COMMAND_FILL_EXISTS')
    plan=journal.load_plan(conn,command.identity.plan_id)
    require(plan is not None and plan.fingerprint()==retained['plan_fingerprint']
        and (plan.is_superseded or plan.effective_session<evaluated.astimezone(ZoneInfo('America/New_York')).date()),
        'EXACT_OBSOLETE_PLAN_REQUIRED')
    history=journal.command_history(conn,command.client_key)
    detail=closure_detail(expected,command,retained)
    if command.state is CommandState.SUPERSEDED:
        require(bool(history) and history[-1]['from']=='PLANNED' and history[-1]['to']=='SUPERSEDED'
            and Decimal(str(history[-1]['filled'] or 0))==0 and history[-1]['detail']==detail
            and command.detail==detail and event_digest(history[:-1])==retained['events_sha256'],
            'TERMINAL_CLOSURE_DOES_NOT_MATCH_THIS_OPERATION')
    else:
        require(command.state is CommandState.PLANNED,'ONLY_PLANNED_OR_THIS_OPERATION_TERMINAL_ALLOWED')
        proof=issuer_admission._unsent_proof(conn,command,observation,evaluated)
        require(proof is not None and all(proof[key]==retained[key] for key in
            ('client_key','plan_id','plan_fingerprint','events_sha256')),'ENROLLED_NO_TRANSPORT_PROOF_CHANGED')
    return dict(state=command.state.value,economics=economics(command),events_sha256=event_digest(history),
                retained_proof=retained,closure_detail=detail)

def selected(conn,owner,expected):
    commands={command.client_key:command for command in journal.load_commands(conn,owner.identity)}
    require(set(expected['keys'])<=set(commands),'SELECTED_COMMAND_MISSING')
    return {key:commands[key] for key in expected['keys']}

async def run(expected):
    require(require_authorized_runtime('authorize-unsent-paper-recovery') is None,'AUTHORIZED_IMAGE_REQUIRED')
    require(os.environ['SENTINEL_GIT_COMMIT']==expected['runtime_commit']
        and os.environ['SENTINEL_RUNTIME_IMAGE_DIGEST']==expected['image_digest'],'INSTALLED_RUNTIME_CHANGED')
    require(expected['keys']==sorted(set(expected['keys'])) and bool(expected['keys'])
        and digest(expected['keys'])==expected['keyset_sha256'],'EXACT_KEY_SET_REQUIRED')
    config=SentinelConfig.from_env()
    os.environ['PGAPPNAME']='sentinel_retirement_20261027'
    conn=store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
        automation_config=config_from_env()
        with journal.writer_lock(conn):
            owner,rollout,certificate=_automation_authority(conn,config,automation_config)
            require(owner.broker_account_id==expected['account'] and owner.deployment_id==expected['deployment']
                and certificate.certificate_sha256==expected['certificate_sha256'],'FRESH_SIGNED_AUTHORITY_CHANGED')
            fence(conn,expected,owner)
            journal.require_observation_integrity(conn)
            enrollment=issuer_admission.load_enrollment(conn,binding=owner.identity)
            require(enrollment.sha256==expected['enrollment_sha256'],'ENROLLMENT_CHANGED')
            retained={entry['client_key']:entry for entry in enrollment.excluded_unsent_proofs}
            require(len(retained)==len(enrollment.excluded_unsent_proofs)
                and set(retained)==set(expected['keys']),'EXACT_ENROLLED_KEY_SET_REQUIRED')
            initial=selected(conn,owner,expected)
            require(not journal.in_flight_commands(conn,owner.identity),'PENDING_COMMAND_OUTCOME_EXISTS')
            require(all(command.state in {CommandState.PLANNED,CommandState.SUPERSEDED}
                and not command.is_recovered and command.filled_quantity==0 and command.broker_order_id is None
                for command in initial.values()),'SELECTED_COMMAND_MAY_HAVE_BEEN_SUBMITTED')
            with feed_inputs.pinned(conn,commit=False) as pub:
                require(pub.window_end==expected['decision_session'],'CURRENT_PUBLICATION_SESSION_CHANGED')
                resolver=build_security_resolver(conn,calendar.next_session(pub.window_end))
                inner=build_execution_broker(config,resolve_security_id=resolver)
                grant=PaperPreparationGrant(owner.broker_account_id,date.fromisoformat(pub.window_end))
                broker=_guard_broker(conn=conn,broker=inner,grant=grant,base_url=config.base_url,
                    now_provider=now,strategy_provider=lambda:_default_paper_strategy()[1],
                    automation_config_sha256=automation_config.fingerprint)
                read_started=now()
                account=await broker.account_snapshot()
                _recovery_account_identity_or_refuse(account,owner,expected['account'])
                actions=_action_lookup(conn,None,now().astimezone(ZoneInfo(calendar.EXCHANGE_TZ)).date())
                rec=await reconciliation.reconcile(broker=broker,conn=conn,binding=None,
                    deployment=owner.identity,actions=actions,informational_current_book=True)
                observation,facts=issuer_admission._reconciliation(
                    enrollment.binding,rec,now(),clean=True)
                journal.require_observation_integrity(conn)
                require(observation.observed_at>=read_started,'FRESH_REQUEST_OBSERVATION_REQUIRED')
                require(not any(order.is_working for order in observation.orders),'WORKING_NATIVE_ORDER_EXISTS')
                before={key:validate_command(conn,command,retained[key],expected,observation,now())
                        for key,command in initial.items()}
                receipt=dict(schema='sentinel.expired-unsent-retirement/1',request=expected,
                    observation=facts,before=before,after={},broker_mutations=False)
                print(json.dumps(dict(stage='BEFORE',receipt=receipt),sort_keys=True),flush=True)
                for key in expected['keys']:
                    fence(conn,expected,owner)
                    require(issuer_admission.load_enrollment(conn,binding=owner.identity)==enrollment,'ENROLLMENT_DRIFT')
                    evaluated=now()
                    require(timedelta(0)<=evaluated-observation.observed_at<=timedelta(seconds=60),
                            'CURRENT_OBSERVATION_EXPIRED')
                    command=selected(conn,owner,expected)[key]
                    require(economics(command)==before[key]['economics'],'COMMAND_ECONOMICS_CHANGED')
                    checked=validate_command(conn,command,retained[key],expected,observation,evaluated)
                    if command.state is CommandState.PLANNED:
                        journal.save_command(conn,command.transition(CommandState.SUPERSEDED,
                            detail=checked['closure_detail']),previous=CommandState.PLANNED)
                    retired=selected(conn,owner,expected)[key]
                    receipt['after'][key]=validate_command(conn,retired,retained[key],expected,observation,now())
                    print(json.dumps(dict(stage='PROGRESS',receipt=receipt),sort_keys=True),flush=True)
            fence(conn,expected,owner)
            require(all(c.state is CommandState.SUPERSEDED for c in selected(conn,owner,expected).values()),
                    'SELECTED_COMMAND_REMAINS_OPEN')
            if expected.get('recover') is True:
                fresh,rollout,certificate=_automation_authority(conn,config,automation_config)
                require(fresh.identity==owner.identity and certificate.certificate_sha256==expected['certificate_sha256'],
                        'RECOVERY_SIGNED_AUTHORITY_CHANGED')
                generation,authorization=unsent_recovery.authorize(conn,
                    binding=_automation_control_binding(fresh,rollout,certificate,automation_config),
                    decision_session=expected['decision_session'],blocked_cycle_id=expected['blocked_cycle_id'],
                    actor=expected['actor'],reason=expected['reason'],now=now(),automation_config=automation_config)
                require(generation==expected['generation']+1,'RECOVERY_GENERATION_CHANGED')
                fresh,rollout,certificate=_automation_authority(conn,config,automation_config)
                require(fresh.identity==owner.identity and certificate.certificate_sha256==expected['certificate_sha256'],
                        'RELEASE_SIGNED_AUTHORITY_CHANGED')
                control=automation.release_kill(conn,expected_binding=_automation_control_binding(
                    fresh,rollout,certificate,automation_config),actor=expected['actor'],reason=expected['reason'])
                require(control.generation==expected['generation']+2 and control.kill_switch_engaged is False,
                        'RELEASE_GENERATION_OR_KILL_CHANGED')
                receipt['recovery']=dict(authorization=authorization.model_dump(mode='json',by_alias=True),
                    generation=control.generation,kill_switch_engaged=control.kill_switch_engaged)
            receipt['completed_at']=now().isoformat()
            print(json.dumps(dict(stage='COMPLETE',receipt=receipt),sort_keys=True),flush=True)
            return receipt
    finally:conn.close()

if __name__=='__main__':asyncio.run(run(json.loads(sys.argv[1])))
'''


def program_sha256():
    return hashlib.sha256(PROGRAM.encode()).hexdigest()


def sealed_program(expected):
    """Hash the exact literal before executing it in the existing image."""
    if expected.get('program_sha256') != program_sha256():
        raise ValueError('PROGRAM_DIGEST_CHANGED')
    return ('import hashlib;source=' + repr(PROGRAM) +
            ';assert hashlib.sha256(source.encode()).hexdigest()==' + repr(program_sha256()) +
            ';exec(compile(source,"<qualified-unsent-retirement>","exec"))')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('operation', 'request', 'receipt', 'confirm-program-sha256'):
        parser.add_argument('--'+field, required=True)
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args(argv)
    from sentinel_backed_local_patch import BackedHost
    from sentinel_local_delivery.model import Journal, read_json, require, write_new
    operation = Journal(Path(args.operation).resolve())
    require(operation.read()['stage'] == 'VERIFIED', 'SOFTWARE_INSTALLATION_NOT_VERIFIED')
    require(args.confirm_program_sha256 == program_sha256(), 'PROGRAM_NOT_CONFIRMED')
    require(600 <= args.timeout <= 3600, 'FINITE_MAINTENANCE_TIMEOUT_REQUIRED')
    expected = read_json(args.request)
    require(re.fullmatch('[a-z0-9][a-z0-9-]{0,79}', expected['operation_id']) is not None, 'OPERATION_ID_INVALID')
    require(type(expected['generation']) is int and expected['generation'] > 0, 'GENERATION_INVALID')
    require(not Path(args.receipt).exists(), 'MAINTENANCE_RECEIPT_ALREADY_EXISTS')
    expected.update(recover=args.recover, program_sha256=program_sha256(),
                    host_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    host = BackedHost(operation.request, Path(args.operation).resolve())
    values = host.load_values()
    require(values['SENTINEL_GIT_COMMIT'] == expected['runtime_commit']
            and values['SENTINEL_RUNTIME_IMAGE_DIGEST'] == expected['image_digest'], 'INSTALLED_RUNTIME_CHANGED')
    require(operation.request['candidate']['commit'] == expected['runtime_commit']
            and operation.request['candidate']['image'] == expected['image_digest'], 'VERIFIED_INSTALLATION_RUNTIME_CHANGED')
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = host.compose(values, 'run', '--rm', '--no-deps', '--pull', 'never', '-T', '--entrypoint', 'python',
            'sentinel-authorized-cli', '-B', '-c', sealed_program(expected),
            json.dumps(expected, sort_keys=True), timeout=args.timeout)
        output = result.stdout.decode('utf-8') if isinstance(result.stdout, bytes) else result.stdout
        events = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
        require(events and events[-1]['stage'] == 'COMPLETE', 'MAINTENANCE_DID_NOT_COMPLETE')
    except BaseException as exc:
        write_new(args.receipt, dict(schema='sentinel.expired-unsent-host-result/1',
            status='REFUSED_OR_PARTIAL',request=expected,started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),exception_type=type(exc).__name__,
            process_returncode=None,requires_durable_audit=True))
        raise
    receipt = dict(events[-1]['receipt'],status='COMPLETE',process_returncode=result.returncode,
        host_started_at=started,host_finished_at=datetime.now(timezone.utc).isoformat())
    write_new(args.receipt, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
