"""Complete P06 eight/ordinary-nine/bounded-ten input history; never a truncated book."""
from copy import deepcopy
import gzip,json
from pathlib import Path
import system_campaign_financial_future as ordinary
from system_campaign_bounded_sensor_input import need,sha,digest,parse
from system_campaign_abmd_bounded_catalog import evidence,document,validate
from system_campaign_pxd_pause import adoption

HERE=Path(__file__).parent
DIRECTORY='abmd-initial-origin'
PARENT='initial-parent-checkpoint.json.gz'
ORDINARY='ordinary-neutral-checkpoint.json.gz'
TYPED='typed-neutral-checkpoint.json.gz'
FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'

def ordinary_material(root,parent,descriptor,member):
    need(sha(Path(ordinary.__file__).read_bytes())==FUTURE_SHA,'P06_MODELS_ENTIRE_ORIGINAL_ORDINARY_COMPILER')
    codec,name,terms=ordinary.selected('P06',cursor='2022-11-30')
    need(len(terms)==1 and terms[0]['ticker']=='TRQ' and terms[0]['added']['cash_per_share']==31.575855485386988,
         'P06_MODELS_EXACT_EXISTING_TRQ_NORMALIZATION')
    raw=member(ordinary.hydration_name(parent));material=json.loads(raw)
    need(material['schema']==ordinary.REFERENCE and material['arm']=='P06' and material['catalog']==name
         and material['catalog_sha256']==codec.catalog_sha and material['original_validator_sha256']==codec.compiler_sha
         and material['selector_sha256']==FUTURE_SHA and material['terms']==terms
         and material['parent_outer_sha256']==parent['sha256'] and material['consumed_native_preserved']==[]
         and material['financial_source_changed'] is material['provider_metadata_upgraded'] is False,
         'P06_MODELS_WHOLE_ORIGINAL_TRQ_INPUT_MATERIAL')
    overlay=member('book/repairs/'+descriptor['filename'])
    need(sha(overlay)==descriptor['sha256'] and json.loads(overlay)==ordinary.document(parent,material,sha(raw)),
         'P06_MODELS_ENTIRE_ORIGINAL_ORDINARY_DOCUMENT_RECONSTRUCTION')
    return json.loads(overlay),material

def history(root,cp,catalog,*,root_metadata,input_hash,initial_parent=None,ordinary_neutral=None,typed_neutral=None,member=None):
    root=Path(root);member=(lambda name:(root/name).read_bytes()) if member is None else member
    prefix=root_metadata['repairs']
    need(catalog['arm']=='P06' and len(prefix)==8 and cp['base']==root_metadata['base']
         and cp['repairs'][:8]==prefix and len(cp['repairs']) in (8,9,10)
         and cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']),
         'P06_MODELS_FULL_ACTUAL_EIGHT_PREFIX_AND_CANONICAL_HASH')
    for descriptor in cp['repairs'][:8]:
        raw=member('book/repairs/'+descriptor['filename'])
        need(descriptor['filename']==descriptor['sha256']+'.json' and sha(raw)==descriptor['sha256']
             and json.loads(raw)['schema']=='terminal-repair/1','P06_MODELS_ALL_EIGHT_ORIGINAL_ORDINARY_FILES')
    if len(cp['repairs'])==8:
        need((cp['sha256'],cp['source_cursor'],cp['completed'])==
             (catalog['parent_outer_sha256'],catalog['parent_cursor'],catalog['parent_completed']),
             'P06_MODELS_EXACT_UNADOPTED_OWN1238')
        return dict(ordinary_descriptor=None,bounded_descriptor=None,full_inputs=8)
    need(initial_parent is not None and ordinary_neutral is not None
         and initial_parent['sha256']==catalog['parent_outer_sha256']==root_metadata['outer_sha256']
         and initial_parent['repairs']==prefix and initial_parent['run']['checkpoint_sha256']==catalog['parent_inner_sha256'],
         'P06_MODELS_ACTUAL_ORIGINAL_AND_ORDINARY_NEUTRAL_PARENTS_REQUIRED')
    d=cp['repairs'][8]
    need(d==dict(filename=d['sha256']+'.json',sha256=d['sha256'],resume_session='2022-11-30',
                 predecessor_checkpoint_sha256=initial_parent['run']['checkpoint_sha256']),
         'P06_MODELS_EXACT_NINTH_ORDINARY_DESCRIPTOR')
    doc,material=ordinary_material(root,initial_parent,d,member)
    adoption(ordinary_neutral,initial_parent,d['sha256'],min(t['session'] for field in ('add','suppress') for t in doc[field]))
    need(ordinary_neutral['repairs']==cp['repairs'][:9], 'P06_MODELS_FULL_ACTUAL_ORDINARY_NEUTRAL_HISTORY')
    if len(cp['repairs'])==9:
        need(cp==ordinary_neutral,'P06_MODELS_NINTH_IS_ONLY_ZERO_SESSION_NEUTRAL_BOUNDARY')
        return dict(ordinary_descriptor=deepcopy(d),bounded_descriptor=None,full_inputs=9)
    need(typed_neutral is not None,'P06_MODELS_ACTUAL_TENTH_NEUTRAL_PARENT_REQUIRED')
    typed=cp['repairs'][9];path=root/'book/repairs'/typed['filename'];raw=member('book/repairs/'+typed['filename'])
    need(typed==dict(filename=typed['sha256']+'.json',sha256=typed['sha256'],resume_session='2022-11-30',
              predecessor_checkpoint_sha256=ordinary_neutral['run']['checkpoint_sha256'])
         and sha(raw)==typed['sha256'] and json.loads(raw)==document(catalog,
              predecessor_checkpoint_sha256=ordinary_neutral['run']['checkpoint_sha256']),
         'P06_MODELS_EXACT_TENTH_TYPED_INPUT_AND_ACTUAL_NINTH_PREDECESSOR')
    loaded=parse(path,resume_session='2022-11-30',predecessor_checkpoint_sha256=ordinary_neutral['run']['checkpoint_sha256'],
                 expected_event=catalog['event'],expected_evidence=evidence(catalog))
    need(loaded.sha256==typed['sha256'],'P06_MODELS_INDEPENDENT_EXACT_TYPED_PARSER')
    adoption(typed_neutral,ordinary_neutral,typed['sha256'],catalog['event']['native_session'])
    need(typed_neutral['repairs']==cp['repairs'] and typed_neutral['base']==cp['base']
         and typed_neutral['run']['input_sha256']==cp['run']['input_sha256']
         and cp['source_cursor']>=typed_neutral['source_cursor'] and cp['completed']>=typed_neutral['completed'],
         'P06_MODELS_FULL_TEN_HISTORY_RETAINED_AFTER_REAL_ADOPTION')
    return dict(ordinary_descriptor=deepcopy(d),bounded_descriptor=deepcopy(typed),full_inputs=10)

def validate_full(root,cp,catalog):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_financial_partial import root_spec
    metadata=root_spec('P06',catalog['parent_root_admission_sha256'])
    validate(catalog,root_lookup=root_spec)
    if len(cp['repairs'])==8:return history(root,cp,catalog,root_metadata=metadata,input_hash=backtest.input_hash)
    root=Path(root);origin=root/DIRECTORY;raw=(origin/PARENT).read_bytes()
    need(dict(bytes=len(raw),sha256=sha(raw))==metadata['selected_file'],'P06_MODELS_EXACT_AUTHENTIC_INITIAL_GZIP_BEFORE_PARSE')
    initial=journal.read_checkpoint(origin/PARENT);ninth=journal.read_checkpoint(origin/ORDINARY)
    tenth=journal.read_checkpoint(origin/TYPED) if len(cp['repairs'])==10 else None
    return history(root,cp,catalog,root_metadata=metadata,input_hash=backtest.input_hash,
                   initial_parent=initial,ordinary_neutral=ninth,typed_neutral=tenth)
