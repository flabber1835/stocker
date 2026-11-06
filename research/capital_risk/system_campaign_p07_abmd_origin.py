"""Exact actual neutral24-input origin; no synthetic financial checkpoint writer."""
from copy import deepcopy
import ast,gzip,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
import system_campaign_p07_abmd_models as models

SCHEMA='research.p07-abmd-neutral-origin/1'
ORIGIN='p07-abmd-origin.json'
DIRECTORY='p07-abmd-origin'
ADOPTION='p07-abmd-neutral-adoption'
DOCUMENT='p07-abmd-bounded-input.json'
SOURCE='p07-abmd-event-source.json'
INITIAL_OBSERVATION_PIN={'bytes':137581003,'sha256':'ab86a9bdd15e4a46ecbb2dd346e45c25450f2bf89cc0b3d3d31d11171d62343a'}

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def filenames():
    return {DOCUMENT,SOURCE,*(DIRECTORY+'/'+name for name in ('parent-checkpoint.json.gz',
        'adopted-checkpoint.json.gz','proof.json','correlation-inputs.jsonl.gz',
        'prior-committed-certificate.jsonl','entire-prior-certificate.jsonl'))}

def validate(value,current,catalog,root_metadata,member,*,input_hash,read_checkpoint,zero_adoption,observation_seed):
    p=models.plan()
    need(set(value)=={'schema','arm','passed','catalog_sha256','initial_root_admission_sha256','parent_outer_sha256',
         'adopted_outer_sha256','adopted_input_sha256','descriptor','parent_file','adopted_file','input_files',
         'committed_proof_rows','committed_proof_prefix','financial_state_unchanged','financial_sessions_advanced',
         'canonical_financial_source_changed','financial_root_admitted'}
         and value['schema']==SCHEMA and value['arm']=='P07' and value['passed'] is True
         and value['initial_root_admission_sha256']==p['root_admission_sha256']==root_metadata['root_admission_sha256']
         and value['catalog_sha256']==sha(encoded(catalog)) and value['parent_outer_sha256']==p['parent_outer_sha256']
         and value['committed_proof_rows']==784 and type(value['committed_proof_rows']) is int
         and value['committed_proof_prefix']==p['committed_certificate_prefix'],
         'P07_ABMD_EXACT_SOURCE_BOUND_ORIGIN_HEADER')
    need(value['financial_state_unchanged'] is True and value['canonical_financial_source_changed']
         is value['financial_root_admitted'] is False and type(value['financial_sessions_advanced']) is int
         and value['financial_sessions_advanced']==0,'P07_ABMD_NEUTRAL_ORIGIN_GRANTS_NO_FINANCIAL_ROOT')
    need(set(value['input_files'])==filenames() and all(type(pin) is str and len(pin)==64
         and all(c in '0123456789abcdef' for c in pin) for pin in value['input_files'].values()),
         'P07_ABMD_EXACT_COMPLETE_ORIGIN_FILE_AXIS')
    raw={name:member(name) for name in value['input_files']}
    need(all(sha(raw[name])==pin for name,pin in value['input_files'].items()),
         'P07_ABMD_AUTHENTICATE_EVERY_ORIGIN_BYTE_BEFORE_PARSE')
    parent_name=DIRECTORY+'/parent-checkpoint.json.gz';adopted_name=DIRECTORY+'/adopted-checkpoint.json.gz'
    need(dict(bytes=len(raw[parent_name]),sha256=sha(raw[parent_name]))==value['parent_file']==root_metadata['selected_file']
         and dict(bytes=len(raw[adopted_name]),sha256=sha(raw[adopted_name]))==value['adopted_file'],
         'P07_ABMD_AUTHENTIC_ACTUAL_PARENT_AND_NEUTRAL_GZIP_BYTES')
    parent=read_checkpoint(parent_name);adopted=read_checkpoint(adopted_name)
    need(parent['sha256']==p['parent_outer_sha256'] and parent['repairs']==p['parent_descriptors']
         and parent['base']==root_metadata['base'] and parent['run']['checkpoint_sha256']==catalog['parent_inner_sha256']
         and (parent['source_cursor'],parent['completed'])==('2022-11-30',1238),
         'P07_ABMD_ORIGIN_IS_ACTUAL_OWN1238_FULL23_PARENT')
    from system_campaign_abmd_bounded_catalog import document
    doc=json.loads(raw[DOCUMENT]);h=sha(raw[DOCUMENT]);descriptor=dict(filename=h+'.json',sha256=h,
        resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
    need(raw[DOCUMENT]==encoded(document(catalog)) and raw[SOURCE]==encoded(catalog['market_source'])
         and value['descriptor']==descriptor and adopted['repairs']==parent['repairs']+[descriptor]
         and adopted['sha256']==value['adopted_outer_sha256']
         and adopted['run']['input_sha256']==value['adopted_input_sha256']==input_hash(adopted['base'],adopted['repairs']),
         'P07_ABMD_EXACT_ACTUAL_NEUTRAL24_DESCRIPTOR_AND_INPUT_HASH')
    event=zero_adoption(adopted,parent,h,catalog['event']['native_session'])
    proof=json.loads(raw[DIRECTORY+'/proof.json'])
    need(type(proof['financial_sessions_advanced']) is int and proof['financial_state_unchanged'] is True
         and proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(raw[adopted_name]),original_outer_sha256=parent['sha256'],
         financial_state_unchanged=True,financial_sessions_advanced=0),
         'P07_ABMD_WHOLE_ORIGINAL_CANONICAL_ZERO_ADOPTION_PROOF')
    need(type(observation_seed) is bytes
         and dict(bytes=len(observation_seed),sha256=sha(observation_seed))==INITIAL_OBSERVATION_PIN
         and gzip.decompress(raw[DIRECTORY+'/correlation-inputs.jsonl.gz'])==observation_seed,
         'P07_ABMD_EXACT_OLD_OBSERVATION_BYTES_NO_NEUTRAL_TRANSITION')
    committed=raw[DIRECTORY+'/prior-committed-certificate.jsonl'];entire=raw[DIRECTORY+'/entire-prior-certificate.jsonl']
    need(dict(bytes=len(committed),sha256=sha(committed))==p['committed_certificate_prefix']
         and dict(bytes=len(entire),sha256=sha(entire))==p['full_certificate_file'] and entire.startswith(committed),
         'P07_ABMD_ENTIRE_PRIOR_FILE_AND784_COMMITTED_BYTES_PRESERVED')
    need(current['base']==parent['base'] and current['repairs']==adopted['repairs'] and len(current['repairs'])==24
         and current['run']['input_sha256']==adopted['run']['input_sha256']==input_hash(current['base'],current['repairs'])
         and current['completed']>=parent['completed'] and current['source_cursor']>=parent['source_cursor'],
         'P07_ABMD_FULL_CURRENT24_HISTORY_AND_CANONICAL_HASH')
    return dict(passed=True,parent=parent,adopted=adopted,descriptor=descriptor,
                prior_proof_rows_reexecuted=0,financial_sessions_advanced=0)

def pause_tree(raw):
    import system_campaign_financial_additional_sensor as inherited
    fn=inherited.function(raw,'paused_own_adoption')
    need(sha(ast.dump(fn,include_attributes=False).encode())==inherited.LEGACY_AST['pause'],
         'P07_ABMD_ENTIRE_ORIGINAL_PAUSE_GATE_AST')
    site,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    need(isinstance(site.value,ast.Dict),'P07_ABMD_ORIGINAL_FILENAME_MAP')
    site.value.keys.append(ast.Constant(ADOPTION));site.value.values.append(ast.Constant(DOCUMENT))
    return ast.fix_missing_locations(fn)

def write_exact(path,raw):
    path=Path(path)
    if path.exists():need(path.read_bytes()==raw,'P07_ABMD_EXACT_EXISTING_ORIGIN_RESOURCE')
    else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

def adopt(parent,out,args,rows,catalog,codec,spec,old):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    import system_campaign_financial_uncertainty as u
    from system_campaign_financial_partial import root_spec,validate_root_spec
    from system_campaign_financial_resume import adoption
    from system_campaign_abmd_bounded_catalog import document,validate as validate_catalog,evidence
    validate_root_spec(spec);root=root_spec('P07',models.plan()['root_admission_sha256'])
    need(spec['root_admission_sha256']==root['root_admission_sha256'] and parent['repairs']==root['repairs'],
         'P07_ABMD_ONLY_EXACT_REGISTERED_INITIAL_ROOT')
    validate_catalog(catalog,root_lookup=root_spec)
    need(getattr(backtest.load_repair,'__self__',None) is codec and codec.event==catalog['event'],
         'P07_ABMD_SAME_INSTALLED_TYPED_INPUT_CODEC')
    out,old=Path(out),Path(old);write_exact(out/DOCUMENT,encoded(document(catalog)))
    write_exact(out/SOURCE,encoded(catalog['market_source']))
    scope=dict(vars(u));exec(compile(ast.Module(body=[pause_tree(Path(u.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-pause-one-P07-ABMD-filename>','exec'),scope)
    current=scope['paused_own_adoption'](parent,out,args,rows,out/DOCUMENT,catalog['event']['native_session'],ADOPTION)
    models.validate_full(out,current,catalog,evidence(catalog),input_hash=backtest.input_hash,root_metadata=root)
    p=models.plan();entire=(old/'uncertainty-certificate.jsonl').read_bytes();committed=entire[:p['committed_certificate_prefix']['bytes']]
    files={DOCUMENT:(out/DOCUMENT).read_bytes(),SOURCE:(out/SOURCE).read_bytes(),
        DIRECTORY+'/parent-checkpoint.json.gz':(old/spec['selected_checkpoint']).read_bytes(),
        DIRECTORY+'/adopted-checkpoint.json.gz':(out/ADOPTION/'checkpoint.json.gz').read_bytes(),
        DIRECTORY+'/proof.json':(out/ADOPTION/'proof.json').read_bytes(),
        DIRECTORY+'/correlation-inputs.jsonl.gz':(out/(ADOPTION+'-correlation-inputs.jsonl.gz')).read_bytes(),
        DIRECTORY+'/prior-committed-certificate.jsonl':committed,DIRECTORY+'/entire-prior-certificate.jsonl':entire}
    for name,raw in files.items():write_exact(out/name,raw)
    value=dict(schema=SCHEMA,arm='P07',passed=True,catalog_sha256=sha(encoded(catalog)),
        initial_root_admission_sha256=root['root_admission_sha256'],parent_outer_sha256=parent['sha256'],
        adopted_outer_sha256=current['sha256'],adopted_input_sha256=current['run']['input_sha256'],descriptor=deepcopy(current['repairs'][-1]),
        parent_file=dict(bytes=len(files[DIRECTORY+'/parent-checkpoint.json.gz']),sha256=sha(files[DIRECTORY+'/parent-checkpoint.json.gz'])),
        adopted_file=dict(bytes=len(files[DIRECTORY+'/adopted-checkpoint.json.gz']),sha256=sha(files[DIRECTORY+'/adopted-checkpoint.json.gz'])),
        input_files={name:sha(raw) for name,raw in files.items()},committed_proof_rows=784,
        committed_proof_prefix=p['committed_certificate_prefix'],financial_state_unchanged=True,financial_sessions_advanced=0,
        canonical_financial_source_changed=False,financial_root_admitted=False)
    write_exact(out/ORIGIN,encoded(value))
    validate(value,current,catalog,root,lambda name:(out/name).read_bytes(),input_hash=backtest.input_hash,
        read_checkpoint=lambda name:journal.read_checkpoint(out/name),zero_adoption=adoption,observation_seed=b''.join(rows))
    return current

def verify(root,current,catalog):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_financial_partial import root_spec
    from system_campaign_financial_resume import adoption
    root=Path(root);value=json.loads((root/ORIGIN).read_bytes())
    initial=root_spec('P07',models.plan()['root_admission_sha256'])
    raw=(root/DIRECTORY/'parent-checkpoint.json.gz').read_bytes()
    need(dict(bytes=len(raw),sha256=sha(raw))==initial['selected_file'],'P07_ABMD_VERIFY_ACTUAL_PARENT_BEFORE_OBSERVATION_READ')
    return validate(value,current,catalog,initial,
        lambda name:(root/name).read_bytes(),input_hash=backtest.input_hash,
        read_checkpoint=lambda name:journal.read_checkpoint(root/name),zero_adoption=adoption,
        observation_seed=gzip.decompress((root/DIRECTORY/'correlation-inputs.jsonl.gz').read_bytes()))

def preserve(root,out,current,catalog):
    verify(root,current,catalog);root,out=Path(root),Path(out);value=json.loads((root/ORIGIN).read_bytes())
    for name in [ORIGIN,*value['input_files']]:write_exact(out/name,(root/name).read_bytes())
