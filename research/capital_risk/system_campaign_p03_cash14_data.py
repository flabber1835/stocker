"""Exact admitted524/full17 and retained factual generations for fourteen cash terms."""
import ast,gzip,importlib,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
from system_campaign_bounded_sensor_input import need,sha,digest
import system_campaign_financial_future as future
import system_campaign_qualified_cash_batch as cash
import system_campaign_qualified_cash_subset as subset
import system_campaign_p03_thor_data as old
HERE=Path(__file__).parent
ROOT='bff8b5f2dea2bba80ed2da03053e95246cce401db749c4a0d4f54302cd5f2877'
OUTER='7b1a0140089732de1dc6c77a4d4cc996f79883be3d5b721c30cf9b41d85cac5b'
FACT='P03-own524-14cash18-finite-facts.json'
FACT_SHA='6fb9e2b93c2fbe864a26701efb3c84732c2e19eb08f284710080245d520b4b6a'
PRIMARY='P03-DERM2-preopen-common-cash-fact.json'
CATALOG='P03-own524-DERM2-and13-ordinary18-catalog.json'
SID='739966891811158555'
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def facts():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'P03_14_EXACT_FINITE_ACTUAL524_FACTS')
    value=json.loads(raw)
    for n,p in value['source_files'].items():
        raw=(HERE/n).read_bytes();need(dict(bytes=len(raw),sha256=sha(raw))==p,'P03_14_COMPLETE_NEW_FACT_ASSET:'+n)
    base=Path(future.__file__).parent
    for n,pin in value['frozen_sources'].items():need(sha((base/n).read_bytes())==pin,'P03_14_WHOLE_FROZEN_SOURCE:'+n)
    return value
def parent_contract(cp,spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);value=facts();run=cp['run']
    need({k:v for k,v in spec.items() if k!='root_admission'}==value['parent_transport']
        and spec['root_admission_sha256']==ROOT and spec['root_admission']['branch_uncertainty_proof']==value['branch_proof']
        and (cp['sha256'],cp['completed'],cp['source_cursor'],len(cp['repairs']))==(OUTER,524,'2020-01-31',17)
        and cp['sha256']==spec['outer_sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
        and cp['base']==spec['base'] and cp['repairs']==spec['repairs']
        and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
        and run['state_sha256']==spec['state_sha256']==digest(run['state'])
        and run['input_sha256']==spec['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))
        and run['state']['last_processed_session']==cp['source_cursor'],'P03_14_ONLY_ACTUAL_ADMITTED524_FULL17_ALL_COMMITMENTS')
    proof=value['branch_proof'];need(proof['passed'] is proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True
        and (proof['rows'],proof['retained_rows'])==(21,49) and proof['hosted_canonical_transition_oracle_sha256']=='ae2ac28a64c3f39f179a3c2ff1968be3a5e05d09da9b992413e6b6a015356abb',
        'P03_14_EXACT_REAL70_ADMITTED_PROOF_AND_HOSTED_ORACLE')
    roles=json.loads((HERE/'P03-own524-14cash-role-and-DERM-boundary-DATA.json').read_bytes());actual=roles['actual_checkpoint']
    need(roles['passed'] is True and roles['old503_roles_reused'] is roles['later_state_roles_inferred'] is False
        and actual['outer_sha256']==cp['sha256'] and actual['state_sha256']==run['state_sha256'] and actual['input_sha256']==run['input_sha256']
        and set(roles['actual524_candidate_roles'])=={SID,*[c['security_id'] for c in value['candidates']]}
        and all(not refs for r in roles['actual524_candidate_roles'].values() for refs in r['current_financial_role_references'].values())
        and all(r['future_holding_or_ordered_role_inferred'] is False for r in roles['actual524_candidate_roles'].values()),
        'P03_14_ACTUAL524_CURRENT_ROLE_PROOF_SEPARATE_FROM_OLD503_AND_FUTURE_ROLES')
    return value
def source(label):
    need(label in ('SOURCE327','SOURCE334'),'P03_14_TRUE_SEPARATE_SOURCE_NAMESPACES')
    value=json.loads((HERE/('P03-retained-'+label+'-full-factual-generation.json')).read_bytes())
    module=importlib.import_module('system_campaign_p03_forward_source_queries'+('_batch2' if label=='SOURCE334' else ''))
    def scope(pin):
        query,=module.registry().queries;result=query.scope.model_dump()
        need(query.root_admission_sha256==old.ROOT and query.parent_completed==503 and query.parent_input_count==16
            and result==value['payload']['scope'] and digest(result)==pin,'P03_14_EXACT_OLD503_CLOSED_SCOPE_NOT_CURRENT_ROLE')
        return result
    fn=old.source_tree(Path(cash.__file__).read_bytes());namespace=dict(vars(cash),registered_scope=scope)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-cash-source-binding-true-retained-generation>','exec'),namespace)
    view=dict(arm='P03',parent_root_admission_sha256=old.ROOT,parent_outer_sha256=old.OUTER,parent_cursor='2019-12-31',source_data=value)
    result=namespace['source_binding'](view)
    expected='aa802805042661ea6750915c947918cd0622b9364009a579fbcc889ea2381de1' if label=='SOURCE327' else '4499c4f362cad601153a013712e852aece5243087c6ae34257d2d3559917ff89'
    need(sha(encoded(result[2]))==expected,'P03_14_EXACT_INDEPENDENT_COMPLETE_SOURCE_QUALIFICATION:'+label)
    return value
def primary_catalog():
    value=json.loads((HERE/'P03-DERM2-retained503-source-subset-template.json').read_bytes());value['loader_sha256']=sha(Path(__file__).read_bytes())
    need(value['source_data']==source('SOURCE327'),'P03_14_PRIMARY_OLD_SOURCE_GENERATION_UNALTERED')
    return value
def validate_primary(value):
    fn=subset.validator();bound=FunctionType(fn.__code__,dict(fn.__globals__,__file__=__file__,source_binding=old.source_binding),fn.__name__,fn.__defaults__)
    need(bound.__code__ is fn.__code__,'P03_14_WHOLE_ORIGINAL_PRIMARY_CASH_VALIDATOR_CODE')
    bound(value);term,=value['terms'];p=json.loads((HERE/PRIMARY).read_bytes());row=source('SOURCE327')['payload']['terms'][17]
    need(value['selected_source_indices']==[17] and value['retained_source_indices']==[] and value['parent_root_admission_sha256']==old.ROOT
        and term['security_id']==SID and term['native']==row['native_term'] and term['identity_witness']==row['identity_witness']
        and term['native_session']==term['last_trading_session']=='2020-02-19' and term['added']['session']==term['actual_completion_date']=='2020-02-20'
        and term['added']['cash_per_share']==18.75 and p['cash_per_share']=='18.75' and p['currency']=='USD'
        and p['preopen_completion_confirmed'] is True and p['stock_or_contingent_common_components']==[]
        and term['primary_extraction']['qualified_preopen_fact_sha256']==sha((HERE/PRIMARY).read_bytes()),'P03_14_EXACT_DERM_COMMON_CASH_SEPARATE_NATIVE_AND_PREOPEN_CLOCK')
    return True
class PrimaryCash:
    def __init__(self,value):
        init=cash.QualifiedCashBatch.__init__
        FunctionType(init.__code__,dict(init.__globals__,validate=validate_primary),init.__name__,init.__defaults__)(self,value)
        self.catalog_sha=sha(encoded(value));self.compiler_sha=sha(Path(__file__).read_bytes())
def components():
    value=facts();grouped={}
    for c in value['candidates']:grouped.setdefault(c['original_file'],[]).append(c['ticker'])
    result=[]
    for filename,tickers in grouped.items():
        p=value['original_catalogs'][filename]
        literal=json.loads((Path(future.__file__).parent/filename).read_bytes())
        tickers=[t['ticker'] for t in literal['terms'] if t['ticker'] in tickers]
        result.append((p['validator_file'][:-3],p['constructor'],p['argument_kind'],filename,p['catalog_sha256'],p['validator_sha256'],tuple(tickers)))
    need(len(result)==4,'P03_14_FOUR_ORIGINAL_INTERLEAVING_CATALOGS')
    return tuple(result)
def supplemental():
    fn=future.supplemental_selection
    phases=dict(future.SUPPLEMENTAL_PHASES);need(('P03','2020-01-31') not in phases,'P03_14_NO_ORIGINAL_PHASE_REPLACEMENT')
    phases['P03','2020-01-31']=components()
    bound=FunctionType(fn.__code__,dict(fn.__globals__,SUPPLEMENTAL_PHASES=phases),fn.__name__,fn.__defaults__)
    need(bound.__code__ is fn.__code__,'P03_14_WHOLE_ORIGINAL_SUPPLEMENTAL_SELECTOR_CODE')
    terms,sources=bound('P03','2020-01-31');need(len(terms)==13 and len(sources)==4,'P03_14_EXACT_THIRTEEN_ORIGINAL_SUPPLEMENTAL_TERMS')
    s=source('SOURCE334')
    for t in terms:
        c,=[c for c in facts()['candidates'] if c['security_id']==t['security_id']]
        original=deepcopy(t);original.pop('original_ordinary_source');original.pop('timing_source',None)
        # timing_source may have been an original field. Verify by the immutable
        # catalog term itself, preserving every original economic field.
        catalog=json.loads((Path(future.__file__).parent/c['original_file']).read_bytes());prior=catalog
        for key in c['original_path'].split('/')[1:]:prior=prior[int(key)] if isinstance(prior,list) else prior[key]
        row=s['payload']['terms'][c['source334_index']]
        need(digest(prior)==c['original_term_sha256'] and all(t[k]==v for k,v in prior.items()) and t['identity_witness']==row['identity_witness']
            and t['native_term_sha256']==digest(row['native_term']) and t['added']['kind']=='CASH_MERGER','P03_14_ALL_ORIGINAL_ECONOMIC_IDENTITY_ALIAS_AND_SOURCE_FIELDS')
    return terms,sources
def terms():
    p=primary_catalog();PrimaryCash(p);primary=deepcopy(p['terms']);extra,_=supplemental();result=future.merge_selected_terms(primary,extra)
    need(len(result)==14 and len({t['security_id'] for t in result})==14,'P03_14_EXACT_COMPLETE_UNIQUE_CASH_BATCH')
    generations={label:source(label) for label in ('SOURCE327','SOURCE334')}
    for term in result:
        label='SOURCE327' if term['security_id']==SID else 'SOURCE334';generation=generations[label];review,q=generation['review'],generation['qualification']
        original_sha=term.get('original_ordinary_source',{}).get('term_sha256',digest(term))
        capture=dict(run_id=review['run_id'],head=review['head'],artifact_id=review['artifact_id'],payload_sha256=review['payload_sha256'],scope_sha256=review['scope_sha256'],
            independent_data_review_sha256=sha(encoded(review)),independent_qualification_sha256=sha(encoded(q)))
        if 'source_capture' in term:need(term['source_capture']==capture,'P03_14_ORIGINAL_PRIMARY_CAPTURE_UNCHANGED')
        term['source_capture']=capture
        term['retained_qualified_source']=dict(schema='research.P03-retained-original-source-generation-only/1',source_arm='P03',source_label=label,
            original_parent_root_admission_sha256=old.ROOT,original_parent_outer_sha256=old.OUTER,original_term_sha256=original_sha,
            originating_book_authority_retained=False,current_root_admission_sha256=ROOT,current_role_basis='SEPARATE_ACTUAL524_FULL_STATE_CONTRACT',
            future_ownership_inferred=False)
    return result
def catalog():
    value=facts();return dict(schema='research.P03-own524-retained-factual14-ordinary18-catalog/1',arm='P03',
        current_root_admission_sha256=ROOT,current_parent_outer_sha256=OUTER,current_cursor='2020-01-31',current_inputs=17,
        retained_old_source_generations_are_financial_seeds=False,old503_roles_are_current524_roles=False,
        primary_catalog=primary_catalog(),supplemental_components=components(),terms=terms(),
        primary_fact_sha256=value['source_files'][PRIMARY]['sha256'],actual524_role_DATA_sha256=value['source_files']['P03-own524-14cash-role-and-DERM-boundary-DATA.json']['sha256'],
        financial_source_changed=False,provider_metadata_upgraded=False)
def primary_fact():return json.loads((HERE/PRIMARY).read_bytes())
def codec(parent,spec):
    parent_contract(parent,spec);value=catalog();return SimpleNamespace(catalog=value,catalog_sha=sha(encoded(value)),compiler_sha=sha(Path(__file__).read_bytes()),validator_description='Whole original primary cash subset plus four original catalog constructors; retained factual source generations do not grant current or future roles.')
def completion_session(term,dates):
    future.completion_session(term,dates)
    if term['security_id']!=SID:return
    need(dates==sorted(set(dates)) and dates[dates.index('2020-02-19')+1]=='2020-02-20'
        and term['native_session']==term['last_trading_session']=='2020-02-19' and term['added']['session']=='2020-02-20','P03_14_DERM_EXACT_NEXT_FROZEN_SESSION_NO_EARLY_CASH')
def source_names():
    value=facts();return tuple(sorted({Path(__file__).name,FACT,CATALOG,*value['source_files'],*[n for file,p in value['original_catalogs'].items() for n in (file,p['validator_file'])]}))
