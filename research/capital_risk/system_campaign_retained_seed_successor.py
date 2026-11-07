"""Whole original retained seed and ABMD factory with exact admitted metadata."""
import ast,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import digest,sha
import system_campaign_financial_uncertainty as original
import system_campaign_p06_abmd_point_continuation as point
import system_campaign_p06_abmd_initial_certificate as initial
U_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
CATALOG='system-campaign-retained-seed-successors.json'
CATALOG_SHA='080d960c9bd576963706f9bf7c47b744ded279e419b7843d863f53c24cba259e'
HERE=Path(__file__).parent

def metadata(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);raw=(HERE/CATALOG).read_bytes()
 need(len(CATALOG_SHA)==64 and sha(raw)==CATALOG_SHA,'SEED_SUCCESSOR_EXACT_METADATA_CATALOG')
 value=json.loads(raw);need(value['schema']=='research.retained-seed-successor-metadata/1' and value['financial_authority'] is False,'SEED_SUCCESSOR_METADATA_HAS_NO_FINANCIAL_AUTHORITY')
 result=value['roots'][spec['root_admission_sha256']]
 need(result['checkpoint_sha256']==spec['outer_sha256'] and result['checkpoint_file']==spec['selected_file']
  and result['input_descriptors']==spec['repairs'] and result['state_sha256']==spec['state_sha256'],
  'SEED_SUCCESSOR_ENTIRE_ACTUAL_ADMITTED_PARENT_METADATA')
 return result

def phase(spec):
 value=metadata(spec);proof=spec['root_admission']['branch_uncertainty_proof']
 need(value['committed_rows']==proof['rows']+proof.get('retained_rows',0),'SEED_SUCCESSOR_ALL_COMMITTED_ROWS_FROM_ADMISSION')
 return dict(rows=value['committed_rows'],new_rows=proof['rows'],retained_rows=proof.get('retained_rows',0))

def literal_prefix(raw,rows,spec):
 value=metadata(spec);lines=raw.splitlines(keepends=True);committed=b''.join(lines[:value['committed_rows']])
 need(dict(bytes=len(raw),sha256=sha(raw))==value['raw_proof'] and len(lines)==value['raw_rows']
  and dict(bytes=len(committed),sha256=sha(committed))==value['committed_proof']
  and point.proof_bytes(rows)==committed and len(rows)==value['committed_rows']
  and all(json.loads(v)['session']>spec['selected_session'] for v in lines[value['committed_rows']:]),
  'SEED_SUCCESSOR_LITERAL_COMPLETE_PREFIX_EXCLUDES_EVERY_RAW_TAIL')
 return True

def qualify_metadata(parent,spec,rows,committed,resolutions,allowed,archive,source_hashes,expected_hashes):
 value=metadata(spec)
 from system_campaign_full_history_successor import current_commitments
 current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(parent['sha256']==spec['outer_sha256'] and parent['base']==spec['base'] and parent['repairs']==spec['repairs']
  and parent['completed']==spec['measured_closes'] and parent['source_cursor']==spec['selected_session']
  and parent['run']['checkpoint_sha256']==spec['inner_sha256'] and parent['run']['state_sha256']==spec['state_sha256']
  and parent['run']['input_sha256']==spec['input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs'])),
  'SEED_SUCCESSOR_FULL_ACTUAL_PARENT_NOT_PROJECTED_OR_REPLACED')
 proof=spec['root_admission']['branch_uncertainty_proof'];expected=phase(spec)
 need(proof['passed'] is proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True
  and len(rows)==len(committed)==expected['rows'] and point.proof_bytes(rows)==point.proof_bytes(committed)
  and dict(bytes=len(point.proof_bytes(rows)),sha256=sha(point.proof_bytes(rows)))==value['committed_proof']
  and rows[-1]['session']==spec['selected_session'] and rows[-1]['next_state_sha256']==spec['state_sha256']
  and rows[-1]['chain_sha256']==value['last_chain_sha256'],'SEED_SUCCESSOR_LITERAL_ADMITTED_PROOFS_AND_FINAL_STATE')
 need(source_hashes==expected_hashes and len(source_hashes)==6 and source_hashes['sentinel/controller/median5.py']==point.WITNESS_SHA
  and all(parent['base']['sources'].get(n)==h for n,h in source_hashes.items()),'SEED_SUCCESSOR_ALL_SIX_UNCHANGED_CONTROLLER_IDENTITIES')
 events=[r for r in rows if r['session']=='2022-12-22']
 need(len(events)==len(resolutions)==1 and events[0]['event_basis']==events[0]['bounded_event_basis']
  and events[0]['bounded_event_basis']['selected'] is False and allowed=={},'SEED_SUCCESSOR_ONE_ORIGINAL_UNSELECTED_ABMD_EVENT_NO_NEW_PERMISSION')
 event,=events;resolution,=resolutions;epoch=value['historical_event_input_count']
 need(epoch==10 and resolution==value['historical_event_resolution']
  and resolution['actual']=='book/pre-event/2022-12-22-'+resolution['outer_sha256']+'.json.gz'
  and resolution['state_sha256']==event['prior_state_sha256']
  and resolution['input_sha256']==event['input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs'][:epoch]))
  and sha(archive)==resolution['gzip_sha256'],'SEED_SUCCESSOR_ACTUAL_ABMD_ARCHIVE_WITH_RETAINED_HISTORICAL_INPUT_EPOCH')
 return dict(passed=True,committed_rows=expected['rows'],unadmitted_tail_rows_used=0,second_event_authorized=False,financial_authority=False)

def seed_tree(raw):
 need(sha(raw)==U_SHA,'SEED_SUCCESSOR_WHOLE_ORIGINAL_SEED_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='retained_seed']
 imp,=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_branches']
 need([(v.name,v.asname) for v in imp.names]==[('validate_input',None),('seed',None),('discrete',None),('digest',None)],'SEED_SUCCESSOR_EXACT_ORIGINAL_SEED_IMPORTS')
 imp.names=imp.names[2:];return ast.fix_missing_locations(fn)

def bind_seed(*,contract,visitor,reader):
 need(all(callable(v) for v in (contract,visitor,reader)),'SEED_SUCCESSOR_EXPLICIT_COMPLETE_CONTRACT_VISITOR_AND_ORIGINAL_READER')
 scope=dict(vars(original),retained_contract=contract,retained_phase=phase,validate_input=visitor,seed=reader)
 exec(compile(ast.Module(body=[seed_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-retained-seed-explicit-history-and-reader>','exec'),scope)
 return scope['retained_seed']

def contract(parent,spec):
 from full_system_core import hosted
 hosted();metadata(spec)
 hashes=json.loads((HERE/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
 need(len(hashes)==6 and all(parent['base']['sources'].get(n)==h and sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),'SEED_SUCCESSOR_ALL_SIX_ACTUAL_PHYSICAL_CONTROLLER_SOURCES')
 point.arithmetic_sources(Path('/variant/sentinel/controller/median5.py').read_bytes(),(HERE/'system_campaign_point_growth.py').read_bytes(),(HERE/'system_campaign_financial_additional_sensor.py').read_bytes())
 from system_campaign_point_growth import point_growth
 point_growth(())
 return hashes

def prior_event(root,parent,rows,spec):
 from system_campaign_bounded_sensor_event_review import permissions
 import system_campaign_p06_abmd_lifecycle_data as lifecycle
 value=metadata(spec);allowed,resolutions=permissions(Path(root),rows,lifecycle.catalog(),through=parent['source_cursor'],input_descriptors=parent['repairs'][:value['historical_event_input_count']])
 need(allowed=={} and resolutions==[value['historical_event_resolution']],'SEED_SUCCESSOR_EXACT_ORIGINAL_EVENT_ARCHIVE_NO_SECOND_EVENT')
 return allowed,resolutions

def original_seed(root,parent,spec,*,visitor):
 from full_system_core import hosted
 hosted();root=Path(root);raw=(root/spec['selected_checkpoint']).read_bytes()
 from system_campaign_bounded_sensor_origin_v2 import strict_json
 need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'] and strict_json(raw)==parent,'SEED_SUCCESSOR_GENUINE_ORIGINAL_PARENT_GZIP')
 hashes,rows,qualified=bind_seed(contract=contract,visitor=visitor,reader=initial.seed_reader(inherited_root=HERE))(root,parent,spec)
 literal_prefix((root/'uncertainty-certificate.jsonl').read_bytes(),rows,spec)
 allowed,resolutions=prior_event(root,parent,rows,spec)
 qualify_metadata(parent,spec,rows,rows,resolutions,allowed,(root/resolutions[0]['actual']).read_bytes(),hashes,hashes)
 return hashes,rows,qualified,resolutions[0]

def factory(event,source,codec,native,*,inherited_root,retained_root,parent,spec,visitor,boundary):
 from full_system_core import hosted
 hosted();need(callable(boundary) and boundary() is True,'SEED_SUCCESSOR_GENUINE_NEUTRAL_BOUNDARY_REQUIRED_BEFORE_FACTORY')
 import system_campaign_p06_abmd_lifecycle_data as lifecycle
 value=lifecycle.catalog();need(event==value['event'] and source==value['market_source'],'SEED_SUCCESSOR_UNCHANGED_ABMD_EVENT_AND_SOURCE')
 root=Path(retained_root);hashes,rows,qualified,resolution=original_seed(root,parent,spec,visitor=visitor);archive=(root/resolution['actual']).read_bytes()
 def qualified_retained_seed(actual,source_hashes,actual_event,actual_source,actual_codec):
  need(actual_event==event and actual_source==source and actual_codec is codec and (root/resolution['actual']).read_bytes()==archive,'SEED_SUCCESSOR_FRESH_ACTUAL_ARCHIVE_CODEC_AND_SOURCE')
  qualify_metadata(parent,spec,actual,rows,[resolution],{},archive,source_hashes,hashes)
  need(sha(Path('/variant/sentinel/controller/median5.py').read_bytes())==point.WITNESS_SHA,'SEED_SUCCESSOR_FRESH_UNALTERED_WITNESS_SOURCE')
  return True
 scope=dict(vars(initial),mixed_growth=point.mixed_growth,qualified_retained_seed=qualified_retained_seed)
 exec(compile(ast.Module(body=[point.factory_tree(Path(initial.__file__).read_bytes())],type_ignores=[]),'<whole-original-ABMD-factory-and-point-operation-order>','exec'),scope)
 return scope['certificate_class'](event,source,codec,native,inherited_root=inherited_root)
