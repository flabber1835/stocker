"""Full current input visitor, retaining the genuine neutral origin separately."""
import ast,json
from pathlib import Path
from copy import deepcopy
from system_campaign_bounded_sensor_input import SCHEMA,parse,need,sha,digest
import system_campaign_bounded_sensor_models as original

TYPED_SHA='55e9eef76c3a0c837b6a1ad8a526879de9789f89319e15f82036ccd681882195'

def descriptor(root,cp,catalog,expected_evidence,*,input_hash,root_metadata):
    prefix=catalog['parent_descriptors'];need(len(prefix)==15,'BOUNDED_FULL_ORIGINAL15_BOUNDARY')
    need(cp['base']==root_metadata['base'] and cp['repairs'][:15]==prefix and len(cp['repairs'])>=15
         and cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']),
         'BOUNDED_FULL_CURRENT_UNTRUNCATED_HISTORY_AND_INPUT_HASH')
    if len(cp['repairs'])==15:
        need((cp['sha256'],cp['completed'],cp['source_cursor'])==
             (catalog['parent_outer_sha256'],462,'2019-10-31'),'BOUNDED_FULL_ONLY_EXACT_UNADOPTED_INITIAL_PARENT')
        return None
    d=cp['repairs'][15]
    need(d==dict(filename=TYPED_SHA+'.json',sha256=TYPED_SHA,resume_session=catalog['parent_cursor'],
        predecessor_checkpoint_sha256=catalog['parent_inner_sha256']), 'BOUNDED_FULL_EXACT_TYPED16_DESCRIPTOR')
    obj=parse(Path(root)/'book/repairs'/d['filename'],resume_session=d['resume_session'],
        predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'],expected_event=catalog['event'],expected_evidence=expected_evidence)
    need(obj.sha256==TYPED_SHA,'BOUNDED_FULL_EXACT_PARSED_TYPED16_BYTES')
    for entry in cp['repairs'][16:]:
        need(entry['filename']==entry['sha256']+'.json' and Path(entry['filename']).name==entry['filename'],
             'BOUNDED_FULL_SAFE_ORDINARY_TAIL_FILENAME')
        raw=(Path(root)/'book/repairs'/entry['filename']).read_bytes()
        need(sha(raw)==entry['sha256'] and json.loads(raw)['schema']=='terminal-repair/1',
             'BOUNDED_FULL_EVERY_ORDINARY_TAIL_INPUT_BYTES_AND_SCHEMA')
    return deepcopy(d)

def validate_full(root,cp,catalog,expected_evidence,*,root_metadata):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest
    import system_campaign_financial_branches as branch
    selected=descriptor(root,cp,catalog,expected_evidence,input_hash=backtest.input_hash,root_metadata=root_metadata)
    fn=original.visitor_tree(Path(branch.__file__).read_bytes())
    namespace=dict(vars(branch),BOUNDED_SCHEMA=SCHEMA,validated_descriptor=selected)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-B19-full-current-input-visitor>','exec'),namespace)
    need(namespace['validate_input'](Path(root),cp)==catalog['parent_descriptors'][-1]['sha256'],
         'BOUNDED_FULL_ORIGINAL_BRANCH_MODEL_IDENTITY_RETAINED')
    return selected
