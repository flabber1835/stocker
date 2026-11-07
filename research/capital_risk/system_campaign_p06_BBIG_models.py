"""Finite genuine full11 visitor retaining all original8/9/typed10 predicates."""
import ast,json
from copy import deepcopy
from pathlib import Path
import system_campaign_p06_abmd_models as original
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_BBIG_data as data
from system_campaign_pxd_pause import adoption

MODELS_SHA='c60488d0ac9418977fc4d3082b03e9bbeee8dda85ddc1ba71e7d956d78c6affe'
PARENT='p06-BBIG-ordinary11-origin/actual-selected-parent10.json.gz'
DIRECTORY='p06-BBIG-ordinary11-adoption'
OVERLAY='p06-BBIG-source-only-ordinary11-overlay.json'
QUALIFICATION='p06-BBIG-ordinary11-input-qualification.json'
def history_tree(raw):
    data.need(data.sha(raw)==MODELS_SHA,'P06_BBIG_WHOLE_ORIGINAL_HISTORY_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='history']
    choices,=[n for n in ast.walk(fn) if isinstance(n,ast.Tuple) and ast.unparse(n)=='(8, 9, 10)']
    choices.elts.append(ast.Constant(11))
    equality,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="typed_neutral['repairs'] == cp['repairs']"]
    equality.comparators[0]=ast.parse("cp['repairs'][:10]",mode='eval').body
    hashsite,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="typed_neutral['run']['input_sha256'] == cp['run']['input_sha256']"]
    hashsite.comparators[0]=ast.parse("input_hash(typed_neutral['base'],typed_neutral['repairs'])",mode='eval').body
    fn.args.kwonlyargs += [ast.arg(arg='financial_parent'),ast.arg(arg='neutral11')]
    fn.args.kw_defaults += [ast.Constant(None),ast.Constant(None)]
    tail=ast.parse("if len(cp['repairs'])==11:\n validate_ordinary11(root,cp,catalog,financial_parent,neutral11,member,input_hash)\n").body[0]
    fn.body.insert(-1,tail)
    returned=fn.body[-1].value
    site,=[k for k in returned.keywords if k.arg=='full_inputs'];data.need(isinstance(site.value,ast.Constant) and site.value.value==10,'P06_BBIG_EXACT_OLD_TEN_RETURN')
    site.value=ast.parse("len(cp['repairs'])",mode='eval').body
    return ast.fix_missing_locations(fn)
def validate_ordinary11(root,cp,catalog,parent,neutral,member,input_hash):
    from system_campaign_financial_partial import root_spec
    from system_campaign_p06_BBIG_api import api
    data.need(parent is not None and neutral is not None,'P06_BBIG_REAL_PARENT10_AND_NEUTRAL11_REQUIRED')
    spec=root_spec('P06',data.ROOT);data.parent_contract(parent,spec)
    data.need(cp['repairs'][:10]==parent['repairs'] and cp['base']==parent['base']
        and cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']),
        'P06_BBIG_UNTRUNCATED_CURRENT11_HASH_AND_ALL_TEN_DESCRIPTORS')
    d=cp['repairs'][10];raw=member('book/repairs/'+d['filename'])
    data.need(d==dict(filename=d['sha256']+'.json',sha256=d['sha256'],resume_session='2023-06-30',
        predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256']) and data.sha(raw)==d['sha256'],
        'P06_BBIG_GENUINE_SOLE_ELEVENTH_ORDINARY_DESCRIPTOR')
    bound=api(parent,spec);import system_campaign_financial_future as future
    material_raw=member(future.hydration_name(parent));material=json.loads(material_raw)
    data.need(material['terms']==[data.catalog()['terms'][-1]] and material['parent_outer_sha256']==parent['sha256']
        and json.loads(raw)==bound.document(parent,material,data.sha(material_raw)),
        'P06_BBIG_COMPLETE_ELEVENTH_SOURCE_DOCUMENT_RECONSTRUCTION')
    adoption(neutral,parent,d['sha256'],'2023-07-27')
    data.need(neutral['repairs']==cp['repairs'] and neutral['base']==cp['base']
        and neutral['run']['input_sha256']==cp['run']['input_sha256']
        and cp['completed']>=neutral['completed'] and cp['source_cursor']>=neutral['source_cursor'],
        'P06_BBIG_ACTUAL_NEUTRAL11_FULL_HISTORY_RETAINED')
def bound_history():
    scope=dict(vars(original),validate_ordinary11=validate_ordinary11)
    exec(compile(ast.Module(body=[history_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-history-finite-real11>','exec'),scope)
    return scope['history']
def full(root,cp):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_financial_partial import root_spec
    root=Path(root);catalog=initial.catalog();original.validate(catalog,root_lookup=root_spec)
    metadata=root_spec('P06',catalog['parent_root_admission_sha256']);origin=root/original.DIRECTORY
    raw=(origin/original.PARENT).read_bytes()
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==metadata['selected_file'],'P06_BBIG_GENUINE_INITIAL8_GZIP')
    count=len(cp['repairs']);data.need(count in (8,9,10,11),'P06_BBIG_FINITE_HISTORY_ONLY')
    return bound_history()(root,cp,catalog,root_metadata=metadata,input_hash=backtest.input_hash,
        initial_parent=journal.read_checkpoint(origin/original.PARENT),ordinary_neutral=journal.read_checkpoint(origin/original.ORDINARY),
        typed_neutral=journal.read_checkpoint(origin/original.TYPED) if count>=10 else None,
        financial_parent=journal.read_checkpoint(root/PARENT) if count==11 else None,
        neutral11=journal.read_checkpoint(root/DIRECTORY/'checkpoint.json.gz') if count==11 else None)
def source_names():return (Path(__file__).name,*data.source_names())
