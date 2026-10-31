"""Narrow negative formation witnesses for the existing shadow-status CLI."""
from datetime import date, datetime, timedelta, timezone
import json
import re

FORMATION_EXIT = 76
WAIT_MARKER = 'SENTINEL_ACTIVATION_SHADOW_WAIT='
SCHEMA = 'sentinel.activation-shadow-wait/1'

_CODE = r'''
import json,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sentinel import committed_read,rolling_runtime,shadow_runtime,shadow_service,shadow_service_status,shadow_service_probe
from sentinel.feed import calendar,operational_snapshot,readers,rolling_go_inputs
from sentinel.cli.main import main
_original_shadow_status=shadow_runtime.verified_shadow_status

def _owner(config):
    snapshot=shadow_service_probe.observe(Path(os.environ.get('SENTINEL_STATE_DIR','/var/lib/sentinel')))
    value=shadow_service_status.decode_probe(snapshot,config.database_url)
    now=datetime.now(timezone.utc)
    if (value.get('state')!='RUNNING' or value.get('reason') not in {'ACTIVE_WORKER','IDLE'}
            or not -timedelta(seconds=5)<=now-value['observed_at']<=timedelta(seconds=60)):
        raise ValueError('shadow publisher is not currently running')
    if value['reason']=='ACTIVE_WORKER':
        pending=shadow_service_status._decode_pending(snapshot['pending'])
        latest=shadow_service_status._decode_pending(snapshot['latest_pending'])
        if (pending is None or latest is None or pending!=latest
                or pending['attempt_id']!=value['attempt_id'] or not value['worker_deadline']>now):
            raise ValueError('shadow publisher worker ownership or deadline unavailable')
    return value

def _formation(conn,observation_id,starting_cash,reason):
    config=shadow_service.ShadowServiceConfig.from_env()
    if config.observation_id!=observation_id or config.starting_cash!=starting_cash:
        raise ValueError('shadow formation scope differs from its publisher')
    before=_owner(config)
    if before['reason']=='IDLE' and reason!='RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY':
        return None
    state=None
    with committed_read.proof_connection(conn) as proof:
        rolling_go_inputs.require_schemas(proof)
        proof.rollback()
        proof.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with readers.pinned(proof,commit=False) as pub:
            if not readers.is_rolling(pub):
                raise ValueError('shadow formation requires rolling inputs')
            operational_snapshot.require_alpaca_openfigi(proof,pub)
            classified=shadow_runtime.classify_shadow_lineage(proof,
                observation_id=observation_id,starting_cash=starting_cash,
                structural_only=reason!='ROLLING_RUNTIME_ATTESTATION_REQUIRED')
            if classified.get('status')=='VERIFIED':
                return None
            if reason=='ROLLING_RUNTIME_PUBLICATION_CHANGED':
                prior=classified.get('latest_session')
                if (classified.get('status') not in {'ATTESTED_STRUCTURAL','RECONSTRUCTED_STRUCTURAL'}
                        or not isinstance(prior,str)):
                    raise ValueError('shadow publication is not the adjacent formation session')
                if prior==pub.window_end:
                    classified=shadow_runtime.classify_shadow_lineage(proof,
                        observation_id=observation_id,starting_cash=starting_cash,structural_only=False)
                    if classified.get('status')=='VERIFIED':
                        return None
                elif calendar.next_session(prior)==pub.window_end:
                    rolling_go_inputs.validate_status(proof,pub)
                    state='PUBLICATION_AHEAD'
                else:
                    raise ValueError('shadow publication is not the adjacent formation session')
            if reason=='RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY':
                prior=classified.get('latest_session')
                if classified.get('status')!='RECONSTRUCTED_STRUCTURAL' or prior!=pub.window_end:
                    raise ValueError('shadow reconstruction is not the current retained session')
                context=rolling_runtime.initial._context(observation_id,starting_cash)
                checkpoint,_,_,_,_=rolling_runtime._closure(proof,context,status_only=True)
                if checkpoint.publication!=pub.to_dict():
                    raise ValueError('shadow reconstruction publication changed')
                rolling_go_inputs.validate_status(proof,pub)
                state='NEXT_FRESH_SESSION'
            if state is None and (classified.get('status')=='RECOVERY_REQUIRED'
                    and classified.get('recovery_kind')=='TRAILING_CANDIDATE'
                    and classified.get('recovery_session')==pub.window_end):
                state='TRAILING_CANDIDATE'
            if state is None:
                raise ValueError('shadow attestation refusal is not validated formation')
            session=calendar.next_session(pub.window_end) if state=='NEXT_FRESH_SESSION' else pub.window_end
    after=_owner(config)
    if (after['incarnation']!=before['incarnation']
            or after['binding_sha256']!=before['binding_sha256']
            or after['observed_at']<before['observed_at']):
        raise ValueError('shadow publisher changed during formation observation')
    if after['reason']!=before['reason'] or after['attempt_id']!=before['attempt_id']:
        return None
    if after['reason']=='IDLE' and state!='NEXT_FRESH_SESSION':
        return None
    if (after['worker_deadline'] is not None
            and after['worker_deadline']>before['worker_deadline']):
        raise ValueError('shadow worker changed during formation observation')
    return dict(schema='sentinel.activation-shadow-wait/1',state=state,session=session,
        publisher_attempt_id=after['attempt_id'],publisher_binding_sha256=after['binding_sha256'],
        publisher_observed_at=after['observed_at'].isoformat(),
        publisher_deadline=after['worker_deadline'].isoformat() if after['worker_deadline'] is not None else None)

def _status_with_formation(conn,*,observation_id,starting_cash):
    last=None
    for _observation in range(2):
        try:
            return _original_shadow_status(conn,observation_id=observation_id,starting_cash=starting_cash)
        except shadow_runtime.ShadowRuntimeRefused as exc:
            last=exc
            cause=exc.__cause__
            if (type(cause) is not rolling_runtime.Refused or str(cause) not in {
                    'ROLLING_RUNTIME_PUBLICATION_CHANGED','ROLLING_RUNTIME_ATTESTATION_REQUIRED',
                    'RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY'}):
                raise
            wait=_formation(conn,observation_id,starting_cash,str(cause))
            if wait is None:
                continue
            print('SENTINEL_ACTIVATION_SHADOW_WAIT='+json.dumps(wait,sort_keys=True,separators=(',',':')),flush=True)
            raise SystemExit(76)
    raise last

shadow_runtime.verified_shadow_status=_status_with_formation
raise SystemExit(main(['shadow-status']))
'''.strip()


def code():
    return _CODE


def decode_result(result, *, now=None):
    """A formation wait is negative availability evidence, never an attestation."""
    output, errors = result.stdout or '', getattr(result,'stderr','') or ''
    if WAIT_MARKER in errors:
        raise ValueError('shadow formation response used an invalid channel')
    if result.returncode != FORMATION_EXIT:
        if WAIT_MARKER in output:
            raise ValueError('shadow formation response contradicts command status')
        return None
    text = output.strip()
    if not text.startswith(WAIT_MARKER) or len(text.splitlines()) != 1:
        raise ValueError('shadow formation response is malformed')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate shadow formation field')
            value[key] = item
        return value
    def nonfinite(_value):
        raise ValueError('nonfinite shadow formation field')
    value = json.loads(text[len(WAIT_MARKER):], object_pairs_hook=pairs, parse_constant=nonfinite)
    expected = {'schema','state','session','publisher_attempt_id','publisher_binding_sha256',
                'publisher_observed_at','publisher_deadline'}
    if (not isinstance(value,dict) or set(value)!=expected
            or any(type(item) is not str for key,item in value.items()
                   if key not in {'publisher_attempt_id','publisher_deadline'})
            or value['schema']!=SCHEMA or value['state'] not in {'PUBLICATION_AHEAD','TRAILING_CANDIDATE','NEXT_FRESH_SESSION'}
            or not re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}',value['session'])
            or not re.fullmatch('[0-9a-f]{64}',value['publisher_binding_sha256'])):
        raise ValueError('shadow formation identity is malformed')
    date.fromisoformat(value['session'])
    observed = datetime.fromisoformat(value['publisher_observed_at'].replace('Z','+00:00'))
    instant = now or datetime.now(timezone.utc)
    if (observed.utcoffset()!=timedelta(0)
            or not -timedelta(seconds=5)<=instant-observed<=timedelta(seconds=60)):
        raise ValueError('shadow formation clocks are invalid or expired')
    if value['publisher_attempt_id'] is None or value['publisher_deadline'] is None:
        if (value['state']!='NEXT_FRESH_SESSION' or value['publisher_attempt_id'] is not None
                or value['publisher_deadline'] is not None):
            raise ValueError('shadow formation idle ownership is malformed')
    else:
        if (type(value['publisher_attempt_id']) is not str or type(value['publisher_deadline']) is not str
                or not re.fullmatch('[0-9a-f]{32}',value['publisher_attempt_id'])):
            raise ValueError('shadow formation worker identity is malformed')
        deadline = datetime.fromisoformat(value['publisher_deadline'].replace('Z','+00:00'))
        if (deadline.utcoffset()!=timedelta(0) or not observed<=deadline
                or not instant<deadline<=observed+timedelta(seconds=7200)):
            raise ValueError('shadow formation clocks are invalid or expired')
    return value
