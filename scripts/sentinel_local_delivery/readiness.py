"""One persisted readiness budget; only published facts can satisfy it."""
from datetime import datetime, timedelta

from .model import require, utcnow

SECONDS = 230


def original_cutoff(receipt, *, now=None):
    now = utcnow() if now is None else now
    events = [event for event in receipt['history'] if event['stage'] == 'START_REQUESTED']
    require(len(events) == 1, 'READINESS_START_INTENT_REQUIRED')
    started = datetime.fromisoformat(events[0]['at'])
    proved = datetime.fromisoformat(receipt['artifacts']['successor_verified_at'])
    require(started.utcoffset() is not None and proved.utcoffset() is not None
        and started <= now+timedelta(seconds=5) and proved <= now+timedelta(seconds=5),
        'READINESS_CLOCK_INVALID')
    return min(started+timedelta(seconds=SECONDS), proved+timedelta(seconds=900))


def cutoff(receipt, *, now=None):
    now = utcnow() if now is None else now
    end = original_cutoff(receipt, now=now)
    require(now < end, 'APPLICATION_READINESS_DEADLINE')
    return end


# Self-contained because the selected runtime image does not contain host tools.
# The exact existing validator is supplied separately and consumes the very same
# HTTP response; successful observations are never fetched twice.
PANEL_WAIT = r'''import hashlib,io,json,sys,time,urllib.error,urllib.request
from datetime import datetime,timedelta,timezone
expected=json.loads(sys.argv[1])
validator=sys.argv[2]
cutoff=datetime.fromisoformat(sys.argv[3])
assert cutoff.utcoffset() is not None
remaining=(cutoff-datetime.now(timezone.utc)).total_seconds()
assert remaining>0
remaining=min(230,remaining)
deadline=time.monotonic()+remaining
started=time.monotonic()
startup={'automation_leader','alert_dispatcher','shadow_worker'}
previous=None
attempts=0
transitions=[]
# Load validator dependencies before acquiring a short-lived published fact.
from sentinel.panel.review_model import OperatorReview
from sentinel.panel.presentation import _HISTORY_CURRENT_FACTS
from sentinel.panel.model import OperationalFact,TradingRun
from zoneinfo import ZoneInfo
compiled_validator=compile(validator,'strict installation dashboard validator','exec')
def budget():
 left=min(deadline-time.monotonic(),(cutoff-datetime.now(timezone.utc)).total_seconds())
 assert left>0,'APPLICATION_READINESS_DEADLINE'
 return left
def clean_retired_projection_wait(rows,checking,instant,page):
 if not (expected.get('handoff_mode')=='POST_TRADE' and expected.get('clean_retired') is True
         and ('paper_reconciliation' in checking or 'backup_restore' in checking)):return set()
 checking_paper='paper_reconciliation' in checking
 paper=rows['paper_reconciliation']
 fact=OperationalFact.model_validate(paper['operational_fact']);fact.require_key('paper_reconciliation')
 assert fact.kind=='PAPER_VERIFICATION' and fact.state==('CHECKING' if checking_paper else 'AWAITING_NEXT_DECISION'),'READINESS_CLEAN_RETIRED_PAPER_CHECK'
 assert paper['current'] is True and paper['required_current'] is True,'READINESS_CLEAN_RETIRED_PAPER_CURRENT'
 assert paper['stale'] is False and paper['future'] is False,'READINESS_CLEAN_RETIRED_PAPER_CLOCK'
 bound=datetime.fromisoformat(paper['valid_until'])
 assert bound.utcoffset()==timedelta(0) and instant<bound,'READINESS_CLEAN_RETIRED_PAPER_DEADLINE'
 current=rows['trading_run'];run=TradingRun.model_validate(current['trading_run'])
 completed=datetime.fromisoformat(expected['completed_at'])
 assert completed.utcoffset()==timedelta(0) and completed<=instant,'READINESS_CLEAN_RETIRED_COMPLETION_CLOCK'
 assert run.state=='SUPERSEDED' and run.orders==[] and run.updated_at==completed,'READINESS_CLEAN_RETIRED_RUN_STATE'
 assert run.intent.execute_at<=completed,'READINESS_CLEAN_RETIRED_EXECUTION_CLOCK'
 assert (run.intent.plan_id,run.intent.cycle_id)==(expected['plan'],expected['cycle_id']),'READINESS_CLEAN_RETIRED_RUN_SUBJECT'
 assert str(run.intent.decision_session)==expected['decision'] and str(run.intent.effective_session)==expected['effective'],'READINESS_CLEAN_RETIRED_RUN_SESSION'
 assert current['current'] is True and current['stale'] is False and current['future'] is False,'READINESS_CLEAN_RETIRED_RUN_CURRENT'
 assert current['status'] in {'fail','warn'} and datetime.fromisoformat(current['as_of'])==completed,'READINESS_CLEAN_RETIRED_RUN_CLOCK'
 history=None
 if current.get('operational_fact') is not None:
  history=OperationalFact.model_validate(current['operational_fact']);history.require_key('trading_run')
  original_end=(datetime.fromisoformat(expected['effective'])+timedelta(days=1)).replace(
   tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)-timedelta(microseconds=1)
  assert history.kind=='EXECUTION_HISTORY' and history.state=='SUPERSEDED','READINESS_CLEAN_RETIRED_HISTORY_STATE'
  assert (history.opening.cycle_id,history.opening.plan_id)==(expected['cycle_id'],expected['plan']),'READINESS_CLEAN_RETIRED_HISTORY_SUBJECT'
  assert history.opening.observation_id==int(expected['reconciliation_id']),'READINESS_CLEAN_RETIRED_HISTORY_OBSERVATION'
  assert history.opening.started_at==completed and history.opening.terminal_reason=='POST_PLAN_CASH_ACTIVITY_RECONCILED','READINESS_CLEAN_RETIRED_HISTORY_OUTCOME'
  assert run.intent.execute_at<=history.opening.reconciled_at<=completed,'READINESS_CLEAN_RETIRED_HISTORY_ORDER'
  assert history.opening.deadline==original_end,'READINESS_CLEAN_RETIRED_HISTORY_DEADLINE'
  assert instant<original_end,'READINESS_CLEAN_RETIRED_HISTORY_EXPIRED'
 if current['status']=='warn' and current.get('recovery') is None:
  assert history is not None and datetime.fromisoformat(current['valid_until'])==history.opening.deadline,'READINESS_CLEAN_RETIRED_HISTORY_REQUIRED'
 if not checking_paper:
  progress=paper['recovery']
  assert paper['status']=='warn' and paper['original_status']=='warn' and paper['color']=='amber' and paper['value']=='PLAN SKIPPED · CASH ACTIVITY RECONCILED','READINESS_CLEAN_RETIRED_PAPER_POSITIVE'
  assert (fact.opening.plan_id,fact.opening.cycle_id,fact.opening.observation_id,fact.opening.started_at)==(expected['plan'],expected['cycle_id'],int(expected['reconciliation_id']),completed),'READINESS_CLEAN_RETIRED_PAPER_SUBJECT'
  assert fact.opening.deadline==bound and progress['phase']=='AWAITING_NEXT_DECISION' and progress['automatic'] is True and progress['operator_required'] is False and progress['active'] is True,'READINESS_CLEAN_RETIRED_PAPER_RECOVERY'
 keys={'trading_run','automation_cycle','automation_step_transport','automation_step_reconcile','automation_step_complete'}
 for key in keys-{'trading_run'}:
  row=rows[key];workflow=OperationalFact.model_validate(row['operational_fact']);workflow.require_key(key)
  assert workflow.kind=='AUTOMATION_CYCLE' and workflow.state=='SUPERSEDED',f'READINESS_CLEAN_RETIRED_STEP_STATE:{key}'
  assert row['current'] is True and row['stale'] is False and row['future'] is False,f'READINESS_CLEAN_RETIRED_STEP_CURRENT:{key}'
  assert row['status'] in {'fail','warn'},f'READINESS_CLEAN_RETIRED_STEP_STATUS:{key}'
  recorded=datetime.fromisoformat(row['as_of'])
  if recorded!=completed:
   assert key=='automation_step_transport' and history is not None,f'READINESS_CLEAN_RETIRED_STEP_CLOCK:{key}'
   assert recorded.utcoffset()==timedelta(0) and run.intent.execute_at<=recorded<=history.opening.reconciled_at<=completed,'READINESS_CLEAN_RETIRED_TRANSPORT_ORDER:automation_step_transport'
   if row['status']=='fail':
    assert row['value']=='INTERRUPTED · OUTCOME UNVERIFIED' and row.get('recovery') is None,'READINESS_CLEAN_RETIRED_TRANSPORT_INTERRUPTION:automation_step_transport'
   else:
    progress=row['recovery']
    assert row['value']=='INTERRUPTED · RECONCILED · PLAN SKIPPED','READINESS_CLEAN_RETIRED_TRANSPORT_RESOLUTION:automation_step_transport'
    if progress is None:
     assert (checking_paper or 'backup_restore' in checking) and paper['recovery']['active'] is True,'READINESS_CLEAN_RETIRED_TRANSPORT_CHECK_REQUIRED:automation_step_transport'
     assert datetime.fromisoformat(row['valid_until'])==history.opening.deadline,'READINESS_CLEAN_RETIRED_TRANSPORT_HISTORY_BOUND:automation_step_transport'
    else:
     assert progress['phase']=='AWAITING_NEXT_DECISION' and progress['automatic'] is True and progress['operator_required'] is False,'READINESS_CLEAN_RETIRED_TRANSPORT_RECOVERY:automation_step_transport'
     assert instant<datetime.fromisoformat(progress['deadline'])==datetime.fromisoformat(row['valid_until']),'READINESS_CLEAN_RETIRED_TRANSPORT_DEADLINE:automation_step_transport'
 if not checking_paper:keys.add('paper_reconciliation')
 broker=rows['broker']
 if broker['status']!='ok':
  assert checking_paper and history is not None,'READINESS_CLEAN_RETIRED_BROKER_CHECK_REQUIRED'
  assert broker['status']=='fail' and broker['original_status']=='fail' and broker['color']=='red','READINESS_CLEAN_RETIRED_BROKER_EXPIRY_STATUS'
  assert broker['current'] is True and broker['required_current'] is True and broker['stale'] is True and broker['future'] is False and broker.get('recovery') is None,'READINESS_CLEAN_RETIRED_BROKER_EXPIRY_STATE'
  observed=datetime.fromisoformat(broker['as_of']);expired=datetime.fromisoformat(broker['valid_until'])
  assert observed.utcoffset()==expired.utcoffset()==timedelta(0) and observed<expired<=instant and expired==observed+timedelta(minutes=10),'READINESS_CLEAN_RETIRED_BROKER_EXPIRY_CLOCK'
  assert history.opening.reconciled_at<=observed<=completed,'READINESS_CLEAN_RETIRED_BROKER_HISTORY_CLOCK'
  candidate=OperationalFact.model_validate(broker['operational_fact']);candidate.require_key('broker')
  assert candidate.kind=='EXECUTION_PROGRESS' and candidate.state=='AWAITING_NEXT_DECISION','READINESS_CLEAN_RETIRED_BROKER_CANDIDATE'
  assert (candidate.opening.cycle_id,candidate.opening.plan_id,candidate.opening.observation_id,candidate.opening.started_at)==(expected['cycle_id'],expected['plan'],int(expected['reconciliation_id']),completed),'READINESS_CLEAN_RETIRED_BROKER_SUBJECT'
  from sentinel.automation import schedule
  from sentinel.automation.model import AutomationConfig
  from sentinel.feed import calendar
  obligation=schedule.for_decision_session(calendar.next_session(str(run.intent.decision_session)),AutomationConfig()).prepare_at.astimezone(timezone.utc)
  assert instant<candidate.opening.deadline==obligation,'READINESS_CLEAN_RETIRED_BROKER_OBLIGATION'
  frame=page['observation'];generated=datetime.fromisoformat(page['as_of']);until=datetime.fromisoformat(frame['valid_until'])
  assert frame['current'] is True and frame.get('strict_current',True) is True and generated.utcoffset()==until.utcoffset()==timedelta(0) and generated<=instant<until<=generated+timedelta(seconds=30),'READINESS_CLEAN_RETIRED_BROKER_FRAME'
  keys.add('broker')
 return keys

def maintenance_wait(row,instant):
 if row.get('value')!='BACKUP CHECK IN PROGRESS':return False
 progress=row.get('recovery') or {}
 assert row['status']=='warn' and row['original_status']=='warn' and row['color']=='amber','READINESS_BACKUP_MAINTENANCE_STATUS'
 assert row['current'] is True and row['required_current'] is True and row['stale'] is False and row['future'] is False,'READINESS_BACKUP_MAINTENANCE_CURRENT'
 assert progress.get('phase')=='BACKUP_MAINTENANCE' and progress.get('automatic') is True and progress.get('operator_required') is False and progress.get('active') is True,'READINESS_BACKUP_MAINTENANCE_RECOVERY'
 observed=datetime.fromisoformat(row['as_of']);until=datetime.fromisoformat(row['valid_until'])
 assert observed.utcoffset()==until.utcoffset()==timedelta(0) and observed<=instant<until<=observed+timedelta(hours=1) and until==datetime.fromisoformat(progress['deadline']),'READINESS_BACKUP_MAINTENANCE_CLOCK'
 return True

def status_code(value):
 return value if isinstance(value,str) and value in {'ok','warn','pending','fail','unknown'} else 'INVALID'

def refusal_summary(page,stage):
 def stamp(value):
  try:
   at=datetime.fromisoformat(value)
   return at.isoformat() if at.utcoffset()==timedelta(0) else 'INVALID'
  except (ValueError,TypeError):return None if value is None else 'INVALID'
 closed={'authority','broker','runtime_identity','feed','ownership','book','exposure','backup_restore','paper_reconciliation','trading_run','automation_cycle','automation_step_transport','automation_step_reconcile','automation_step_complete'}
 result=[]
 for row in page['rows'] if isinstance(page,dict) and isinstance(page.get('rows'),list) else []:
  if not isinstance(row,dict) or not isinstance(row.get('key'),str) or row['key'] not in closed:continue
  progress=row.get('recovery') or {};phase=progress.get('phase') if isinstance(progress,dict) else None
  item=dict(key=row['key'],status=status_code(row.get('status')),original_status=status_code(row.get('original_status')),
   as_of=stamp(row.get('as_of')),valid_until=stamp(row.get('valid_until')),
   current=row.get('current') is True,stale=row.get('stale') is True,future=row.get('future') is True,
   recovery_phase=phase if isinstance(phase,str) and phase in {'FINANCIAL_VERIFICATION','BACKUP_MAINTENANCE','AWAITING_NEXT_DECISION'} else 'OTHER' if phase else None,
   recovery_deadline=stamp(progress.get('deadline')) if isinstance(progress,dict) else None,
   value_sha256=hashlib.sha256(row.get('value','')[:4096].encode('utf-8','backslashreplace')).hexdigest() if isinstance(row.get('value'),str) else None)
  result.append(item)
  if len(result)==len(closed):break
 print(json.dumps(dict(schema='sentinel.install-readiness-refusal/1',stage=stage,rows=result),sort_keys=True),file=sys.stderr,flush=True)

def retain_refusal(page,stage):
 try:refusal_summary(page,stage)
 except Exception:pass  # Diagnostics cannot replace the original refusal.
def partial_wait(page,rows,checking,workflows,retiring):
 # Validate the public protocol. Human display admission is not installation
 # authority and private runtime model predicates are not a host-tool API.
 observation=page['observation']
 changed=observation['changed_scopes'];revalidated=observation['revalidated_keys']
 assert type(observation['current']) is bool
 assert observation.get('strict_current',observation['current']) is False
 assert isinstance(changed,list) and len(changed)==len(set(changed))
 assert changed or observation.get('retained') is True,'READINESS_PARTIAL_SCOPE_INVALID'
 assert set(changed)<={'SHADOW','PAPER'},'READINESS_PARTIAL_SCOPE_INVALID'
 assert isinstance(revalidated,list) and len(revalidated)==len(set(revalidated))
 assert set(revalidated)<={'shadow_verification','shadow_nav','shadow_return','exposure','book','terminals','paper_reconciliation'}
 withdrawn=set();negatives=set()
 for key,row in rows.items():
  current=row.get('current')
  assert type(current) is bool
  original=row.get('original_status')
  assert original in {'ok','warn','pending','fail','unknown'}
  assert row['status']==(original if current else 'pending')
  if original in {'fail','unknown'} or row.get('color')=='red':negatives.add(key)
  if not current:
   withdrawn.add(key)
   assert row.get('color')=='neutral'
   assert all(row.get(field) is None for field in ['shadow_book','paper_plan','paper_account','trading_run','preparation','operational_fact'])
   assert row.get('order_outcomes')==[]
  else:
   assert row.get('color')=={'ok':'green','warn':'amber','pending':'amber','fail':'red','unknown':'red'}[original]
 unavailable=set()
 if (expected.get('handoff_mode')=='POST_TRADE' and expected.get('clean_retired') is True
     and 'paper_reconciliation' in checking):
  paper=rows['paper_reconciliation'];fact=OperationalFact.model_validate(paper['operational_fact']);fact.require_key('paper_reconciliation')
  assert fact.kind=='PAPER_VERIFICATION' and fact.state=='CHECKING','READINESS_WITHDRAWN_PAPER_CHECK'
  assert paper['current'] is True and paper['required_current'] is True and paper['stale'] is False and paper['future'] is False,'READINESS_WITHDRAWN_PAPER_CURRENT'
  bound=datetime.fromisoformat(paper['valid_until']);instant=datetime.now(timezone.utc);progress=paper['recovery']
  assert bound.utcoffset()==timedelta(0) and instant<bound<=instant+timedelta(seconds=600),'READINESS_WITHDRAWN_PAPER_DEADLINE'
  assert progress['active'] is True and progress['phase']=='FINANCIAL_VERIFICATION' and progress['automatic'] is True and progress['operator_required'] is False and datetime.fromisoformat(progress['deadline'])==bound,'READINESS_WITHDRAWN_PAPER_RECOVERY'
  unavailable={key for key in ('broker','trading_run','automation_cycle','automation_step_transport','automation_step_reconcile','automation_step_complete')
   if rows[key]['current'] is False}
 assert negatives<=startup|retiring|unavailable,'NONSTARTUP_READINESS_FAILURE'
 assert not any(row.get('original_status')=='fail' and key in startup
  for key,row in rows.items()),'NONSTARTUP_READINESS_FAILURE'
 if expected.get('handoff_mode')=='POST_TRADE':
  run=rows['trading_run']
  if 'trading_run' not in unavailable:
   assert (run.get('original_status') in {'fail','warn'} if 'trading_run' in retiring
     else run.get('original_status')==('warn' if expected.get('clean_retired') else 'ok'))
  assert run.get('stale') is False and run.get('future') is False
  if run.get('current'):
   assert run['trading_run']['state']==('SUPERSEDED' if expected.get('clean_retired') else 'SUCCEEDED')
   assert run['trading_run']['intent']['plan_id']==expected['plan']
 else:
  plan=rows.get('paper_plan',{})
  assert plan.get('original_status')=='ok'
  assert plan.get('stale') is False and plan.get('future') is False
  if plan.get('current'):
   assert plan['paper_plan']['plan_id']==expected['plan']
  else: assert plan.get('paper_plan') is None
 review=page['operator_review']
 if observation['current'] is False: assert review is None
 else:
  assert review is None or isinstance(review,dict)
  if review is not None: assert set(review['active'])|set(review['warnings'])<=startup|checking|workflows|retiring|unavailable
 health=page['dashboard_health'];assert isinstance(health,dict)
 conditions=set(health['active_conditions'])|set(health['review_conditions'])
 assert conditions<=startup|withdrawn|checking|workflows|retiring,'NONSTARTUP_READINESS_FAILURE'
 observed=datetime.fromisoformat(page['as_of'])
 expiry=datetime.fromisoformat(observation['valid_until'])
 assert observed.utcoffset()==expiry.utcoffset()==timedelta(0)
 assert observed<=datetime.now(timezone.utc) and observed<expiry<=observed+timedelta(seconds=30)
 return ['dashboard_subject_revalidation']

def pending(page,header):
 # A pending classification grants no readiness. Financial and other current
 # negatives are never turned into startup waits.
 assert isinstance(page,dict) and isinstance(page['rows'],list)
 rows={row['key']:row for row in page['rows']}
 assert len(rows)==len(page['rows']) and not page['source_errors']
 assert header in {'CURRENT','PARTIAL'},'READINESS_HEADER_INVALID'
 if expected.get('handoff_mode') in {'BLOCKED_UNSENT','POST_TRADE_SUCCESSOR'}:
  return None
 observation=page['observation']
 assert type(observation['current']) is bool
 strict=observation.get('strict_current',observation['current'])
 assert type(strict) is bool
 assert (header=='CURRENT') is observation['current'],'READINESS_HEADER_INVALID'
 checking=set()
 instant=datetime.now(timezone.utc)
 for key in ('shadow_verification','paper_reconciliation','exposure','book','terminals'):
  row=rows.get(key,{})
  recovery=row.get('recovery') or {}
  if (row.get('status')=='warn' and row.get('value')=='CHECK IN PROGRESS'
   and recovery.get('phase')=='FINANCIAL_VERIFICATION' and recovery.get('automatic') is True
   and recovery.get('operator_required') is False):
   bound=datetime.fromisoformat(recovery['deadline'])
   assert bound.utcoffset() is not None and instant<bound<=instant+timedelta(seconds=600)
   assert datetime.fromisoformat(row['valid_until'])==bound
   checking.add(key)
 if maintenance_wait(rows.get('backup_restore',{}),instant):checking.add('backup_restore')
 workflows=set()
 if checking:
  for key,phase in [('automation_cycle','AUTOMATION_WAITING_OPEN'),('automation_step_open','AUTOMATION_OPEN')]:
   row=rows.get(key,{})
   recovery=row.get('recovery') or {}
   if (row.get('status')=='warn' and row.get('value')=='WAITING_OPEN'
    and recovery.get('phase')==phase and recovery.get('automatic') is True
    and recovery.get('operator_required') is False):
    bound=datetime.fromisoformat(recovery['deadline'])
    assert bound.utcoffset() is not None and instant<bound
    workflows.add(key)
 retiring=set()
 if header=='PARTIAL':
  return partial_wait(page,rows,checking,workflows,retiring)
 if strict is False:
  return partial_wait(page,rows,checking,workflows,retiring)
 retiring=clean_retired_projection_wait(rows,checking,instant,page)
 post_trade=expected.get('handoff_mode')=='POST_TRADE'
 plan=((rows.get('trading_run',{}).get('trading_run') or {}).get('intent') if post_trade
       else rows.get('paper_plan',{}).get('paper_plan'))
 assert isinstance(plan,dict) and plan.get('plan_id')==expected['plan']
 assert str(plan.get('decision_session'))==expected['decision']
 assert str(plan.get('effective_session'))==expected['effective']
 if post_trade:
  assert rows['trading_run']['trading_run']['state']==('SUPERSEDED' if expected.get('clean_retired') else 'SUCCEEDED')
  if not expected.get('clean_retired'):
   assert rows['automation_cycle']['value']=='SUCCEEDED' and rows['automation_cycle']['status']=='ok'
 for key in ('authority','broker','runtime_identity','feed','ownership','book','exposure',
             'trading_run' if post_trade else 'paper_plan','backup_restore'):
  if key in rows and key not in checking:
   if key=='broker' and key in retiring:continue
   if key=='trading_run' and expected.get('clean_retired'):
    assert rows[key]['status'] in ({'fail','warn'} if key in retiring else {'warn'}),'NONSTARTUP_READINESS_FAILURE'
   else:assert rows[key]['status']=='ok',f'NONSTARTUP_READINESS_FAILURE:{key}:{status_code(rows[key].get("status"))}'
 review=page['operator_review'];health=page['dashboard_health']
 assert isinstance(review,dict) and isinstance(health,dict)
 conditions=set(review['active'])|set(review['warnings'])|set(health['active_conditions'])|set(health['review_conditions'])
 negatives={row['key'] for row in page['rows'] if row.get('color')=='red'
  or row.get('status') in {'fail','unknown'}}
 assert conditions<=startup|checking|workflows|retiring and negatives<=startup|retiring,'NONSTARTUP_READINESS_FAILURE'
 assert not any(row.get('status')=='fail' and row['key'] in startup
  for row in page['rows']),'NONSTARTUP_READINESS_FAILURE'
 if conditions or negatives or checking:
  return sorted(conditions|negatives|checking)
 # A partial current-subject read may settle; its financial rows were still
 # checked for negatives above. The strict current validator must pass later.
 if header=='PARTIAL' or strict is False:
  return ['dashboard_publication_pending']
 return None
while True:
 attempts+=1
 reason=None
 try:
  with urllib.request.urlopen('http://127.0.0.1:8000/panel.json',timeout=min(25,budget())) as response:
   raw=response.read(2*1024*1024+1)
   assert len(raw)<=2*1024*1024,'READINESS_PAGE_TOO_LARGE'
   page=json.loads(raw)
   headers=response.headers
   header=response.headers.get('X-Sentinel-Panel-Status')
  budget()
  try:reason=pending(page,header)
  except (AssertionError,ValueError,KeyError,TypeError):
   retain_refusal(page,'PENDING')
   raise
 except urllib.error.HTTPError as error:
  if error.code!=503:raise
  error.close()
  reason=['dashboard_http_503']
 except urllib.error.URLError as error:
  if not isinstance(error.reason,ConnectionRefusedError):raise
  reason=['dashboard_starting']
 if reason is None:
  observation_until=datetime.fromisoformat(page['observation']['valid_until'])
  health_until=datetime.fromisoformat(page['dashboard_health']['valid_until'])
  observed=datetime.fromisoformat(page['as_of'])
  assert all(at.utcoffset()==timedelta(0) for at in (observation_until,health_until,observed))
  assert health_until<=observation_until<=observed+timedelta(seconds=30)
  if datetime.now(timezone.utc)>=health_until:
   reason=['dashboard_publication_expired']
 if reason is None:
  response=io.StringIO(json.dumps(page));response.headers=headers
  printed=[]
  try:
   exec(compiled_validator,{'_page':page,'_response':response,'print':printed.append})
  except (AssertionError,ValueError,KeyError,TypeError):
   retain_refusal(page,'FINAL')
   raise
  budget()
  assert len(printed)==1
  output=json.loads(printed[0])
  if expected.get('handoff_mode') in {None,'PRE_OPEN','POST_TRADE'}:
   output['installation_panel_valid_until']=min(datetime.fromisoformat(page['observation']['valid_until']),
    datetime.fromisoformat(page['dashboard_health']['valid_until'])).isoformat()
  output['readiness_observations']=attempts
  output['readiness_transitions']=transitions
  print(json.dumps(output,sort_keys=True))
  break
 if reason!=previous:
  transitions.append(dict(conditions=reason,elapsed_ms=max(0,int((time.monotonic()-started)*1000))))
  print(json.dumps(dict(readiness='PENDING',conditions=reason)),file=sys.stderr,flush=True)
  previous=reason
 time.sleep(min(5,budget()))
'''
