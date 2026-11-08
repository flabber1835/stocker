"""Exact actual neutral boundary plus immutable typed-input origin resources."""
from copy import deepcopy
import gzip,json
from pathlib import Path,PurePosixPath
from system_campaign_bounded_sensor_input import need,sha,digest
from system_campaign_bounded_sensor_catalog import encoded
import system_campaign_bounded_sensor_lifecycle_data as original

ORIGIN='bounded-contingent-origin-v2.json'
SCHEMA='research.bounded-contingent-actual-neutral-origin/2'
ADOPTED=original.ORIGIN_DIRECTORY+'/neutral-checkpoint.json.gz'
PROOF=original.ORIGIN_DIRECTORY+'/neutral-proof.json'
PARENT=original.ORIGIN_DIRECTORY+'/parent-checkpoint.json.gz'
PRIOR=original.ORIGIN_DIRECTORY+'/prior-certificate.jsonl'

def exact(path,raw):
    path=Path(path)
    if path.exists():need(path.read_bytes()==raw,'BOUNDED_ORIGIN_EXISTING_BYTES_IDENTICAL')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)

def strict_json(raw):
    cp=json.loads(gzip.decompress(raw));run=cp['run']
    need(cp['sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
         and run['checkpoint_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==digest(run['state'])
         and cp['source_cursor']==run['state']['last_processed_session']
         and run['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs'])),
         'BOUNDED_ORIGIN_ALL_ACTUAL_JSON_COMMITMENTS')
    return cp

def validate_bundle(value,current,catalog,typed,root_metadata,member,*,input_hash,zero_adoption):
    need(value['schema']==SCHEMA and value['passed'] is True and value['initial_root_admission_sha256']==
         catalog['parent_root_admission_sha256']==root_metadata['root_admission_sha256']
         and value['catalog_sha256']==sha(encoded(catalog))
         and value['financial_sessions_advanced']==0 and type(value['financial_sessions_advanced']) is int
         and value['canonical_financial_source_changed'] is value['old_observer_origin_is_financial_seed'] is False,
         'BOUNDED_ORIGIN_EXACT_FAMILY_AND_NO_FALSE_AUTHORITY')
    pins=value['boundary_files']
    need(set(pins)=={PARENT,ADOPTED,PROOF} and pins[PARENT]==root_metadata['selected_file'],
         'BOUNDED_ORIGIN_EXACT_ORIGINAL_ADMITTED_PARENT_GZIP_PIN')
    files=value['origin']['input_files']
    need(type(files) is dict and files and all(type(n) is str and not PurePosixPath(n).is_absolute()
         and '..' not in PurePosixPath(n).parts and PurePosixPath(n).as_posix()==n and ':' not in n and '\\' not in n
         and type(pin) is str and len(pin)==64 and all(c in '0123456789abcdef' for c in pin) for n,pin in files.items()),
         'BOUNDED_ORIGIN_ALL_SAFE_AUTHENTIC_RESOURCE_NAMES_BEFORE_READ')
    raw={n:member(n) for n in pins}
    need(all(dict(bytes=len(raw[n]),sha256=sha(raw[n]))==pin for n,pin in pins.items()),
         'BOUNDED_ORIGIN_AUTHENTIC_BOUNDARY_BYTES_BEFORE_PARSING')
    parent,adopted=strict_json(raw[PARENT]),strict_json(raw[ADOPTED]);proof=json.loads(raw[PROOF])
    need(parent['sha256']==catalog['parent_outer_sha256'] and parent['repairs']==catalog['parent_descriptors']
         and adopted['sha256']==value['origin']['initial_adopted_outer_sha256']
         and proof['event']==zero_adoption(adopted,parent,typed.sha256,catalog['event']['native_session'])
         and proof['actual_checkpoint_gzip_sha256']==sha(raw[ADOPTED])
         and proof['original_outer_sha256']==parent['sha256'] and proof['financial_state_unchanged'] is True
         and type(proof['financial_sessions_advanced']) is int and proof['financial_sessions_advanced']==0,
         'BOUNDED_ORIGIN_ORIGINAL_ACTUAL_NEUTRAL_ADOPTION_RELATION')
    need(current['sha256']==digest({k:v for k,v in current.items() if k!='sha256'})
         and current['run']['checkpoint_sha256']==digest({k:v for k,v in current['run'].items() if k!='checkpoint_sha256'})
         and current['run']['state_sha256']==digest(current['run']['state'])
         and current['source_cursor']==current['run']['state']['last_processed_session'],
         'BOUNDED_ORIGIN_ACTUAL_CURRENT_STATE_AND_CHECKPOINT_COMMITMENTS')
    original.validate_origin(value['origin'],adopted,catalog,input_hash=input_hash,member=member,typed=typed,root_metadata=root_metadata)
    need(current['base']==parent['base'] and current['completed']>=parent['completed']
         and current['source_cursor']>=parent['source_cursor']
         and current['repairs'][:len(adopted['repairs'])]==adopted['repairs'] and len(adopted['repairs'])==16
         and current['run']['input_sha256']==input_hash(current['base'],current['repairs']),
         'BOUNDED_ORIGIN_FULL16_CONTINUATION_IDENTITY')
    return parent,adopted

def create(old,out,parent,adopted,catalog,typed,spec,*,root_metadata,extra_files=()):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest
    from system_campaign_pxd_pause import adoption
    old,out=Path(old),Path(out)
    original_parent=(old/spec['selected_checkpoint']).read_bytes()
    neutral=(out/original.DIRECTORY/'checkpoint.json.gz').read_bytes()
    proof_raw=(out/original.DIRECTORY/'proof.json').read_bytes();proof=json.loads(proof_raw)
    for name,raw in ((PARENT,original_parent),(ADOPTED,neutral),(PROOF,proof_raw),
                     (PRIOR,(old/'uncertainty-certificate.jsonl').read_bytes()),
                     (original.ORIGIN_DIRECTORY+'/catalog.json',encoded(catalog))):exact(out/name,raw)
    required=original.resource_pins(catalog,typed,root_metadata)
    names=set(required)|{ADOPTED,PROOF}|set(extra_files)
    resources={name:sha((out/name).read_bytes()) for name in names}
    origin=original.origin(parent,adopted,catalog,typed,proof,resources,input_hash=backtest.input_hash,
                           zero_adoption=adoption,root_metadata=root_metadata)
    value=dict(schema=SCHEMA,passed=True,initial_root_admission_sha256=catalog['parent_root_admission_sha256'],
        catalog_sha256=sha(encoded(catalog)),origin=origin,
        boundary_files={n:dict(bytes=len((out/n).read_bytes()),sha256=sha((out/n).read_bytes())) for n in (PARENT,ADOPTED,PROOF)},
        financial_sessions_advanced=0,canonical_financial_source_changed=False,old_observer_origin_is_financial_seed=False)
    validate_bundle(value,adopted,catalog,typed,root_metadata,lambda n:(out/n).read_bytes(),
                    input_hash=backtest.input_hash,zero_adoption=adoption)
    exact(out/ORIGIN,encoded(value));return value

def load(root,current,catalog,typed,root_metadata):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest
    from system_campaign_pxd_pause import adoption
    root=Path(root);value=json.loads((root/ORIGIN).read_bytes())
    parents=validate_bundle(value,current,catalog,typed,root_metadata,lambda n:(root/n).read_bytes(),
        input_hash=backtest.input_hash,zero_adoption=adoption)
    return value,*parents

def preserve(root,current,out,catalog,typed,root_metadata):
    from full_system_core import hosted
    hosted()
    root,out=Path(root),Path(out);value,_,_=load(root,current,catalog,typed,root_metadata)
    names=set(value['origin']['input_files'])|set(value['boundary_files'])|{ORIGIN}
    for name in names:exact(out/name,(root/name).read_bytes())
    return value
