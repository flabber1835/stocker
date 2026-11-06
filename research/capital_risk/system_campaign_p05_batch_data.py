"""Exact SOURCE322 generation and original65 cash contracts plus qualified ACC."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_qualified_cash_batch as original
import system_campaign_qualified_cash_subset as subset
import system_campaign_p05_acc_next as acc

HERE=Path(__file__).parent
ROOT='e50bb7bb725c4636ad882b8b36b69aa1de9b7decc90fc611aa922f27b3e602c6'
OUTER='69f529dc4a2b6790257068be6cf75455b9aaa87264cdd2d536120145a6afd399'
SCOPE='6bca61ce8a03a51382d82db768e549e4d692d47aab253bf916825d395530fbd6'
SUPPORTED='system-campaign-p05-own1070-supported-cash-inputs.json'
SUPPORTED_SHA='0215ae4293365f6327dfd38dce0493b05b67cb7cb400ff494876d835df61fb77'
PINS={'P05-batch-source-payload.json':'d6625a14a9476ddc0df9e86c302d911cfcd9a7d998ececb47177ae1c9a33e150',
      'P05-batch-source-review.json':'f2668ab9da00bd0f041a89a339125be0acd885f00c81c2c08b26a2ed4baa0cd2',
      'P05-batch-source-qualification-v2.json':'6efd1c0bcd083bc313a1ed2c7a05537be54ddb39a9fa13d72fa115237d874857'}
BASE_SHA='96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
SUBSET_SHA='e0f7f8599032d6927a9fb84f156bcb60c8c0162b7abd37a47db5bdd1a7ae7ea2'
FRESH=frozenset(('arm','parent_cursor','parent_outer_sha256','parent_root_admission_sha256',
                 'parent_positions','identity_witness','native','source_capture'))
need,sha,digest,encoded=original.need,original.sha,original.digest,original.encoded

def records():
    values=[]
    for name,pin in PINS.items():
        raw=(HERE/name).read_bytes();need(sha(raw)==pin,'P05_BATCH_EXACT_WHOLE_SOURCE322_BYTES');values.append(json.loads(raw))
    payload,review,q=values
    need(payload['scope_sha256']==SCOPE==digest(payload['scope']) and len(payload['terms'])==len(payload['scope']['terms'])==102
         and q['root_admission_sha256']==ROOT and q['payload_sha256']==PINS['P05-batch-source-payload.json']
         and q['scope_sha256']==SCOPE and q['review_sha256']==PINS['P05-batch-source-review.json']
         and q['schema']=='research.independent-forward-source-DATA-validation/2'
         and q['old_financial_rows_reaudited']==0 and type(q['old_financial_rows_reaudited']) is int,
         'P05_BATCH_EXACT_NEW_SOURCE_GENERATION_AND_FULL_SCOPE')
    return payload,review,q

def registered_scope(pin):
    need(pin==SCOPE,'P05_BATCH_ONLY_EXACT_NEW_REGISTERED_SCOPE')
    return deepcopy(records()[0]['scope'])

def source_tree(raw):
    need(sha(raw)==BASE_SHA,'P05_BATCH_WHOLE_ORIGINAL_CASH_VALIDATOR')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding')
    statement=next(n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future')
    need([a.name for a in statement.names]==['registered_scope'],'P05_BATCH_ONE_ORIGINAL_SCOPE_IMPORT')
    statement.module='system_campaign_p05_batch_data'
    literals=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='research.independent-frozen-source-data-validation/1']
    need(len(literals)==1,'P05_BATCH_ONE_QUALIFICATION_SCHEMA_SITE')
    literals[0].value='research.independent-forward-source-DATA-validation/2'
    return ast.fix_missing_locations(fn)

def source_binding(catalog):
    payload,review,q=records()
    need(catalog['source_data']==dict(payload=payload,review=review,qualification=q),
         'P05_BATCH_CATALOG_BINDS_FULL_SOURCE_GENERATION_NOT_PROJECTION')
    fn=source_tree(Path(original.__file__).read_bytes());scope=dict(vars(original))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-cash-source-binding-one-new-generation>','exec'),scope)
    return scope['source_binding'](catalog)

def validator_tree(raw):
    need(sha(raw)==BASE_SHA and sha(Path(subset.__file__).read_bytes())==SUBSET_SHA,'P05_BATCH_ORIGINAL_BASE_AND_SUBSET_VALIDATORS')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
    site=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='(terms, captured, declared)')
    fn.body.insert(site+1,ast.parse('captured, declared, checked_members = selected_members(catalog, payload, review)').body[0])
    class Members(ast.NodeTransformer):
        count=0
        def visit_Subscript(self,node):
            if ast.unparse(node)=="review['terms']":self.count+=1;return ast.copy_location(ast.Name(id='checked_members',ctx=ast.Load()),node)
            return self.generic_visit(node)
    adapter=Members();fn=adapter.visit(fn);need(adapter.count==2,'P05_BATCH_EXACT_ORIGINAL_SUBSET_REVIEW_BINDINGS')
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    policy=next(n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=="term['recognition_rule'] == RESEARCH_CASH")
    old=deepcopy(policy.orelse);branch=ast.parse('if is_acc(term):\n validate_acc_bound(term)\nelse:\n pass').body[0]
    branch.orelse=old;policy.orelse=[branch]
    return ast.fix_missing_locations(fn)

def is_acc(term):return term['security_id']==acc.SID

def validate_acc_bound(term,parent):
    payload,_,q=records()
    return acc.validate_acc(term,source=payload,source_qualification=q,parent=parent)

def validate(catalog,parent):
    fn=validator_tree(Path(original.__file__).read_bytes())
    scope=dict(vars(original),__file__=__file__,CashInputBatch=subset.CashInputSubset,selected_members=subset.selected_members,
        source_binding=source_binding,is_acc=is_acc,validate_acc_bound=lambda term:validate_acc_bound(term,parent))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-subset-validator-exact-ACC-dispatch>','exec'),scope)
    need(subset.validate.__closure__ is None,'P05_BATCH_ORIGINAL_SUBSET_NO_HIDDEN_CLOSURE')
    whole=FunctionType(subset.validate.__code__,dict(subset.validate.__globals__,validator=lambda:scope['validate']),
        subset.validate.__name__,subset.validate.__defaults__)
    need(whole.__code__ is subset.validate.__code__,'P05_BATCH_ENTIRE_ORIGINAL_RETAINED_LEGAL_FIELD_REVIEW')
    return whole(catalog)

def parent_contract(parent):
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P05',ROOT);run=parent['run']
    need(parent['sha256']==OUTER==spec['outer_sha256']==digest({k:v for k,v in parent.items() if k!='sha256'})
         and parent['base']==spec['base'] and parent['repairs']==spec['repairs'] and len(parent['repairs'])==16
         and (parent['completed'],parent['source_cursor'])==(1152,'2022-07-29')
         and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==spec['state_sha256']==digest(run['state'])
         and run['input_sha256']==spec['input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs'])),
         'P05_BATCH_ACTUAL_ORIGINAL_OWN1152_FULL16_PARENT')
    return spec

def current_natives(root,parent):
    keys=set()
    for d in parent['repairs']:
        need(d['filename']==d['sha256']+'.json' and Path(d['filename']).name==d['filename'],'P05_BATCH_SAFE_CURRENT_INPUT_NAME')
        raw=(Path(root)/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'P05_BATCH_ALL16_CURRENT_INPUT_BYTES')
        doc=json.loads(raw);need(doc['schema']=='terminal-repair/1','P05_BATCH_ONLY_ORIGINAL_ORDINARY_CURRENT_INPUTS')
        keys.update((r['session'],r['security_id'],r['term_sha256']) for r in doc['suppress'])
    return keys

def catalogs(root,parent):
    parent_contract(parent);payload,review,q=records();current=current_natives(root,parent)
    raw=(HERE/SUPPORTED).read_bytes();need(sha(raw)==SUPPORTED_SHA,'P05_BATCH_WHOLE_ORIGINAL91_LEGAL_CATALOG')
    old=json.loads(raw)['terms'];lookup={(t['security_id'],t['native_session'],t['native_term_sha256']):t for t in old}
    capture=dict(run_id=review['run_id'],head=review['head'],artifact_id=review['artifact_id'],payload_sha256=review['payload_sha256'],
        scope_sha256=SCOPE,independent_data_review_sha256=PINS['P05-batch-source-review.json'],
        independent_qualification_sha256=PINS['P05-batch-source-qualification-v2.json'])
    terms=[];indices=[];retained=[]
    for i,actual in enumerate(payload['terms']):
        n=actual['native_term'];key=n['security_id'],n['session'],digest(n)
        if key[0]==acc.SID:term=acc.qualified_term()
        elif key in lookup:
            prior=lookup[key];term=deepcopy(prior)
            term['retained_qualified_legal_term']=dict(catalog_file=SUPPORTED,catalog_sha256=SUPPORTED_SHA,term_sha256=digest(prior));retained.append(i)
        else:continue
        need((n['session'],n['security_id'],digest(n)) not in current and parent['source_cursor']<n['session'],
             'P05_BATCH_ONLY_MISSING_FORWARD_NATIVE_INPUTS')
        term.update(arm='P05',parent_cursor=parent['source_cursor'],parent_outer_sha256=parent['sha256'],parent_root_admission_sha256=ROOT,
            parent_positions=deepcopy(actual['parent_positions']),identity_witness=deepcopy(actual['identity_witness']),native=deepcopy(n),source_capture=deepcopy(capture))
        terms.append(term);indices.append(i)
    need(len(terms)==66 and len(retained)==65 and indices==sorted(set(indices)),'P05_BATCH_EXACT65_RETAINED_PLUS_ONE_ACC_IN_STABLE_SOURCE_ORDER')
    result=[]
    for start in range(0,len(terms),30):
        chosen=indices[start:start+30]
        value=dict(schema='research.qualified-own-cash-input-subset/1',arm='P05',parent_cursor=parent['source_cursor'],parent_outer_sha256=parent['sha256'],
            parent_root_admission_sha256=ROOT,loader_sha256=sha(Path(__file__).read_bytes()),canonical_financial_source_changed=False,
            provider_metadata_upgraded=False,production_contacted=False,historical_causality='UNVERIFIED',
            source_data=dict(payload=payload,review=review,qualification=q),terms=terms[start:start+30],selected_source_indices=chosen,
            retained_source_indices=[i for i in chosen if i in retained])
        validate(value,parent);result.append(value)
    need([len(v['terms']) for v in result]==[30,30,6],'P05_BATCH_EXACT_THREE_BOUNDED_CHUNKS')
    return result

class QualifiedChunk:
    def __init__(self,catalog,parent):
        validate(catalog,parent);self.catalog=deepcopy(catalog);self.catalog_sha=sha(encoded(catalog));self.compiler_sha=sha(Path(__file__).read_bytes())
