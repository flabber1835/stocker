"""One persisted readiness budget; only published facts can satisfy it."""
from datetime import datetime, timedelta

from .model import require, utcnow

SECONDS = 230


def cutoff(receipt, *, now=None):
    now = utcnow() if now is None else now
    events = [event for event in receipt['history'] if event['stage'] == 'START_REQUESTED']
    require(len(events) == 1, 'READINESS_START_INTENT_REQUIRED')
    started = datetime.fromisoformat(events[0]['at'])
    proved = datetime.fromisoformat(receipt['artifacts']['successor_verified_at'])
    require(started.utcoffset() is not None and proved.utcoffset() is not None
        and started <= now+timedelta(seconds=5) and proved <= now+timedelta(seconds=5),
        'READINESS_CLOCK_INVALID')
    end = min(started+timedelta(seconds=SECONDS), proved+timedelta(seconds=900))
    require(now < end, 'APPLICATION_READINESS_DEADLINE')
    return end


# Self-contained because the selected runtime image does not contain host tools.
# The exact existing validator is supplied separately and consumes the very same
# HTTP response; successful observations are never fetched twice.
PANEL_WAIT = r'''import io,json,sys,time,urllib.error,urllib.request
from datetime import datetime,timezone
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
def budget():
 left=min(deadline-time.monotonic(),(cutoff-datetime.now(timezone.utc)).total_seconds())
 assert left>0,'APPLICATION_READINESS_DEADLINE'
 return left
def pending(page,header):
 # A pending classification grants no readiness. Financial and other current
 # negatives are never turned into startup waits.
 assert isinstance(page,dict) and isinstance(page['rows'],list)
 rows={row['key']:row for row in page['rows']}
 assert len(rows)==len(page['rows']) and not page['source_errors']
 assert header in {'CURRENT','PARTIAL'},'READINESS_HEADER_INVALID'
 if expected.get('handoff_mode') in {'BLOCKED_UNSENT','POST_TRADE','POST_TRADE_SUCCESSOR'}:
  return None
 plan=rows.get('paper_plan',{}).get('paper_plan')
 assert isinstance(plan,dict) and plan.get('plan_id')==expected['plan']
 assert str(plan.get('decision_session'))==expected['decision']
 assert str(plan.get('effective_session'))==expected['effective']
 for key in ('authority','broker','runtime_identity','feed','ownership','book','exposure','paper_plan','backup_restore'):
  if key in rows:assert rows[key]['status']=='ok','NONSTARTUP_READINESS_FAILURE'
 review=page['operator_review'];health=page['dashboard_health']
 assert isinstance(review,dict) and isinstance(health,dict)
 conditions=set(review['active'])|set(review['warnings'])|set(health['active_conditions'])|set(health['review_conditions'])
 negatives={row['key'] for row in page['rows'] if row.get('color')=='red'
  or row.get('status') in {'fail','unknown'}}
 assert conditions<=startup and negatives<=startup,'NONSTARTUP_READINESS_FAILURE'
 if conditions or negatives:
  return sorted(conditions|negatives)
 # A partial current-subject read may settle; its financial rows were still
 # checked for negatives above. The strict current validator must pass later.
 if header=='PARTIAL' or page['observation']['current'] is False:
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
  response=io.StringIO(json.dumps(page));response.headers=headers
  printed=[]
  exec(compile(validator,'strict installation dashboard validator','exec'),
   {'_page':page,'_response':response,'print':printed.append})
  budget()
  assert len(printed)==1
  output=json.loads(printed[0])
  if expected.get('handoff_mode') is None:
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
