"""Exact saved P07 proofs and whole original post-event factory bindings."""
import ast,gzip,json
from pathlib import Path
from types import SimpleNamespace
import system_campaign_financial_uncertainty as uncertainty
import system_campaign_p07_vivo_models as models
import system_campaign_p07_vivo_retained as retained
import system_campaign_p07_vivo_certificate as certificate
import system_campaign_p07_abmd_lifecycle as original_lifecycle
import system_campaign_p07_abmd_certificate as frozen
from system_campaign_facts import sha,digest
from full_system_benchmark import need
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
HERE=Path(__file__).parent
METADATA='P07-BWA-retained929-source.json'
METADATA_SHA='92a073c9e1a4732e2b117fec79a6dfc9b84cbfeae688b139547ace704d52015f'
ROOT='66ea8c9f48fe10335a6255d12a8d2482fd9c2e3742702c71cbaa936c21f6b695'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def metadata(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);raw=(HERE/METADATA).read_bytes()
 need(sha(raw)==METADATA_SHA,'P07_SAVED_EXACT_AUTHENTICATED_METADATA')
 value=json.loads(raw);proof=spec['root_admission']['branch_uncertainty_proof']
 need(value['schema']=='research.P07-postclose-retained929-source/1' and value['financial_authority'] is value['financial_profile_ready'] is False
  and spec['arm']=='P07' and value['root_admission_sha256']==spec['root_admission_sha256']==ROOT
  and value['checkpoint_sha256']==spec['outer_sha256'] and value['checkpoint_file']==spec['selected_file']
  and value['state_sha256']==spec['state_sha256'] and value['input_sha256']==spec['input_sha256']
  and value['descriptors']==spec['repairs'] and len(spec['repairs'])==25
  and value['retained_ABMD_declaration']==spec['retained_abmd']
  and value['committed_rows']==proof['rows']+proof['retained_rows']==929 and value['raw_rows']==930,
  'P07_SAVED_ENTIRE_REAL25_PARENT_AND_ALL929_ADMITTED_PROOFS')
 return value

def parent_contract(parent,spec):
 from system_campaign_full_history_successor import current_commitments
 metadata(spec);current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(parent['sha256']==spec['outer_sha256'] and parent['repairs']==spec['repairs'] and parent['journals']==spec['journals']
  and parent['completed']==spec['measured_closes'] and parent['source_cursor']==spec['selected_session'],'P07_SAVED_GENUINE_COMPLETE_ADMITTED_PARENT')

def full_parent(root,parent,spec=None):
 from system_campaign_financial_partial import root_spec
 from system_campaign_abmd_bounded_catalog import evidence
 spec=root_spec('P07',ROOT) if spec is None else spec;parent_contract(parent,spec);root=Path(root)
 catalog=original_lifecycle.catalog()
 result=models.models().validate_full(root,parent,catalog,evidence(catalog),input_hash=lambda b,r:digest(dict(base=b,repairs=r)),
  root_metadata=original_lifecycle.initial_spec())
 origin=models.origin();member=lambda n:(root/n).read_bytes()
 origin.validate(json.loads(member(origin.ORIGIN)),parent,catalog,original_lifecycle.initial_spec(),member,
  input_hash=lambda b,r:digest(dict(base=b,repairs=r)),read_checkpoint=lambda n:strict_json(member(n)),zero_adoption=adoption,
  observation_seed=gzip.decompress(member(origin.DIRECTORY+'/correlation-inputs.jsonl.gz')))
 need(result['full_input_count']==25,'P07_SAVED_COMPLETE_UNCHANGED_PREVIOUS_VISITOR_AND_ORIGIN')
 return result

def phase(spec):
 proof=spec['root_admission']['branch_uncertainty_proof'];value=metadata(spec)
 return dict(rows=value['committed_rows'],new_rows=proof['rows'],retained_rows=proof['retained_rows'])

def literal_prefix(raw,rows,spec):
 value=metadata(spec);lines=raw.splitlines(keepends=True);prefix=b''.join(lines[:value['committed_rows']])
 need(dict(bytes=len(raw),sha256=sha(raw))==value['raw_proof'] and len(lines)==value['raw_rows']
  and dict(bytes=len(prefix),sha256=sha(prefix))==value['committed_prefix']
  and b''.join(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for v in rows)==prefix
  and len(rows)==929 and rows[-1]['chain_sha256']==value['last_chain_sha256'] and rows[-1]['next_state_sha256']==spec['state_sha256']
  and [json.loads(v)['session'] for v in lines[929:]]==value['excluded_tail_sessions']
  and all(json.loads(v)['session']>spec['selected_session'] for v in lines[929:]),'P07_SAVED_LITERAL929_PREFIX_NO_UNADMITTED930TH_ROW')
 return True

def physical_contract(parent,spec):
 from full_system_core import hosted
 hosted();parent_contract(parent,spec);hashes=metadata(spec)['controller_sources']
 need(len(hashes)==6 and all(parent['base']['sources'][name]==pin and sha((Path('/variant')/name).read_bytes())==pin
  for name,pin in hashes.items()),'P07_SAVED_ALL_SIX_UNCHANGED_PHYSICAL_CONTROLLER_SOURCES')
 return hashes

def seed_reader(*,contract=physical_contract,visitor=full_parent):
 scope=dict(vars(uncertainty),retained_contract=contract,retained_phase=phase,validate_input=visitor)
 tree=retained.seed_tree(Path(uncertainty.__file__).read_bytes())
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-original-retained-seed-genuine929-parent25>','exec'),scope)
 whole=scope['retained_seed']
 def read(root,parent,spec):
  parent_contract(parent,spec);raw=(Path(root)/spec['selected_checkpoint']).read_bytes()
  need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'] and strict_json(raw)==parent,'P07_SAVED_REAL_SELECTED_GZIP_BEFORE_READING_SEED')
  result=whole(Path(root),parent,spec);literal_prefix((Path(root)/'uncertainty-certificate.jsonl').read_bytes(),result[1],spec)
  return result
 return read

def retained_tree(raw):
 need(sha(raw)==retained.LIFECYCLE_SHA,'P07_SAVED_WHOLE_ORIGINAL_RETAINED_DECLARATION_VALIDATOR')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='valid_retained']
 models.replace_count(fn,"len(spec['repairs']) == 24","len(spec['repairs']) == 25",1,'P07_SAVED_ONE_FINITE_REAL_PARENT_COUNT')
 return ast.fix_missing_locations(fn)

def historical_input_sha256(current):
 need(len(current['repairs'])==25,'P07_SAVED_ONLY_REAL_FULL25_EVENT_EPOCH_READER')
 return digest(dict(base=current['base'],repairs=current['repairs'][:24]))

def metadata_tree(raw):
 need(sha(raw)==certificate.SOURCE_SHA,'P07_SAVED_WHOLE_ORIGINAL_POSTEVENT_FACTORY_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_metadata']
 models.replace_count(fn,"len(current['repairs']) == 24","len(current['repairs']) == 25",1,'P07_SAVED_ONE_METADATA_PARENT_COUNT')
 models.replace_count(fn,"resolution['input_sha256'] == row['input_sha256'] == current['run']['input_sha256']",
  "resolution['input_sha256'] == row['input_sha256'] == historical_input_sha256(current)",1,'P07_SAVED_ORIGINAL_EVENT_ARCHIVE_EPOCH_NOT_CURRENT25')
 site,=[kw for n in ast.walk(fn) if isinstance(n,ast.Call) for kw in n.keywords if kw.arg=='full_input_descriptors']
 need(isinstance(site.value,ast.Constant) and site.value.value==24,'P07_SAVED_ONE_TRUTHFUL_METADATA_RETURN_COUNT')
 site.value.value=25
 return ast.fix_missing_locations(fn)

def historical_permissions(root,rows,catalog,*,through,input_descriptors):
 from system_campaign_bounded_sensor_event_review import permissions
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',ROOT);value=metadata(spec)
 need(input_descriptors==spec['repairs'] and through==spec['selected_session'],'P07_SAVED_HISTORICAL_PERMISSION_ONLY_EXACT_PARENT25')
 actual=retained.actual_event_descriptors(root,input_descriptors)
 need(actual==value['historical_event_descriptors'],'P07_SAVED_GENUINE_ARCHIVED24_EVENT_DESCRIPTOR_AXIS')
 allowed,resolutions=permissions(root,rows,catalog,through=through,input_descriptors=actual)
 need(digest(allowed)==digest(value['historical_permissions']) and resolutions==[value['historical_event_resolution']],
  'P07_SAVED_UNCHANGED_HISTORICAL_PERMISSION_AND_EXACT_PRODUCER_GZIP')
 return allowed,resolutions

def qualify_metadata(original,current,spec,catalog,origin_value,rows,committed,resolutions,allowed,archive_raw,*,source_plan):
 parent_contract(current,spec);value=metadata(spec)
 result=original(current,spec,catalog,origin_value,rows,committed,resolutions,allowed,archive_raw,source_plan=source_plan)
 prefix=b''.join(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for v in rows)
 archive=strict_json(archive_raw)
 need(len(rows)==929 and dict(bytes=len(prefix),sha256=sha(prefix))==value['committed_prefix']
  and rows[-1]['chain_sha256']==value['last_chain_sha256'] and rows[-1]['next_state_sha256']==value['last_next_state_sha256']
  and digest(allowed)==digest(value['historical_permissions']) and resolutions==[value['historical_event_resolution']]
  and archive['repairs']==value['historical_event_descriptors'] and archive['sha256']==resolutions[0]['outer_sha256']
  and archive['run']['state_sha256']==resolutions[0]['state_sha256'] and archive['run']['input_sha256']==historical_input_sha256(current),
  'P07_SAVED_EXACT929_AND_GENUINE_HISTORICAL24_EVENT_ARCHIVE')
 return result

def factory_nodes(raw):
 need(sha(raw)==certificate.SOURCE_SHA,'P07_SAVED_ENTIRE_ORIGINAL_FACTORY_FUNCTIONS')
 nodes=[]
 for fn in ast.parse(raw).body:
  if not isinstance(fn,ast.FunctionDef):continue
  if fn.name=='qualify_metadata':fn=metadata_tree(raw)
  if fn.name=='certificate_class':
   site,=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_bounded_sensor_event_review']
   need([(n.name,n.asname) for n in site.names]==[('permissions',None)],'P07_SAVED_ONE_HISTORICAL_EVENT_PERMISSION_IMPORT')
   fn.body.remove(site)
  nodes.append(fn)
 return ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[]))

def factory_namespace():
 life=retained.lifecycle();life_scope=life.phase.__globals__
 exec(compile(ast.Module(body=[retained_tree(Path(original_lifecycle.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-retained-declaration-exact-parent25>','exec'),life_scope)
 life.valid_retained=life_scope['valid_retained']
 scope=dict(frozen=frozen,lifecycle=life,models=models.models(),origin=models.origin(),ast=ast,json=json,Path=Path,
  sha=sha,digest=digest,need=need,FROZEN_SHA='4f3db7f1cefffbad4c6eb48c0efe82678282c96c2a7b97c039db2307b9d86baa',
  SCHEMA='research.p07-abmd-admitted-continuation-qualification/1',historical_input_sha256=historical_input_sha256,permissions=historical_permissions)
 exec(compile(factory_nodes(certificate.source()),'<whole-original-postevent-factory-genuine929-full25>','exec'),scope)
 original=scope['qualify_metadata']
 scope['qualify_metadata']=lambda *a,**k:qualify_metadata(original,*a,**k)
 return SimpleNamespace(**scope)

def certificate_class(*args,**kwargs):
 from full_system_core import hosted
 hosted();parent_contract(kwargs['current_checkpoint'],kwargs['admitted_spec'])
 return factory_namespace().certificate_class(*args,**kwargs)
