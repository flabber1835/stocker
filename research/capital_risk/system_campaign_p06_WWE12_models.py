"""Entire original8/9/typed10/ordinary11 visitor plus genuine WWE ordinary12."""
import ast,json
from copy import deepcopy
from pathlib import Path
import system_campaign_p06_BBIG_models as old11
import system_campaign_p06_WWE_admission as authority
import system_campaign_p06_WWE_source_asset as source_asset
import system_campaign_wwe_facts as facts
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
from system_campaign_facts import digest,sha
from full_system_benchmark import need
PARENT='p06-WWE-ordinary12-origin/actual-selected-parent11.json.gz'
DIRECTORY='p06-WWE-ordinary12-adoption'
OVERLAY='wwe-tko-overlay.json'
PRIVATE='hydrated-wwe-tko-terminal-catalog.json'
PROVENANCE='p06-WWE-ordinary12-origin'
OLD_PROOF=PROVENANCE+'/actual-old-full179-uncertainty-certificate.jsonl'
OLD11_SHA='6517c7513b1cb307cf68694b31ec248e172b9930bf1bb5ebfff8a179da280301'
def ordinary11_tree(raw):
    need(sha(raw)==OLD11_SHA,
        'P06_WWE12_WHOLE_GENUINE11_VISITOR_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_ordinary11']
    equality,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="neutral['repairs'] == cp['repairs']"]
    equality.comparators[0]=ast.parse("cp['repairs'][:11]",mode='eval').body
    hashed,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="neutral['run']['input_sha256'] == cp['run']['input_sha256']"]
    hashed.comparators[0]=ast.parse("input_hash(cp['base'],cp['repairs'][:11])",mode='eval').body
    return ast.fix_missing_locations(fn)
def history_tree():
    fn=old11.history_tree(Path(old11.original.__file__).read_bytes())
    choices,=[n for n in ast.walk(fn) if isinstance(n,ast.Tuple) and ast.unparse(n)=='(8, 9, 10, 11)'];choices.elts.append(ast.Constant(12))
    test,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="len(cp['repairs']) == 11"]
    test.ops=[ast.In()];test.comparators=[ast.Tuple(elts=[ast.Constant(11),ast.Constant(12)],ctx=ast.Load())]
    fn.args.kwonlyargs += [ast.arg(arg='actual_parent11'),ast.arg(arg='neutral12')];fn.args.kw_defaults += [ast.Constant(None),ast.Constant(None)]
    fn.body.insert(-1,ast.parse("if len(cp['repairs'])==12:\n validate_WWE12(root,cp,actual_parent11,neutral12,member,input_hash)\n").body[0])
    return ast.fix_missing_locations(fn)
def bound_history():
    namespace=dict(vars(old11));exec(compile(ast.Module(body=[ordinary11_tree(Path(old11.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-genuine11-history-retained-in-full12>','exec'),namespace)
    scope=dict(vars(old11.original),validate_ordinary11=namespace['validate_ordinary11'],validate_WWE12=validate_WWE12)
    exec(compile(ast.Module(body=[history_tree()],type_ignores=[]),'<whole-original-full8-9-typed10-11-plus-WWE12-history>','exec'),scope)
    return scope['history']
def material(member):
    catalog=facts.validate(json.loads((Path(facts.__file__).parent/facts.CATALOG).read_bytes()));term,=catalog['terms']
    raw=member(PRIVATE);value=json.loads(raw)
    need(value['catalog']==catalog and len(value['effective_terms'])==1 and value['actual_alias_rows']==3
        and value['source_metadata_unchanged'] is value['not_actual_issuer_settlement'] is True
        and value['cil_convention']==catalog['cil_convention'],'P06_WWE12_ENTIRE_UNCHANGED_ORIGINAL_PRIVATE_STOCK_PAYLOAD')
    facts.stock.require_provider_rows(value['provider_rows']['WWE'],term)
    rows={(r['session'],r['security_id']):r for r in value['source_witnesses']}
    need(len(rows)==len(value['source_witnesses'])==2,'P06_WWE12_EXACT_TWO_FULL_SOURCE_DELIVERY_WITNESSES')
    for witness in (term['identity_witness'],term['delivered_identity_witness']):facts.stock.require_witness(rows[witness['session'],witness['security_id']],witness)
    added=deepcopy(term['added']);added['cash_in_lieu_price_per_delivered_share']=float(rows[facts.DAY,facts.DELIVERED]['raw_open'])
    need(value['effective_terms']==[added] and added['cash_in_lieu_price_per_delivered_share']==102.,
        'P06_WWE12_ORIGINAL_EFFECTIVE_CONVERSION_AND_FROZEN_RAW_OPEN_CIL_PROXY')
    return catalog,raw,added
def document(parent,member):
    catalog,private,added=material(member);group=catalog['commitment_group']
    refs={'catalog':sha((Path(facts.__file__).parent/facts.CATALOG).read_bytes()),'loader':sha(Path(facts.stock.__file__).read_bytes()),'private':sha(private)}
    evidence=[dict(reference=group['reference_stem']+k,sha256=v,description='Primary stock/mixed consideration, unchanged compiler and full frozen private witnesses; raw-open CIL proxy.') for k,v in refs.items()]
    for term in catalog['terms']:
        evidence.extend(dict(reference=term[k],sha256=None,description=term['description']) for k in ('primary_source','timing_source'))
    term,=catalog['terms']
    return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],source_evidence=evidence,
        suppress=[dict(session=term['native_session'],security_id=term['security_id'],term_sha256=term['native_term_sha256'])],add=[added])
def validate_WWE12(root,current,parent,neutral,member,input_hash):
    spec=authority.fact()['root_spec'];authority.parent(parent,spec)
    need(parent is not None and neutral is not None and current['base']==parent['base'] and current['repairs'][:11]==parent['repairs']
        and len(current['repairs'])==12 and current['run']['input_sha256']==input_hash(current['base'],current['repairs']),
        'P06_WWE12_COMPLETE_CURRENT12_HASH_ALL_REAL_PARENT11_DESCRIPTORS')
    descriptor=current['repairs'][11];raw=member('book/repairs/'+descriptor['filename'])
    need(descriptor==dict(filename=descriptor['sha256']+'.json',sha256=descriptor['sha256'],resume_session='2023-08-31',
        predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256']) and sha(raw)==descriptor['sha256']
        and json.loads(raw)==document(parent,member) and member(OVERLAY)==raw,'P06_WWE12_GENUINE_SOLE_NEW_ORDINARY_STOCK_DOCUMENT_RECONSTRUCTION')
    adoption(neutral,parent,sha(raw),'2023-09-11')
    need(neutral['repairs']==current['repairs'] and neutral['run']['input_sha256']==current['run']['input_sha256']
        and current['completed']>=neutral['completed'] and current['source_cursor']>=neutral['source_cursor'],
        'P06_WWE12_ACTUAL_ZERO_SESSION_NEUTRAL12_RETAINED_IN_CURRENT_HISTORY')
def full(root,current):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_financial_partial import root_spec
    root=Path(root);old=old11.original;catalog=old11.initial.catalog();count=len(current['repairs'])
    need(count in (11,12),'P06_WWE12_ONLY_COMPLETE_ACTUAL_FULL11_OR_GENUINE12')
    if count==11:return old11.full(root,current)
    return bound_history()(root,current,catalog,root_metadata=root_spec('P06',catalog['parent_root_admission_sha256']),input_hash=backtest.input_hash,
        initial_parent=journal.read_checkpoint(root/old.DIRECTORY/old.PARENT),ordinary_neutral=journal.read_checkpoint(root/old.DIRECTORY/old.ORDINARY),
        typed_neutral=journal.read_checkpoint(root/old.DIRECTORY/old.TYPED),financial_parent=journal.read_checkpoint(root/old11.PARENT),
        neutral11=journal.read_checkpoint(root/old11.DIRECTORY/'checkpoint.json.gz'),actual_parent11=journal.read_checkpoint(root/PARENT),
        neutral12=journal.read_checkpoint(root/DIRECTORY/'checkpoint.json.gz'))
def source_names():return (Path(__file__).name,*authority.source_names(),*old11.source_names())
