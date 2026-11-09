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
PANEL_WAIT = r'''import io,json,sys,time,urllib.error,urllib.request
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
compiled_validator=compile(validator,'strict installation dashboard validator','exec')
def budget():
 left=min(deadline-time.monotonic(),(cutoff-datetime.now(timezone.utc)).total_seconds())
 assert left>0,'APPLICATION_READINESS_DEADLINE'
 return left
def partial_wait(page,rows,checking,workflows):
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
 assert negatives<=startup,'NONSTARTUP_READINESS_FAILURE'
 assert not any(row.get('original_status')=='fail' and key in startup
  for key,row in rows.items()),'NONSTARTUP_READINESS_FAILURE'
 if expected.get('handoff_mode')=='POST_TRADE':
  run=rows['trading_run']
  assert run.get('original_status')=='ok' and run.get('stale') is False and run.get('future') is False
  if run.get('current'):
   assert run['trading_run']['state']=='SUCCEEDED'
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
  if review is not None: assert set(review['active'])|set(review['warnings'])<=startup|checking|workflows
 health=page['dashboard_health'];assert isinstance(health,dict)
 conditions=set(health['active_conditions'])|set(health['review_conditions'])
 assert conditions<=startup|withdrawn|checking|workflows,'NONSTARTUP_READINESS_FAILURE'
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
 if header=='PARTIAL':
  return partial_wait(page,rows,checking,workflows)
 if strict is False:
  return partial_wait(page,rows,checking,workflows)
 post_trade=expected.get('handoff_mode')=='POST_TRADE'
 plan=((rows.get('trading_run',{}).get('trading_run') or {}).get('intent') if post_trade
       else rows.get('paper_plan',{}).get('paper_plan'))
 assert isinstance(plan,dict) and plan.get('plan_id')==expected['plan']
 assert str(plan.get('decision_session'))==expected['decision']
 assert str(plan.get('effective_session'))==expected['effective']
 if post_trade:
  assert rows['trading_run']['trading_run']['state']=='SUCCEEDED'
  assert rows['automation_cycle']['value']=='SUCCEEDED' and rows['automation_cycle']['status']=='ok'
 for key in ('authority','broker','runtime_identity','feed','ownership','book','exposure',
             'trading_run' if post_trade else 'paper_plan','backup_restore'):
  if key in rows and key not in checking:assert rows[key]['status']=='ok','NONSTARTUP_READINESS_FAILURE'
 review=page['operator_review'];health=page['dashboard_health']
 assert isinstance(review,dict) and isinstance(health,dict)
 conditions=set(review['active'])|set(review['warnings'])|set(health['active_conditions'])|set(health['review_conditions'])
 negatives={row['key'] for row in page['rows'] if row.get('color')=='red'
  or row.get('status') in {'fail','unknown'}}
 assert conditions<=startup|checking|workflows and negatives<=startup,'NONSTARTUP_READINESS_FAILURE'
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
  reason=pending(page,header)
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
  exec(compiled_validator,
   {'_page':page,'_response':response,'print':printed.append})
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


def panel_validator(program):
    fetch = ("with urllib.request.urlopen('http://127.0.0.1:8000/panel.json',timeout=25) as response:\n"
             " page=json.load(response)\n")
    require(program.count(fetch) == 1, 'PANEL_VALIDATOR_FETCH_CONTRACT_CHANGED')
    return program.replace(fetch, 'response=_response\npage=_page\n')
