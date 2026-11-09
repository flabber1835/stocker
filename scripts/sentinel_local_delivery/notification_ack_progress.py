"""Prove supported acknowledgement progress without changing retained history."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .host import application_healthy
from .model import Journal, require

SCHEMA = 'sentinel.dashboard-ack-progress/1'
NOTE = 'Reviewed healthy dashboard state; historical payloads and verdicts unchanged.'
_HASH = re.compile('[a-f0-9]{32}')

PROGRAM = r'''import json,os,re,sys
from datetime import datetime,timedelta,timezone
from sentinel.feed import store
from sentinel.panel import review_schema,review_store
expected=json.loads(sys.argv[1])
assert set(expected)=={'schema','alerts','binding','not_before'}
assert expected['schema']=='sentinel.dashboard-ack-progress/1'
alerts=expected['alerts'];assert isinstance(alerts,dict) and 0<len(alerts)<=1000
note='Reviewed healthy dashboard state; historical payloads and verdicts unchanged.'
def clock(value):
 result=datetime.fromisoformat(value) if isinstance(value,str) else value
 assert isinstance(result,datetime) and result.utcoffset()==timedelta(0)
 return result
not_before=clock(expected['not_before'])
c=store.connect(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=3,statement_timeout_ms=4000)
try:
 c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
 review_schema.require_schema(c)
 now=review_store.database_now(c);assert not_before<=now
 binding=c.execute('SELECT deployment_id,broker,broker_account_id,takeover_epoch,ownership_state FROM sentinel_account_binding WHERE id=1').fetchone()
 assert binding and binding[4]=='SENTINEL_OWNED'
 assert dict(zip(('deployment_id','broker','broker_account_id','takeover_epoch'),binding[:4]))==expected['binding']
 scope=review_store.scope(c)
 state=c.execute('SELECT payload,signature FROM sentinel_dashboard_review_state WHERE scope_sha256=%s',(scope,)).fetchone()
 assert state
 review_store.authenticate(dict(scope=scope,state=state[0]),state[1],purpose=review_store.SCHEMA)
 assert state[0]['schema']==review_store.SCHEMA
 rows=c.execute("SELECT a.alert_id,a.ack_state,a.acknowledged_by,a.acknowledged_at,a.acknowledgement,a.state,a.severity,a.created_at,a.delivered_at,"
  "md5(jsonb_build_array(a.alert_id,a.idempotency_key,a.schema_version,a.event_type,a.severity,a.payload,a.created_at,a.ack_state,a.acknowledged_by,a.acknowledged_at,a.acknowledgement)::text),"
  "md5(jsonb_build_array(a.alert_id,a.idempotency_key,a.schema_version,a.event_type,a.severity,a.payload,a.created_at,'UNACKNOWLEDGED'::text,NULL::text,NULL::timestamptz,NULL::text)::text) "
  "FROM sentinel_alert_outbox a WHERE a.alert_id=ANY(%s)",(list(alerts),)).fetchall()
 assert len(rows)==len(alerts)
 events=c.execute("SELECT sequence,event_key,kind,at,payload,signature FROM sentinel_dashboard_review_events "
  "WHERE scope_sha256=%s AND kind='ACKNOWLEDGED' AND (payload->'details'->'alert_ids') ?| %s "
  "ORDER BY sequence LIMIT %s",(scope,list(alerts),2*len(alerts)+1)).fetchall()
 assert len(events)<=2*len(alerts)
 by_alert={key:[] for key in alerts};verified={}
 for sequence,event_key,kind,at,value,signed in events:
  review_store.authenticate(value,signed,purpose=review_store.EVENT_SCHEMA)
  assert set(value)=={'schema','scope','sequence','kind','at','details','previous'}
  assert value['schema']==review_store.EVENT_SCHEMA and value['scope']==scope
  assert value['sequence']==sequence and value['kind']==kind=='ACKNOWLEDGED'
  assert clock(value['at'])==clock(at) and not_before<=at<=now
  assert isinstance(event_key,str) and re.fullmatch('ack:[a-f0-9]{64}',event_key)
  details=value['details'];assert set(details)=={'actor','reviewed_head','alert_ids'}
  actor=details['actor'];inventory=details['alert_ids']
  assert isinstance(actor,str) and 0<len(actor)<=120
  assert type(details['reviewed_head'])is int and details['reviewed_head']==sequence-1
  assert isinstance(inventory,list) and 0<len(inventory)<=1000
  assert all(isinstance(key,str) and 0<len(key)<=200 for key in inventory)
  assert len(inventory)==len(set(inventory))
  previous=c.execute('SELECT payload,signature FROM sentinel_dashboard_review_events WHERE scope_sha256=%s AND sequence=%s',(scope,sequence-1)).fetchone()
  assert previous
  review_store.authenticate(previous[0],previous[1],purpose=review_store.EVENT_SCHEMA)
  assert previous[0]['scope']==scope and previous[0]['sequence']==sequence-1
  assert clock(previous[0]['at'])<=at and value['previous']==previous[1]
  assert type(state[0]['head'])is int and type(state[0]['reviewed_head'])is int
  assert sequence<=state[0]['reviewed_head']<=state[0]['head']
  recorded=c.execute("SELECT alert_id FROM sentinel_alert_outbox WHERE ack_state='ACKNOWLEDGED' AND acknowledged_at=%s AND acknowledged_by=%s AND acknowledgement=%s ORDER BY alert_id LIMIT 1001",(at,actor,note)).fetchall()
  assert len(recorded)<=1000 and {row[0]for row in recorded}==set(inventory)
  verified[sequence]=(actor,at)
  for key in set(inventory)&set(alerts):by_alert[key].append(sequence)
 output={}
 for key,ack_state,actor,at,acknowledgement,delivery,severity,created,delivered,current,unacknowledged in rows:
  assert ack_state=='ACKNOWLEDGED' and delivery=='DELIVERED' and severity=='CRITICAL'
  assert acknowledgement==note and isinstance(actor,str) and actor
  assert clock(created)<=clock(delivered)<=clock(at)<=now and not_before<=at
  assert current==alerts[key]['current']
  assert unacknowledged==alerts[key]['before'],'ORIGINAL_ALERT_DIGEST_CHANGED'
  assert len(by_alert[key])==1
  sequence=by_alert[key][0];assert verified[sequence]==(actor,at)
  output[key]=dict(before=unacknowledged,current=current,event_sequence=sequence)
 print(json.dumps(dict(schema=expected['schema'],scope=scope,alerts=output),sort_keys=True))
finally:c.rollback();c.close()
'''


def _baseline(host, previous):
    """Only the current journal or its already-qualified direct predecessor."""
    folders = [Path(host.operation_dir)]
    predecessor = getattr(host, 'predecessor_receipt', None)
    if predecessor is not None:
        path = Path(predecessor)
        if path.name == 'receipt.json' and path.parent not in folders:
            folders.append(path.parent)
    for index, folder in enumerate(folders):
        if not (folder/'receipt.json').exists() or not (folder/'request.json').exists():
            continue
        journal = Journal(folder)
        require(index != 0 or journal.request == host.request,
            'Existing notification history changed: alerts')
        require(Path(journal.request['deployment']).resolve() == Path(host.request['deployment']).resolve(),
            'Existing notification history changed: alerts')
        record = journal.read();artifacts = record['artifacts']
        if (artifacts.get('notification_history') or {}).get('alerts') != previous:
            continue
        events = [event for event in record['history'] if event['stage'] == 'PREFLIGHT_PASS']
        require(len(events) == 1, 'Existing notification history changed: alerts')
        boundary = datetime.fromisoformat(events[0]['at'])
        require(boundary.utcoffset() is not None and boundary <= datetime.now(timezone.utc),
            'Existing notification history changed: alerts')
        bound = (artifacts.get('preserved') or {}).get('binding')
        require(isinstance(bound, dict) and bound.get('ownership_state') == 'SENTINEL_OWNED'
            and all(bound.get(key) is not None for key in ('deployment_id','broker','broker_account_id','takeover_epoch')),
            'Existing notification history changed: alerts')
        return boundary.isoformat(), {key:bound[key] for key in
            ('deployment_id','broker','broker_account_id','takeover_epoch')}
    require(False, 'Existing notification history changed: alerts')


def prove(host, previous_alerts, current_alerts):
    """A changed digest may progress only through a fully bound supported ACK."""
    reason = 'Existing notification history changed: alerts'
    require(isinstance(previous_alerts,dict) and isinstance(current_alerts,dict)
        and all(isinstance(key,str) and 0<len(key)<=200 and isinstance(value,str)
                and _HASH.fullmatch(value) for mapping in (previous_alerts,current_alerts)
                for key,value in mapping.items()) and set(previous_alerts)<=set(current_alerts), reason)
    changed = {key:dict(before=value,current=current_alerts[key])
               for key,value in previous_alerts.items() if current_alerts[key] != value}
    if not changed:
        return
    require(len(changed)<=1000 and getattr(host,'supports_dashboard_ack_progress',False) is True, reason)
    boundary, binding = _baseline(host,previous_alerts)
    data = host.container('sentinel-panel')
    installed = host.load_values()['SENTINEL_RUNTIME_IMAGE_DIGEST']
    previous = host.request.get('predecessor');candidate = host.request.get('candidate')
    require(isinstance(previous,dict) and isinstance(previous.get('image'),str)
        and re.fullmatch('sha256:[a-f0-9]{64}',previous['image']) and isinstance(candidate,dict),reason)
    admitted = {previous['image']}
    if 'image' in candidate:
        require(isinstance(candidate['image'],str)
            and re.fullmatch('sha256:[a-f0-9]{64}',candidate['image']),reason)
        admitted.add(candidate['image'])
    require(installed in admitted and application_healthy(data,installed), reason)
    expected = dict(schema=SCHEMA,alerts=changed,binding=binding,not_before=boundary)
    result = host.run(['docker','exec',data['Id'],'python','-B','-c',PROGRAM,
        json.dumps(expected,sort_keys=True)],timeout=30)
    try:
        require(len(result.stdout)<=1024*1024,reason)
        proof = json.loads(result.stdout)
        require(isinstance(proof,dict) and set(proof)=={'schema','scope','alerts'}
            and proof['schema']==SCHEMA and isinstance(proof['scope'],str)
            and re.fullmatch('[a-f0-9]{64}',proof['scope']) and isinstance(proof['alerts'],dict)
            and set(proof['alerts'])==set(changed),reason)
        for key, item in proof['alerts'].items():
            require(isinstance(item,dict) and set(item)=={'before','current','event_sequence'}
                and item['before']==changed[key]['before'] and item['current']==changed[key]['current']
                and type(item['event_sequence']) is int and item['event_sequence']>1,reason)
    except (ValueError,TypeError,KeyError):
        require(False,reason)
