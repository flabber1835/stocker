"""Unverified scalar progress only; never export or mutate a financial book."""
from datetime import date,datetime,timezone
import gzip,hashlib,json,os,re,subprocess,threading,time
from pathlib import Path
ACTION=Path('/home/runner/work/_actions/actions/upload-artifact/ea165f8d65b6e75b540449e92b4886f43607fa02/dist/index.js')
MAX_PLAIN=32*1024**2
FIELDS=frozenset(('schema','run_id','head','arm','phase','phase_state','elapsed_seconds','observed_utc','checkpoint_completed','checkpoint_session','constructor_marker_seen','writer_stopped','verified','financial_sessions_admitted','observer_sha256'))

def counters(value):
 if not isinstance(value,dict):return None,None
 n=value.get('completed');day=value.get('source_cursor')
 if type(n)is not int or not 0<=n<=2156 or type(day)is not str:return None,None
 try:valid=date.fromisoformat(day).isoformat()==day and '2017-01-01'<=day<='2026-07-31'
 except ValueError:valid=False
 return (n,day) if valid else (None,None)

def observe(root):
 root=Path(root);p=root/'book/checkpoint.json.gz'
 try:
  if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or not p.is_file() or p.stat().st_size>16*1024**2:return None,None,False
  with gzip.open(p,'rb') as f:raw=f.read(MAX_PLAIN+1)
  if len(raw)>MAX_PLAIN:return None,None,False
  n,day=counters(json.loads(raw));marker=root/'continuation-constructor-canary.json'
  seen=marker.is_file() and not marker.is_symlink() and marker.resolve().is_relative_to(root.resolve())
  return n,day,seen
 except (OSError,ValueError,EOFError):return None,None,False

def validate(value):
 if set(value)!=FIELDS or value['schema']!='research.unverified-session-progress/1' or value['verified'] is not False or value['financial_sessions_admitted']!=0:raise ValueError('PROGRESS_CLOSED_METADATA_ONLY')
 if value['arm'] not in tuple('P'+str(i).zfill(2) for i in range(12)) or value['phase'] not in ('preflight','worker','review'):raise ValueError('PROGRESS_EXACT_PHASE')
 if value['phase_state'] not in ('ACTIVE','STOPPED','UNKNOWN') or not(value['writer_stopped'] is True or value['writer_stopped'] is False or value['writer_stopped'] is None):raise ValueError('PROGRESS_ACTUAL_OR_UNKNOWN_STOP')
 if not(re.fullmatch(r'[1-9][0-9]*',value['run_id']) and re.fullmatch(r'[0-9a-f]{40}',value['head']) and re.fullmatch(r'[0-9a-f]{64}',value['observer_sha256'])):raise ValueError('PROGRESS_EXACT_SOURCE_AND_RUN')
 if type(value['constructor_marker_seen'])is not bool or (value['checkpoint_completed'] is None and value['checkpoint_session'] is not None):raise ValueError('PROGRESS_KNOWN_OR_UNKNOWN_COUNTER')
 if type(value['elapsed_seconds'])is not int or value['elapsed_seconds']<0:raise ValueError('PROGRESS_ELAPSED')
 if value['checkpoint_completed'] is not None and counters(dict(completed=value['checkpoint_completed'],source_cursor=value['checkpoint_session']))!=(value['checkpoint_completed'],value['checkpoint_session']):raise ValueError('PROGRESS_COUNTER_FIELDS')
 return value

def upload(path,name):
 # The parent is the dedicated, authenticated GitHub host. No shell, extra
 # token or broad artifact path is introduced; only this small metadata file.
 if not ACTION.is_file():return
 env=dict(os.environ,INPUT_NAME=name,INPUT_PATH=str(path),INPUT_RETENTION_DAYS='1',INPUT_IF_NO_FILES_FOUND='error',INPUT_COMPRESSION_LEVEL='0')
 subprocess.run(['node',str(ACTION)],env=env,shell=False,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25)

class Observer:
 def __init__(self,root,name):
  match=re.fullmatch(r'capital-system-resume-(p[0-9]{2})-(preflight|worker|review)-([0-9]+)-1',name)
  if match is None:raise ValueError('PROGRESS_KNOWN_CONTAINER_NAME')
  self.root,self.arm,self.phase,self.run=Path(root),match[1].upper(),match[2],match[3]
  if self.run!=os.environ.get('GITHUB_RUN_ID'):raise ValueError('PROGRESS_CURRENT_RUN_ONLY')
  self.head=os.environ['GITHUB_SHA'];self.started=time.monotonic();self.stop=threading.Event();self.sequence=0
  self.directory=Path(os.environ['RUNNER_TEMP'])/('research-progress-'+self.run+'-'+self.phase)
  self.source=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();self.thread=threading.Thread(target=self.loop,daemon=True)
 def publish(self,phase_state='ACTIVE',writer_stopped=None):
  n,day,marker=observe(self.root)
  value=validate(dict(schema='research.unverified-session-progress/1',run_id=self.run,head=self.head,arm=self.arm,phase=self.phase,
   phase_state=phase_state,elapsed_seconds=int(time.monotonic()-self.started),observed_utc=datetime.now(timezone.utc).isoformat(),
   checkpoint_completed=n,checkpoint_session=day,constructor_marker_seen=marker,writer_stopped=writer_stopped,
   verified=False,financial_sessions_admitted=0,observer_sha256=self.source))
  self.sequence+=1;self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
  path=self.directory/('progress-'+str(self.sequence)+'.json');path.write_bytes((json.dumps(value,sort_keys=True)+'\n').encode())
  print(json.dumps(value,sort_keys=True),flush=True)
  upload(path,'research-progress-'+self.arm+'-'+self.run+'-'+self.phase+'-'+str(self.sequence))
 def loop(self):
  while not self.stop.wait(60):
   try:self.publish()
   except Exception:pass
 def start(self):self.thread.start()
 def finish(self,result):
  self.stop.set();self.thread.join(timeout=0.1)
  if self.thread.is_alive():return
  try:self.publish('STOPPED' if isinstance(result,dict) and result.get('stopped') is True else 'UNKNOWN',True if isinstance(result,dict) and result.get('stopped') is True else None)
  except Exception:pass

def run(original,values,name,out,**kwargs):
 observer=None;result=None
 try:
  from probe import check_context
  check_context(os.environ);observer=Observer(out,name);observer.start()
 except Exception:observer=None
 try:
  result=original(values,name,out,**kwargs);return result
 finally:
  if observer is not None:
   try:observer.finish(result)
   except Exception:pass

def bind_launch(original,module):
 def launch(args):
  saved=module.stopped_run;module.stopped_run=lambda *a,**k:run(saved,*a,**k)
  try:return original(args)
  finally:module.stopped_run=saved
 return launch
