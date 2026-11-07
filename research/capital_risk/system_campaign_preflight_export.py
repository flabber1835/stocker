"""Bounded export of stopped evidence; omit only redundant preflight payloads."""
import hashlib,json,os,re,shutil,tempfile
from pathlib import Path,PurePosixPath
from full_system_benchmark import need
PREFIX='parent-preflight/'
POLICY='LARGE_IDENTICAL_NONFINANCIAL_PREFLIGHT_COPIES_V1'
FIELD='nonfinancial_preflight_export_policy'
RECEIPT='nonfinancial-preflight-export.json'
MINIMUM=1024**2
LIMIT=1024**3
INSPECTIONS=('parent-preflight/worker-inspect.json','worker-inspect.json','stopped-review/worker-inspect.json')
PROBE=b'{"synthetic_marker":"financial-resume-export-only","financial_sessions":0}\n'


def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def safe(name):
 need(type(name)is str and bool(name),'PREFLIGHT_EXPORT_STRING_MEMBER')
 p=PurePosixPath(name)
 need(bool(p.parts) and p.as_posix()==name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name,'PREFLIGHT_EXPORT_SAFE_MEMBER')
 return p


def plan(inventory):
 need(RECEIPT not in inventory,'PREFLIGHT_EXPORT_NO_EXISTING_RECEIPT_REPLACEMENT')
 outside={}
 for name,pin in sorted(inventory.items()):
  safe(name);need(type(pin['bytes'])is int and pin['bytes']>=0 and re.fullmatch('[0-9a-f]{64}',pin['sha256']) is not None,'PREFLIGHT_EXPORT_EXACT_MEMBER_COMMITMENT')
  if not name.startswith(PREFIX):outside.setdefault((pin['bytes'],pin['sha256']),name)
 omitted={}
 for name,pin in sorted(inventory.items()):
  protected=name.startswith((PREFIX+'book/',PREFIX+'lineage/')) or name.endswith(('/worker-inspect.json','.json.gz'))
  match=outside.get((pin['bytes'],pin['sha256']))
  if name.startswith(PREFIX) and not protected and pin['bytes']>=MINIMUM and match is not None:
   omitted[name]=dict(kept_path=match,**pin)
 return dict(schema='research.nonfinancial-preflight-export/1',policy=POLICY,financial_authority=False,financial_sessions_advanced=0,
  original_output_unchanged=True,original_inventory=inventory,omitted_duplicates=omitted,
  kept_paths=sorted(set(inventory)-set(omitted)),original_bytes=sum(p['bytes'] for p in inventory.values()),
  omitted_bytes=sum(p['bytes'] for p in omitted.values()),kept_bytes=sum(p['bytes'] for n,p in inventory.items() if n not in omitted))


def validate(value,inventory):
 need(value['schema']=='research.nonfinancial-preflight-export/1' and value['policy']==POLICY
  and value['financial_authority'] is False and value['financial_sessions_advanced']==0
  and value['original_output_unchanged'] is True and value['original_inventory']==inventory,'PREFLIGHT_EXPORT_EXACT_NONFINANCIAL_SCOPE')
 kept=set(value['kept_paths']);omitted=value['omitted_duplicates']
 need(len(kept)==len(value['kept_paths']) and kept==set(inventory)-set(omitted)
  and {n for n in inventory if not n.startswith(PREFIX)}<=kept,'PREFLIGHT_EXPORT_EVERY_ORIGINAL_NONPREFLIGHT_PATH_RETAINED')
 for name,pin in omitted.items():
  safe(name);target=pin['kept_path'];safe(target)
  need(name.startswith(PREFIX) and not name.startswith((PREFIX+'book/',PREFIX+'lineage/'))
   and not name.endswith(('/worker-inspect.json','.json.gz')) and pin['bytes']>=MINIMUM,'PREFLIGHT_EXPORT_ONLY_LARGE_NONFINANCIAL_PREFLIGHT_COPY')
  need(target in kept and not target.startswith(PREFIX) and inventory[name]==inventory[target]==dict(bytes=pin['bytes'],sha256=pin['sha256']),
   'PREFLIGHT_EXPORT_EXACT_ALREADY_KEPT_BYTES_NO_ALIAS_CHAIN')
 need(value['original_bytes']==sum(p['bytes'] for p in inventory.values())
  and value['omitted_bytes']==sum(p['bytes'] for p in omitted.values())
  and value['kept_bytes']==sum(inventory[n]['bytes'] for n in kept)
  and value['kept_bytes']+value['omitted_bytes']==value['original_bytes'],'PREFLIGHT_EXPORT_COMPLETE_BYTE_ACCOUNTING')
 need(value['kept_bytes']+len(encoded(value))<LIMIT,'PREFLIGHT_EXPORT_ORIGINAL_ONE_GIB_PLAINTEXT_BOUND')
 return value


def inventory(root):
 result={}
 for path in sorted(Path(root).rglob('*')):
  need(not path.is_symlink(),'PREFLIGHT_EXPORT_NO_SOURCE_SYMLINK')
  if path.is_file():
   name=path.relative_to(root).as_posix();safe(name)
   with path.open('rb') as f:pin=dict(bytes=path.stat().st_size,sha256=hashlib.file_digest(f,'sha256').hexdigest())
   result[name]=pin
 return result


def stopped(root):
 for name in INSPECTIONS:
  value=json.loads((Path(root)/name).read_bytes());state=value['State']
  need(state['Running'] is state['OOMKilled'] is False and type(state['ExitCode'])is int
   and re.fullmatch('[0-9a-f]{64}',value['Id']) is not None,'PREFLIGHT_EXPORT_ALL_ACTUAL_WRITERS_POSITIVELY_STOPPED')


def hosted_root(root):
 from probe import check_context
 check_context(os.environ);root=Path(root).resolve();temp=Path(os.environ['RUNNER_TEMP']).resolve()
 need(os.name=='posix' and str(temp)=='/home/runner/work/_temp' and root!=temp and root.is_relative_to(temp),'PREFLIGHT_EXPORT_OWNED_HOST_OUTPUT_ONLY')
 return root,temp


def bind_seal(original):
 def seal(root,path,key,request,arm,**kwargs):
  value=json.loads(Path(request).read_bytes())
  if FIELD not in value:return original(root,path,key,request,arm,**kwargs)
  need(value[FIELD]==POLICY and value['sources'].get(Path(__file__).name)==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
   'PREFLIGHT_EXPORT_EXPLICIT_EXACT_REQUEST_AND_SOURCE')
  root,temp=hosted_root(root)
  if root==temp/('financial-resume-probe-'+arm):
   need(set(root.iterdir())=={root/'marker.json'} and (root/'marker.json').read_bytes()==PROBE,'PREFLIGHT_EXPORT_EXACT_ORIGINAL_SYNTHETIC_PROBE')
   return original(root,path,key,request,arm,**kwargs)
  need(root==temp/('financial-resume-output-'+arm),'PREFLIGHT_EXPORT_EXACT_ORIGINAL_FINANCIAL_OUTPUT_DIRECTORY')
  if not all((root/name).is_file() for name in INSPECTIONS):
   # The mature caller retains its original stop/export gate. A failed
   # preparation keeps its complete diagnostic output without any new view.
   return original(root,path,key,request,arm,**kwargs)
  stopped(root);before=inventory(root);chosen=validate(plan(before),before)
  with tempfile.TemporaryDirectory(prefix='research-preflight-export-view-',dir=temp) as owned:
   view=Path(owned)/'view';view.mkdir(mode=0o700)
   for name in chosen['kept_paths']:
    dest=view/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,dest)
   (view/RECEIPT).write_bytes(encoded(chosen))
   need(inventory(view)=={**{n:before[n] for n in chosen['kept_paths']},RECEIPT:dict(bytes=len(encoded(chosen)),sha256=hashlib.sha256(encoded(chosen)).hexdigest())},
    'PREFLIGHT_EXPORT_ACTUAL_VIEW_HAS_EVERY_KEPT_BYTE_AND_RECEIPT')
   result=original(view,path,key,request,arm,**kwargs)
  need(not Path(owned).exists() and inventory(root)==before,'PREFLIGHT_EXPORT_ORIGINAL_UNCHANGED_AND_OWNED_VIEW_REMOVED')
  return result
 return seal
