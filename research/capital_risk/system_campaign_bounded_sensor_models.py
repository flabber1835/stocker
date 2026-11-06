"""Full checkpoint typed visitor; original B19 guard body remains authoritative."""
import ast
from copy import deepcopy
import json
from pathlib import Path

from system_campaign_bounded_sensor_input import SCHEMA, parse, need, digest, sha

BRANCH_SHA='b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'


def typed_descriptor(root,cp,catalog,expected_evidence,*,input_hash,root_metadata):
    """Check the actual full list/hash, then parse only the declared new schema."""
    prefix=catalog['parent_descriptors']
    need(cp['base']==root_metadata['base'] and cp['repairs'][:len(prefix)]==prefix
         and len(cp['repairs']) in (len(prefix),len(prefix)+1), 'MODELS_EXACT_FULL_PARENT_PREFIX_AND_ONE_SUFFIX')
    need(cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']), 'MODELS_FULL_CANONICAL_INPUT_HASH')
    if len(cp['repairs'])==len(prefix):
        need((cp['sha256'],cp['source_cursor'],cp['completed'])==
             (catalog['parent_outer_sha256'],catalog['parent_cursor'],catalog['parent_completed']),
             'MODELS_UNADOPTED_EXACT_CURRENT_PARENT')
        return None
    d=cp['repairs'][-1]
    need(d['filename']==d['sha256']+'.json' and Path(d['filename']).name==d['filename']
         and d['resume_session']==catalog['parent_cursor']
         and d['predecessor_checkpoint_sha256']==catalog['parent_inner_sha256'],
         'MODELS_EXACT_SAFE_NEW_DESCRIPTOR_AND_OWN_PREDECESSOR')
    path=Path(root)/'book/repairs'/d['filename']
    raw=path.read_bytes();need(sha(raw)==d['sha256'], 'MODELS_EXACT_NEW_INPUT_BYTES')
    obj=parse(path,resume_session=d['resume_session'],
        predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'],
        expected_event=catalog['event'],expected_evidence=expected_evidence)
    need(obj.sha256==d['sha256'] and obj.event.model_dump()==catalog['event'],
         'MODELS_ONLY_EXACT_VALIDATED_BOUNDED_INPUT')
    return deepcopy(d)


def visitor_tree(raw):
    need(sha(raw)==BRANCH_SHA,'MODELS_UNCHANGED_ORIGINAL_B19_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_input']
    loop,=[n for n in fn.body if isinstance(n,ast.For)]
    site,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='schema']
    skip=ast.parse("if schema==BOUNDED_SCHEMA:\n need(descriptor==validated_descriptor and validated_descriptor is not None,'MODELS_ONLY_INDEPENDENTLY_PARSED_NEW_DESCRIPTOR')\n continue").body[0]
    loop.body.insert(site+1,skip)
    return ast.fix_missing_locations(fn)


def validate_full(root,cp,catalog,expected_evidence):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest
    import system_campaign_financial_branches as original
    from system_campaign_financial_partial import root_spec
    selected=typed_descriptor(root,cp,catalog,expected_evidence,input_hash=backtest.input_hash,
        root_metadata=root_spec(catalog['arm'],catalog['parent_root_admission_sha256']))
    raw=Path(original.__file__).read_bytes();fn=visitor_tree(raw)
    namespace=dict(vars(original),BOUNDED_SCHEMA=SCHEMA,validated_descriptor=selected)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-B19-visitor-one-independently-parsed-bounded-input>','exec'),namespace)
    expected=catalog['parent_descriptors'][-1]['sha256']
    need(namespace['validate_input'](Path(root),cp)==expected, 'MODELS_EXACT_ORIGINAL_BRANCH_DESCRIPTOR')
    return selected
