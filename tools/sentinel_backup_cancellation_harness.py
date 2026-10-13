"""Crash/cancellation qualification restricted to labeled disposable resources."""
import argparse, json, subprocess, time, uuid
from datetime import datetime, timezone
from pathlib import Path
import selectors

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path)
args=parser.parse_args()
image='postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b'
tag='close-backup-cancel-'+uuid.uuid4().hex[:16]
db=tag+'-db'; network=tag+'-net'; label='sentinel.isolated-cancellation-test='+tag
created=False; connected=False; results=[]
def run(args,check=True,timeout=30):
 return subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=check)
def inspect():return json.loads(run(['docker','inspect',db]).stdout)[0]
try:
 run(['docker','network','create','--internal','--label',label,network]); connected=True
 run(['docker','run','-d','--name',db,'--label',label,'--network',network,
      '--memory','512m','--cpus','0.5','-p','127.0.0.1::5432','-e','POSTGRES_PASSWORD=isolated-only',
      '--tmpfs','/var/lib/postgresql/data:rw,size=128m',image]);created=True
 deadline=time.monotonic()+25
 while run(['docker','exec',db,'pg_isready','-h','127.0.0.1','-U','postgres'],check=False).returncode:
  assert time.monotonic()<deadline
  time.sleep(.5)
 def sql(query):
  return run(['docker','exec',db,'psql','-X','-q','-At','-U','postgres','-d','postgres','-c',query]).stdout.strip()
 sql("CREATE TABLE cancellation_probe AS SELECT g,repeat('x',1000) AS value FROM generate_series(1,4000) g")
 def witness_row(process,query):
  process.stdin.write(query+';\n');process.stdin.flush()
  with selectors.DefaultSelector() as selector:
   selector.register(process.stdout,selectors.EVENT_READ)
   assert selector.select(5),'isolated witness response deadline'
   return process.stdout.readline().strip()
 for variant in ('primary-exec','isolated-client'):
  witness=subprocess.Popen(['docker','exec','-i',db,'psql','-X','-q','-At','-U','postgres','-d','postgres'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  pid=int(witness_row(witness,'SELECT pg_backend_pid()'))
  started=datetime.now(timezone.utc).isoformat()
  command='export PGPASSWORD=isolated-only; pg_basebackup -h '+db+' -U postgres -D /tmp/cancel-'+variant+' -Fp -Xs -P -c fast --max-rate=32k'
  if variant=='primary-exec':
   command=command.replace('-h '+db,'-h 127.0.0.1')
   argv=['docker','exec',db,'timeout','--kill-after=2s','3s','sh','-ceu',command.replace('-h '+db,'-h 127.0.0.1')]
  else:
   argv=['docker','run','--rm','--init','--label',label,'--network','container:'+db,
    '--memory','256m','--cpus','0.5','--entrypoint','timeout',image,
    '--kill-after=2s','3s','sh','-ceu',command.replace('-h '+db,'-h 127.0.0.1')]
  result=run(argv,check=False,timeout=15)
  assert result.returncode==124,(variant,result.returncode,result.stderr[-1000:])
  try:lost=witness_row(witness,'SELECT 1')!='1'
  except AssertionError:lost=True
  witness.stdin.close()
  try:witness.wait(timeout=5)
  except subprocess.TimeoutExpired:witness.kill();witness.wait(timeout=5)
  time.sleep(1)
  logs=run(['docker','logs','--since',started,db]).stdout+run(['docker','logs','--since',started,db]).stderr
  recovery=any(s in logs for s in ('reinitializing','automatic recovery in progress','was terminated by signal'))
  record=dict(variant=variant,timeout_exit=result.returncode,witness_connection_lost=lost,
   database_recovered=recovery,backup_progress=result.stderr[-500:],recovery_log='\n'.join(x for x in logs.splitlines() if any(k in x for k in ('terminated','recovery','reinitializing')))[-1200:])
  results.append(record);print(json.dumps(record),flush=True)
  deadline=time.monotonic()+15
  while run(['docker','exec',db,'pg_isready','-h','127.0.0.1','-U','postgres'],check=False).returncode:
   assert time.monotonic()<deadline;time.sleep(.5)
  assert sql('SELECT count(*) FROM cancellation_probe')=='4000'
 assert results[0]['witness_connection_lost'] and results[0]['database_recovered']
 assert not results[1]['witness_connection_lost'] and not results[1]['database_recovered']
 normal=run(['docker','run','--rm','--init','--label',label,'--network','container:'+db,
             '--memory','256m','--cpus','0.5','--entrypoint','sh',image,'-ceu',
             'export PGPASSWORD=isolated-only; pg_basebackup -h 127.0.0.1 -U postgres -D /tmp/verified -Fp -Xs -c fast; pg_verifybackup /tmp/verified'])
 assert 'successfully verified' in normal.stdout
 assert sql('SELECT count(*) FROM cancellation_probe')=='4000'
 results.append(dict(variant='normal-isolated-copy',verified=True,source_rows=4000))
 print(json.dumps(results[-1]),flush=True)
 if args.output:
  args.output.parent.mkdir(parents=True,exist_ok=True)
  args.output.write_text(json.dumps(results,indent=2)+'\n')
finally:
 if created:
  assert inspect()['Config']['Labels']['sentinel.isolated-cancellation-test']==tag
  run(['docker','rm','-f',db])
 if connected:
  v=json.loads(run(['docker','network','inspect',network]).stdout)[0]
  assert v['Labels']['sentinel.isolated-cancellation-test']==tag
  run(['docker','network','rm',network])
