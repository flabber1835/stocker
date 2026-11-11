"""Authenticated, finite display composition between two owned subprocesses."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
import tempfile
import uuid

from sentinel.panel import operational_snapshot as snapshots, review_store

MAX_BYTES = 2*1024*1024
SECONDS = 30
PURPOSE = 'sentinel-operational-composition-v1'


class Pending(ValueError):
    pass


class Failed(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('full operational composition unavailable')


def path(instance):
    if str(uuid.UUID(instance)) != instance:
        raise ValueError('composition instance invalid')
    return Path(tempfile.gettempdir())/('sentinel-composition-'+instance+'.json')


def stable_boundary(panel):
    discovery = any(row.key == 'automation_cycle' and row.operational_fact is not None
        and row.operational_fact.state == 'DISCOVERY_WAIT' for row in panel.rows)
    rows = [row for row in panel.rows if row.key not in {'automation_leader','shadow_worker','alert_dispatcher'}
        and not (discovery and (row.key == 'automation_cycle' or row.key.startswith('automation_step_')))]
    return min(panel.now+timedelta(seconds=SECONDS),
        snapshots.original_boundary(replace(panel, rows=rows)))


def native_services(conn, rows, *, worker=None):
    from sentinel.panel import model, sources
    replacements={}
    if worker is not None:
        replacements['shadow_worker']=worker
    if any(row.key=='alert_dispatcher' for row in rows):
        alerts=next((row for row in rows if row.key=='automation_alerts'),None)
        recovery=alerts.recovery if alerts is not None else None
        required=bool(os.environ.get('SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY','').strip())
        counts=sources._push_subscription_counts(conn) if required else {}
        replacements['alert_dispatcher']=model.alert_dispatcher_row(installed=True,
            dispatchers=sources._alert_dispatchers(conn),push_required=required,**counts,
            retry_attempt=recovery.attempt if recovery is not None else None,
            retry_max_attempts=recovery.maximum_attempts if recovery is not None else None,
            next_attempt_at=recovery.next_attempt_at if recovery is not None else None)
    return [replacements.get(row.key,row) for row in rows]


def _write(instance, value):
    payload = dict(value=value, signature=review_store.signature(value, purpose=PURPOSE))
    raw = json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('composition exceeds bound')
    target = path(instance)
    descriptor, temporary = tempfile.mkstemp(prefix=target.name+'.',dir=target.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            os.fchmod(stream.fileno(),0o600)
            stream.write(raw)
        os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def failure(owner_id, instance, exc):
    from sentinel.panel import observer_failure
    _write(instance,dict(schema=PURPOSE,owner=owner_id,instance=instance,outcome='FAILED',
        diagnostic=observer_failure.classify(exc).model_dump(mode='json',by_alias=True)))


def collect(database_url, owner_id, state_dir, instance, *, shadow_observer=None):
    from sentinel.panel import projection_service as producer, segment_disclosure, sources
    from sentinel.panel.serialization import preflight
    context,subjects,basis = producer._display_coordinates(database_url)
    panel = segment_disclosure.disclose(sources.build_panel(state_dir=Path(state_dir),
        database_url=database_url,shadow_observer=shadow_observer),database_url)
    panel = replace(panel, display_basis=basis)
    if producer._coordinates(database_url) != (context,subjects):
        raise producer.CollectionSuperseded('composition inputs changed')
    preflight(panel)
    raw = snapshots._PANEL.dump_python(panel,mode='json',warnings='error')
    snapshots._validate_panel(raw)
    boundary = stable_boundary(panel)
    if datetime.now(timezone.utc) >= boundary:
        raise producer.CollectionSuperseded('composition expired before completion')
    _write(instance,dict(schema=PURPOSE,owner=owner_id,instance=instance,outcome='PUBLISHED',
        context=context,subjects=subjects,panel=raw,valid_until=boundary.isoformat()))
    return dict(outcome='PUBLISHED',valid_until=boundary.isoformat())


def read(owner_id, instance, *, now):
    target = path(instance)
    try:
        with target.open('rb') as stream:
            raw = stream.read(MAX_BYTES+1)
    except FileNotFoundError:
        raise Pending('composition not yet available') from None
    if target.is_symlink() or len(raw)>MAX_BYTES:
        raise ValueError('composition file invalid')
    envelope=json.loads(raw)
    if not isinstance(envelope,dict) or set(envelope)!={'value','signature'}:
        raise ValueError('composition envelope invalid')
    value=envelope['value']
    if (not isinstance(value,dict) or value.get('schema')!=PURPOSE
        or value.get('owner')!=owner_id or value.get('instance')!=instance
        or not isinstance(envelope['signature'],str)
        or not hmac.compare_digest(envelope['signature'],review_store.signature(value,purpose=PURPOSE))):
        raise ValueError('composition authentication failed')
    if value.get('outcome')=='FAILED':
        from sentinel.panel.observer_failure import Failure
        if set(value)!={'schema','owner','instance','outcome','diagnostic'}:
            raise ValueError('composition failure shape invalid')
        raise Failed(Failure.model_validate(value['diagnostic']).model_dump(mode='json',by_alias=True))
    if set(value)!={'schema','owner','instance','outcome','context','subjects','panel','valid_until'} or value['outcome']!='PUBLISHED':
        raise ValueError('composition shape invalid')
    panel=snapshots._validate_panel(value['panel'])
    expiry=datetime.fromisoformat(value['valid_until'])
    if (expiry.utcoffset()!=timedelta(0) or not panel.now<=now<expiry
        or expiry>stable_boundary(panel)):
        raise Pending('composition expired or clock reversed')
    return panel,value['context'],value['subjects'],expiry
