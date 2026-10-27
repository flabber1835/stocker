"""Read-only server programs used by the resumable local PAPER installer.

These programs do not accept source code or SQL from an operation receipt.
Canonical comparison obtains a fresh server-enforced read-only connection on
all attempts. Only typed corpus contention is retried within original clocks."""

AUTOMATION_CONFIG = r'''import json,sys
from sentinel.automation_runtime import config_from_env
print(config_from_env(json.load(sys.stdin)).fingerprint)
'''

INSTALL_OPERATIONAL_SCHEMA = r'''import json,time
from sentinel import operational_schema,mirror_projection
from sentinel.execution import journal,evidence_projection
from sentinel.feed import store
import os
c=store.connect(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=3,statement_timeout_ms=15000)
try:
    installation=operational_schema.install_quiescent(c)
    end=time.monotonic()+90
    complete=False
    while time.monotonic()<end:
        proof=journal.bootstrap_observation_integrity(c,limit=128)
        c.commit()
        if proof['body']['stage']!='COMPLETE':
            c.rollback()
            continue
        proof=journal.advance_observation_integrity(c,limit=128)
        c.commit()
        if proof['through']!=evidence_projection.head(c,'OBSERVATION')[1]:
            c.rollback()
            continue
        c.rollback()
        proof=mirror_projection.bootstrap_step(c,limit=128)
        c.commit()
        if proof['body']['stage']!='COMPLETE':
            continue
        version,through=c.execute('SELECT version,window_end FROM sentinel_corpus_publications ORDER BY version DESC LIMIT 1').fetchone()
        c.rollback()
        proof=mirror_projection.advance(c,checked_through=through,publication_version=version,limit=128)
        c.commit()
        if (proof['body']['stage']=='COMPLETE' and proof['through']==evidence_projection.head(c,'MIRROR')[1]
                and proof['body']['checked_publication']==version and proof['body']['checked_through']==through.isoformat()):
            c.rollback()
            journal.require_observation_integrity(c)
            mirror_projection.require_current(c,current_frontier=through,current_publication_version=version)
            c.rollback()
            complete=True
            break
        c.rollback()
    print(json.dumps(dict(installation=installation,complete=complete),default=str,sort_keys=True))
finally:
    c.rollback();c.close()
'''

READ_COMPAT_DRAIN = r'''import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from sentinel import shadow_drain_compat as bridge
state=Path(os.environ.get('SENTINEL_STATE_DIR','/var/lib/sentinel'))
value=bridge.validate(bridge._load(state),operation_id=sys.argv[1],request_sha256=sys.argv[2],
    container_id=sys.argv[3],image=sys.argv[4],now=datetime.now(timezone.utc))
print(json.dumps(value,sort_keys=True))
'''

ISSUER_EVIDENCE_PREFIXES = (
    'protected-buy-funding:v1:issuer-policy:v1:enrollment:',
    'protected-buy-funding:v1:issuer-policy:v1:source:',
    'protected-buy-funding:v1:issuer-policy:v1:plan:',
    'protected-buy-funding:v1:issuer-policy:v1:claim:',
    'protected-buy-funding:v1:issuer-policy:v1:shortfall:',
)
EMPTY_ISSUER_EVIDENCE_MD5 = 'd41d8cd98f00b204e9800998ecf8427e'
# Exact operational prefixes preserve their complete rows in the existing
# bounded snapshot. LIKE keeps prefix meaning independent of database collation.
_ISSUER_EVIDENCE_FILTER = ' OR '.join(
    "x.cursor_name LIKE '"+prefix+"%'"
    for prefix in ISSUER_EVIDENCE_PREFIXES)

_SNAPSHOT_SQL = r'''WITH candidates AS (
 SELECT s.* FROM sentinel_automation_cycles s
 JOIN sentinel_automation_control c ON c.id=1
   AND s.deployment_id=c.deployment_id AND s.broker=c.broker
   AND s.broker_account_id=c.broker_account_id AND s.takeover_epoch=c.takeover_epoch
   AND s.control_generation=c.generation AND s.config_sha256=c.config_sha256
 WHERE __CANDIDATE_FILTER__ AND NOT s.historical_state_only
), latest_publication AS (
 SELECT * FROM sentinel_corpus_publications ORDER BY version DESC LIMIT 1
)
SELECT json_build_object(
 'system',(SELECT system_identifier::text FROM pg_control_system()),
 'archive_mode',current_setting('archive_mode'),
 'archive_command',current_setting('archive_command'),
 'fsync',current_setting('fsync'),'full_page_writes',current_setting('full_page_writes'),
 'candidate_count',(SELECT count(*) FROM candidates),
 'control',to_jsonb(c)-'authority_checked_at'-'authority_detail'-'updated_at',
 'binding',(SELECT to_jsonb(b) FROM sentinel_account_binding b WHERE b.id=1),
 'cycle',to_jsonb(s)-'updated_at'-'last_fence_token'-'next_wake_at',
 'plan',json_build_object('plan_id',p.plan_id,'fingerprint',md5(to_jsonb(p)::text),
   'target_basket',p.target_basket,'publication_fingerprint',p.publication_fingerprint),
 'ready',(__READY_FILTER__) AND p.superseded_by IS NULL,
 __SETTLED_FACT__
 'inflight',(SELECT count(*) FROM sentinel_commands WHERE state IN
   ('SEND_PENDING','ACKNOWLEDGED','UNKNOWN','PARTIALLY_FILLED','CANCEL_PENDING')),
 'other_active',(SELECT count(*) FROM sentinel_automation_cycles x
   WHERE x.cycle_id<>s.cycle_id AND x.broker_account_id=c.broker_account_id
   AND x.state IN ('DISCOVERED','REFRESHING_DATA','PREPARING','PLAN_READY',
                   'WAITING_OPEN','EXECUTING','RECONCILING','RETRY_WAIT')),
 'jobs_active',(SELECT count(*) FROM sentinel_snapshot_jobs
   WHERE state NOT IN ('REFUSED','ABORTED','PUBLISHED')),
 'job_live_owners',(SELECT count(*) FROM sentinel_snapshot_jobs
   WHERE owner IS NOT NULL AND lease_until>clock_timestamp()),
 'jobs_md5',(SELECT md5(coalesce(string_agg(md5(to_jsonb(x)::text),'' ORDER BY x.job_id),''))
   FROM sentinel_snapshot_jobs x),
 'publication',json_build_object('version',pub.version,'window_end',pub.window_end,
   'identity_md5',md5(to_jsonb(pub)::text)),
 'source_binding',(SELECT json_build_object('job',b.job_id,'candidate',b.candidate_id,
   'validation',b.validation_sha256,'job_state',j.state,
   'job_publication',j.publication_version,'job_md5',md5(to_jsonb(j)::text))
   FROM sentinel_operational_snapshots b JOIN sentinel_snapshot_jobs j USING(job_id)
   WHERE b.publication_version=pub.version),
 'commands_count',(SELECT count(*) FROM sentinel_commands),
 'commands_md5',(SELECT md5(coalesce(string_agg(md5(to_jsonb(x)::text),'' ORDER BY x.client_key),''))
   FROM sentinel_commands x),
 'events_count',(SELECT count(*) FROM sentinel_command_events),
 'events_md5',(SELECT md5(coalesce(string_agg(md5(to_jsonb(x)::text),'' ORDER BY x.seq),''))
   FROM sentinel_command_events x),
 'fills_count',(SELECT count(*) FROM sentinel_fills),
 'fills_md5',(SELECT md5(coalesce(string_agg(md5(to_jsonb(x)::text),'' ORDER BY x.broker_order_id,x.fill_key),''))
   FROM sentinel_fills x),
 'book_cursors_md5',(SELECT md5(coalesce(string_agg(md5(jsonb_build_array(
   x.cursor_name,x.session,x.xmin::text,x.ctid::text)::text),'' ORDER BY x.cursor_name),''))
   FROM sentinel_processed_sessions x WHERE x.cursor_name IN
     ('rolling-cold-start:v1','rolling-daily-checkpoint:v1')
     OR x.cursor_name LIKE 'rolling-daily-input:v1:%'
     OR x.cursor_name LIKE 'shadow-observation:v1:%'),
 'issuer_evidence',(SELECT json_build_object('count',count(*),
   'md5',md5(coalesce(string_agg(md5(to_jsonb(x)::text),'' ORDER BY x.cursor_name),'')))
   FROM sentinel_processed_sessions x WHERE __ISSUER_EVIDENCE_FILTER__),
 'push_subscriptions',(SELECT json_build_object(
   'active',count(*) FILTER (WHERE x.retired_at IS NULL),
   'retired',count(*) FILTER (WHERE x.retired_at IS NOT NULL),
   'identity_md5',md5(coalesce(string_agg(md5((
     to_jsonb(x)-'refreshed_at'-'last_successful_push_at'-'last_failed_push_at')::text),''
     ORDER BY x.subscription_id),''))) FROM sentinel_web_push_subscriptions x),
 'push_policy_md5',(SELECT md5(to_jsonb(x)::text) FROM sentinel_notification_policy x WHERE x.id=1),
 'authority_md5',(SELECT md5(state::text) FROM sentinel_processed_sessions
   WHERE cursor_name='dual-plan-sizing-authority:v1:'||s.plan_id),
 'projection_md5',(SELECT md5(state::text) FROM sentinel_processed_sessions
   WHERE cursor_name='plan-target-projection:v2:'||s.plan_id),
 'opening_md5',(SELECT md5(state::text) FROM sentinel_processed_sessions
   WHERE cursor_name='plan-opening-intents:v1:'||s.plan_id))
 FROM sentinel_automation_control c CROSS JOIN candidates s
 JOIN sentinel_execution_plans p ON p.plan_id=s.plan_id
 CROSS JOIN latest_publication pub WHERE c.id=1
'''

def handoff_filters(mode):
    if mode=='PRE_OPEN':
        candidate = "s.state='WAITING_OPEN'"
        ready = ("s.state='WAITING_OPEN' AND s.failure_code IS NULL AND s.failure_detail IS NULL "
            "AND s.completed_at IS NULL AND s.execute_at>clock_timestamp()+interval '15 minutes'")
    elif mode=='POST_TRADE':
        candidate = ("s.state='SUCCEEDED' AND s.effective_session="
            "(clock_timestamp() AT TIME ZONE 'America/New_York')::date")
        ready = ("s.state='SUCCEEDED' AND s.failure_code IS NULL AND s.failure_detail IS NULL "
            "AND s.completed_at IS NOT NULL AND s.execute_at<=s.completed_at "
            "AND s.completed_at<=clock_timestamp() "
            "AND s.execution_close_at>clock_timestamp()+interval '15 minutes'")
    else:
        raise ValueError('unknown handoff mode')
    return candidate,ready


def snapshot_sql(mode='PRE_OPEN'):
    candidate,ready = handoff_filters(mode)
    settled = ''
    if mode=='POST_TRADE':
        settled = """'reconciliation',(SELECT json_build_object('seq',o.seq,
            'fingerprint',md5(to_jsonb(o)::text),'provenance',md5(to_jsonb(r)::text))
            FROM sentinel_observations o JOIN sentinel_observation_provenance r ON r.observation_seq=o.seq
            WHERE o.seq::text=s.last_clean_reconciliation_id AND o.runtime_state='RUNNING'
              AND o.completeness='COMPLETE' AND r.broker=c.broker
              AND r.broker_account_id=c.broker_account_id AND r.canonical_payload_sha256 IS NOT NULL),"""
    return (_SNAPSHOT_SQL.replace('__CANDIDATE_FILTER__',candidate)
        .replace('__READY_FILTER__',ready).replace('__SETTLED_FACT__',settled)
        .replace('__ISSUER_EVIDENCE_FILTER__',_ISSUER_EVIDENCE_FILTER))


SNAPSHOT_SQL = snapshot_sql()


NOTIFICATION_SQL = r'''SELECT json_build_object(
 'alerts',(SELECT coalesce(jsonb_object_agg(a.alert_id,md5(jsonb_build_array(
   a.alert_id,a.idempotency_key,a.schema_version,a.event_type,a.severity,a.payload,
   a.created_at,a.ack_state,a.acknowledged_by,a.acknowledged_at,a.acknowledgement)::text)),
   '{}'::jsonb) FROM sentinel_alert_outbox a),
 'delivered_alerts',(SELECT coalesce(jsonb_object_agg(a.alert_id,
   md5(jsonb_build_array(a.state,a.delivered_at)::text)),'{}'::jsonb)
   FROM sentinel_alert_outbox a WHERE a.state='DELIVERED'),
 'events',(SELECT coalesce(jsonb_object_agg(x.seq::text,md5(to_jsonb(x)::text)),
   '{}'::jsonb) FROM sentinel_alert_delivery_events x),
 'fanouts',(SELECT coalesce(jsonb_object_agg(x.alert_id,md5(to_jsonb(x)::text)),
   '{}'::jsonb) FROM sentinel_web_push_fanouts x),
 'recipients',(SELECT coalesce(jsonb_object_agg(x.alert_id||':'||x.subscription_id,
   md5(jsonb_build_array(x.alert_id,x.subscription_id,x.created_at)::text)),
   '{}'::jsonb) FROM sentinel_web_push_deliveries x),
 'delivered_recipients',(SELECT coalesce(jsonb_object_agg(x.alert_id||':'||x.subscription_id,
   md5((to_jsonb(x)-'updated_at')::text)),'{}'::jsonb)
   FROM sentinel_web_push_deliveries x WHERE x.state='DELIVERED'))
'''

CANONICAL = r'''import hashlib,json,os,sys,time
from decimal import Decimal
import psycopg
from psycopg.conninfo import make_conninfo
from sentinel import dual_plan_authority as authority, rolling_runtime, rolling_checkpoint
from sentinel.authority import canonical_sha256
from sentinel.cli.authority import _current_system_identities
from sentinel.cli.automation import _automation_authority
from sentinel.config import SentinelConfig
from sentinel.automation_runtime import config_from_env
from sentinel.core.production import SessionState
from sentinel.core.decision import shadow_target,publication_fingerprint
from sentinel.execution import journal,protected_limits,target_reprojection
from sentinel.feed import readers,operational_snapshot
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.panel.pwa import SERVICE_WORKER
from sentinel.panel.render import PUSH_SCRIPT
expected=json.loads(sys.argv[1])
def verify_once():
    dsn=make_conninfo(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=5,
        options='-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000')
    with psycopg.connect(dsn) as conn:
        conn.read_only=True
        assert conn.execute('SHOW transaction_read_only').fetchone()[0]=='on'
        bound,rollout,certificate=_automation_authority(conn,SentinelConfig.from_env(),config_from_env())
        assert bound.broker_account_id==expected['account']
        assert bound.to_dict()==expected['binding']
        assert config_from_env().fingerprint==expected['config']
        runtime,strategy=_current_system_identities()
        origin=rolling_checkpoint.read(conn)
        assert origin is not None
        observation_id,starting_cash=origin.observation_id,Decimal(origin.starting_cash)
        # The canonical status reader owns a fresh repeatable-read transaction.
        conn.rollback()
        result=rolling_runtime.status(conn,observation_id=observation_id,starting_cash=starting_cash)
        assert result is not None and result.session==expected['decision']
        assert result.shadow_verdict=='SHADOW_GO' and result.verification=='VERIFIED'
        plan=journal.load_plan(conn,expected['plan'])
        assert plan is not None and plan.plan_id==expected['plan']
        assert str(plan.decision_session)==expected['decision'] and str(plan.effective_session)==expected['effective']
        assert plan.superseded_by is None
        proof=authority.rederive_plan(conn,plan=plan,binding=bound,rollout_state=rollout,
            expected_shadow_result=result)
        assert proof['verdict']=='MATCH'
        saved=authority.load_authority(conn,plan_id=plan.plan_id)
        assert saved['schema']=='sentinel.dual-plan-sizing-authority/2'
        settled_native_positions=None
        if expected.get('handoff_mode')=='POST_TRADE':
            settled=journal.load_observation_payload(conn,expected['reconciliation_id'])
            assert settled['completeness']=='COMPLETE'
            assert settled['broker']==bound.broker and settled['account_id']==bound.broker_account_id
            settled_native_positions={}
            for position in settled['positions']:
                asset=position['broker_id']
                amount=Decimal(position['quantity'])
                assert asset and asset not in settled_native_positions and amount.is_finite() and amount>0
                settled_native_positions[asset]=str(amount)
        policy=protected_limits.ProtectedLimitPolicy.from_env()
        assert policy is not None
        assert policy.cap_bps==100 and policy.debug_window is None
        projection=target_reprojection.load_projection(conn,plan_id=plan.plan_id)
        # The existing execution contract creates this record at execution before
        # the first order. A future WAITING_OPEN plan legitimately has no projection;
        # preserve that absence rather than manufacturing a future opening state.
        if projection is not None:
            target_reprojection.assert_projection(conn,plan=plan,projection=projection,
                through_session=projection.through_session)
            state=SessionState.from_dict(saved['shadow_state'])
            target=shadow_target(state)
            projected=target_reprojection.project_target(plan,through_session=projection.through_session,
                action_multipliers=projection.action_multipliers,action_evidence=projection.action_evidence,
                canonical_target_shares=target.shares,pending_open_shares=target.pending_open_shares,
                held_shares=target.held_shares,pending_close_shares=target.pending_close_shares)
            retained_policy,refs=protected_limits.validate_projection(projection)
            assert retained_policy==policy
            replay=protected_limits.resolve_protected(state,plan,projected,refs,policy,
                retained_targets={k:Decimal(v) for k,v in proof['retained_targets'].items()})
            assert replay==projection
        with readers.pinned(conn,commit=False) as pub:
            assert str(readers.frontier(conn,pub))==expected['decision']
            source_binding=operational_snapshot.require_alpaca_openfigi(conn,pub)
            published=publication_fingerprint(pub)
        assert published==plan.publication_fingerprint and plan.data_version==expected['version']
        output=dict(plan=plan.plan_id,plan_fingerprint=plan.fingerprint(),
            targets={k:str(v) for k,v in sorted(plan.target_basket.items())},
            authority=saved['authority_sha256'],sizing_sha256=hashlib.sha256(json.dumps(
                saved,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest(),
            held_targets=saved['held_share_targets'],proof=proof,
            opening_intents=[item.to_dict() for item in plan.opening_intents],
            policy=policy.to_dict(),projection=projection.fingerprint() if projection is not None else None,
            publication=published,source_binding=source_binding,
            strategy=canonical_sha256(strategy),wealth=runtime['environment']['wealth_core_source']['hash'],
            book=result.to_dict(),
            book_state_sha256=result.state.state_hash,
            push_controller_sha256=hashlib.sha256(PUSH_SCRIPT.encode()).hexdigest(),
            service_worker_sha256=hashlib.sha256(SERVICE_WORKER.encode()).hexdigest(),
            transaction_read_only=conn.read_only)
        if settled_native_positions is not None:
            output['settled_native_positions']=settled_native_positions
        conn.rollback()
    return output

started=time.monotonic()
outer_deadline=started+300
retry_deadline=None
while True:
    try:
        output=verify_once()
        assert time.monotonic()<=outer_deadline,'canonical proof exceeded its original deadline'
        break
    except CorpusLockUnavailable:
        now=time.monotonic()
        if retry_deadline is None:
            retry_deadline=min(outer_deadline,now+20)
        remaining=min(outer_deadline,retry_deadline)-now
        if remaining<=0:
            raise
        time.sleep(min(.5,remaining))
print(json.dumps(output,sort_keys=True))
'''

IDLE = r'''import json,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from sentinel import shadow_service_status as status
state=Path(os.environ['SENTINEL_STATE_DIR'])
assert not (state/status.CRITICAL_NAME).exists(),'shadow has a critical incident'
assert status.pending(state/status.PENDING_NAME) is None,'shadow has a pending worker'
current=status._load(state/status.NAME)
assert current.binding_sha256==status.binding(os.environ['SENTINEL_DATABASE_URL'])
assert current.state=='RUNNING' and current.reason=='IDLE'
now=datetime.now(timezone.utc)
assert now-timedelta(seconds=60)<=current.observed_at<=now+timedelta(seconds=5)
busy=[]
for entry in Path('/proc').iterdir():
 if not entry.name.isdigit(): continue
 try: args=(entry/'cmdline').read_bytes().split(b'\0')
 except FileNotFoundError: continue
 if b'sentinel.shadow_worker' in args: busy.append(entry.name)
assert not busy,'a supervised shadow worker is active'
assert status.pending(state/status.PENDING_NAME) is None,'worker started during idle observation'
print(json.dumps(dict(observed_at=current.observed_at.isoformat(),incarnation=current.incarnation,
    reason='IDLE',process_check='NO_SHADOW_WORKER')))
'''

NATIVE_POSITIONS = r'''import json,os,urllib.request
from decimal import Decimal
base=os.environ['ALPACA_BASE_URL']
expected=os.environ['SENTINEL_LOCAL_PAPER_ACCOUNT_ID']
assert base=='https://paper-api.alpaca.markets' and expected
headers={'APCA-API-KEY-ID':os.environ['ALPACA_API_KEY'],'APCA-API-SECRET-KEY':os.environ['ALPACA_SECRET_KEY']}
def get(path):
    request=urllib.request.Request(base+path,headers=headers,method='GET')
    with urllib.request.urlopen(request,timeout=15) as response:
        return json.load(response)
account=get('/v2/account')
assert account['account_number']==expected and account['status']=='ACTIVE'
assert get('/v2/orders?status=open&limit=500')==[]
positions=get('/v2/positions')
assert isinstance(positions,list)
assert all(isinstance(row['asset_id'],str) and row['asset_id'] for row in positions)
assert len({row['asset_id'] for row in positions})==len(positions)
assert all(Decimal(row['qty']).is_finite() and Decimal(row['qty'])>0 for row in positions)
print(json.dumps({row['asset_id']:row['qty'] for row in positions},sort_keys=True))
'''

PANEL = r'''import json,sys,urllib.request
from datetime import datetime,timedelta,timezone
expected=json.loads(sys.argv[1])
with urllib.request.urlopen('http://127.0.0.1:8000/panel.json',timeout=25) as response:
 page=json.load(response)
observed=datetime.fromisoformat(page['as_of'])
now=datetime.now(timezone.utc)
assert observed.utcoffset() is not None and now-timedelta(seconds=120)<=observed<=now+timedelta(seconds=5)
rows={row['key']:row for row in page['rows']}
post_trade=expected.get('handoff_mode')=='POST_TRADE'
plan=(rows.get('trading_run',{}).get('trading_run') or {}).get('intent') if post_trade else rows.get('paper_plan',{}).get('paper_plan')
assert isinstance(plan,dict) and plan.get('plan_id')==expected['plan']
assert str(plan.get('decision_session'))==expected['decision']
assert str(plan.get('effective_session'))==expected['effective']
assert rows['automation_cycle']['value']==('SUCCEEDED' if post_trade else 'WAITING_OPEN')
assert page['color'] in (('green','amber') if post_trade else ('green',)) and not page['source_errors']
assert not any(row.get('color')=='red' for row in page['rows'])
assert rows['alert_dispatcher']['status']=='ok'
assert rows['automation_alerts']['status']=='ok'
assert rows['feed']['status']=='ok' and rows['feed']['value']==expected['decision']+' · 0 sessions behind'
output=dict(as_of=page['as_of'],color=page['color'],source_errors=page['source_errors'],
 plan=dict(plan_id=plan['plan_id'],decision=plan['decision_session'],effective=plan['effective_session']),
 cycle=rows['automation_cycle']['value'],
 feed={key:rows['feed'][key] for key in ('status','value','detail')},
 sender={key:rows['alert_dispatcher'][key] for key in ('status','value','detail')},
 alerts={key:rows['automation_alerts'][key] for key in ('status','value','detail')},
 attention=[dict(key=row['key'],status=row['status'],value=row['value'])
  for row in page['rows'] if row.get('color')=='red'])
print(json.dumps(output,sort_keys=True))
'''
