"""Qualified additional sensor DATA, visitors and exact declaration; no book copy."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).parent
MODE='RETAINED_ADDITIONAL_SENSOR'
SCHEMA='research.zogenix-leadership-uncertainty-input/1'
BRANCH_INPUT='research.leadership-branch-uncertainty-input/1'
MODELS=(BRANCH_INPUT,SCHEMA)
ORIGIN='additional-sensor-origin.json'
QUALIFICATION='additional-sensor-zero-advance-qualification.json'
ADOPTION='additional-sensor-model-adoption'
DECLARATION='research.retained-additional-sensor-declaration/1'
# Replaced only by the private package builder before qualification.
EXPECTED={'system-campaign-financial-branch-contract.json': 'bf988db6a8a4e84e62a316ce0dce907799988abf99468b868878b6007d9c983b', 'system_campaign_financial_branches.py': 'b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef', 'system-campaign-zogenix-sensor-contract.json': '699149d418a932ca10f7c1f0848a5e9bb5f14083be431f7fde3a741c1d4313de', 'system_campaign_zogenix_input.py': 'da4b5af6b5a4e9a6c5cd3ffd236b127a509f984f8743a0b51be49381fc2be812', 'system_campaign_zogenix_facts.py': '1cc8906a8bc7d01b160186d091415d252b9fff45116fa466b46d947a24e90056', 'system_campaign_zogenix_sensor.py': 'df3de6905a23b06254044a8a0f08833d6f3a68290706114a873d8440eedb560e', 'system_campaign_zogenix_review.py': '650f31c3d1f5d9bcfa854c069425170be7fa8ba28c70f7aeee47b488c8046af0', 'system_campaign_zogenix_basis.py': '54c33ba88d951d7360d11e67a9e254693361e588b70c4e39704b2fc66e8fd3fa', 'system_campaign_zogenix_gate.py': '99d248ace66b90c8029ed778e0c1784c65cf508b426348102f0c4a6b50076869', 'system_campaign_uncertainty_context.py': 'b9a51977d6456c5684564f74927d2a5585db2208156269c077b9d35eb8373610', 'system_campaign_uncertainty_math.py': 'a53a3a7b463659eb3788923d504c402a2edd183a3922f20abe51c55dcd303213', 'system_campaign_point_growth.py': '1da8862ccc64dd990c25359d5f1ca03f3e964fa0423df17d9d4865218213a7a0', 'system_campaign_sprint_facts.py': '1f532038b78a89c1ddac805a786f14cf516707b69ecdad4ef621c1902e93fd3b', 'system_campaign_financial_projection.py': '2165e64a961bf0ee44c8f19ac2d6ec65059cc92a2b4154ad735685d29e120777', 'system_campaign_future_amendment.py': '08c39115736eda1a3b6312be710ee8fd8b479554bddb2a035b81a307723fd187', 'system_campaign_uncertainty_input.py': '85572869e11ac0447618c3f6b80ae7d9160746444453959d76852175bc0fc5f3'}
LEGACY_AST={'pause': 'df850dc0669023ee38073da8f407c76de5cf6e7a71364ebad3f389787a9aa6b8', 'retained_seed': '8e1a5e063709417b8984a0f0e35affc4287eaba3c39d1b90908b32caa7203968', 'review_driver_body': '4bf509a234865bbcd905a5644300b97a80f604b7daed4b141d1db3e3a154d06a'}
SOURCE_BINDING_AST='9d1da55a7129c5da97524468b998783f1690d6e830b77fc4ac60c4fb1cff8899'

def need(ok,label):
    if not ok:raise ValueError('REFUSED_'+label)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())

def function(raw,name):
    found=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    need(len(found)==1,'ADDITIONAL_EXACT_SOURCE_FUNCTION')
    return found[0]

def legacy_function(path,name,key):
    fn=function(Path(path).read_bytes(),name)
    need(key in LEGACY_AST and sha(ast.dump(fn,include_attributes=False).encode())==LEGACY_AST[key],
         'ADDITIONAL_EXACT_LEGACY_ORCHESTRATION_FUNCTION_AST')
    return fn

def source(name):
    raw=(HERE/name).read_bytes()
    need(name in EXPECTED and sha(raw)==EXPECTED[name],'ADDITIONAL_UNCHANGED_SOURCE_BYTES')
    return raw

def phase(spec):
    if not isinstance(spec,dict):return None
    from system_campaign_financial_uncertainty import own_policy_catalog
    p=own_policy_catalog()['phases'].get(spec.get('root_admission_sha256'))
    if p is None or p.get('mode')!=MODE:return None
    need(p['arm']==spec['arm'] and (p['outer_sha256'],p['source_cursor'],p['completed'])==
         (spec['outer_sha256'],spec['selected_session'],spec['measured_closes'])
         and p['financial_authority'] is False and p['source_DATA_qualified'] is True
         and p['adoption_mode'] in ('INITIAL','RETAINED')
         and p['ordinary_input_mode']==('NEW_QUALIFIED_ORDINARY' if p['adoption_mode']=='INITIAL' else 'UNCHANGED'),
         'ADDITIONAL_EXACT_REGISTERED_ROOT_PHASE')
    if p['adoption_mode']=='RETAINED':retained_origin(p)
    return p


def retained_origin(p):
    from system_campaign_financial_uncertainty import own_policy_catalog
    original=own_policy_catalog()['phases'].get(p['origin_root_admission_sha256'])
    need(original is not None and original['mode']==MODE and original['adoption_mode']=='INITIAL'
         and original['arm']==p['arm'] and p['root_admission_sha256']!=original['root_admission_sha256']
         and p['origin_record_sha256']==sha(encoded(original)),
         'ADDITIONAL_EXACT_REGISTERED_INITIAL_ORIGIN_RECORD')
    mutable={'root_admission_sha256','outer_sha256','completed','source_cursor','adoption_mode','ordinary_input_mode',
             'proof_rows','proof_new_rows','proof_retained_rows'}
    need(set(p)==set(original)|{'origin_record_sha256'}
         and all(p[k]==v for k,v in original.items() if k not in mutable),
         'ADDITIONAL_ALL_ORIGINAL_MODEL_SOURCE_AND_OBSERVER_BINDINGS_UNCHANGED')
    return original

def declaration(p,policy_sha):
    from system_campaign_financial_uncertainty import OWN_POLICY_SHA,OWN_POLICY_CLOSED_GENERATIONS
    need(policy_sha==OWN_POLICY_SHA or p['root_admission_sha256'] in OWN_POLICY_CLOSED_GENERATIONS.get(policy_sha,()),
         'ADDITIONAL_DECLARED_CLOSED_POLICY_GENERATION')
    return dict(schema=DECLARATION,mode=MODE,input_schema=BRANCH_INPUT,input_schemas=list(MODELS),
        root_admission_sha256=p['root_admission_sha256'],origin_root_admission_sha256=p['origin_root_admission_sha256'],
        policy_catalog_sha256=policy_sha,source_payload_sha256=p['source_payload_sha256'],
        source_review_sha256=p['source_review_sha256'],source_qualification_sha256=p['source_qualification_sha256'],
        retained_prefix_sha256=p['retained_prefix_sha256'],retained_rows=p['retained_rows'],
        original_branch_descriptor=deepcopy(p['original_branch_descriptor']),
        ordinary_origin_outer_sha256=p['origin_outer_sha256'],
        cp1_predecessor_binding='EXACT_REVIEWED_NEUTRAL_ORDINARY_SUCCESSOR',
        observer_generation='IMMUTABLE_ORIGIN_SOURCE_REQUEST',
        every_reachable_canonical_decision_must_match=True,original_strict_guard_unchanged=True)

def report_declaration(request,arm):
    d=request.get('selected_research_models',{}).get(arm)
    if not isinstance(d,dict) or d.get('schema')!=DECLARATION:return None
    from system_campaign_financial_uncertainty import own_policy_catalog,OWN_POLICY_CATALOG
    p=own_policy_catalog()['phases'].get(d['root_admission_sha256'])
    need(p is not None and p['mode']==MODE and p['arm']==arm
         and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
         and request['financial_resume_authorized'] is True and request['financial_source_changed'] is False
         and d==declaration(p,request['sources'][OWN_POLICY_CATALOG])
         and request['admitted_checkpoints'][arm]==p['outer_sha256'],
         'ADDITIONAL_REPORT_EXACT_ORIGINAL_DECLARATION')
    if p['adoption_mode']=='RETAINED':
        from system_campaign_financial_partial import root_spec
        from system_campaign_financial_uncertainty import OWN_POLICY_CLOSED_GENERATIONS
        original=retained_origin(p)
        transported=root_spec(arm,p['root_admission_sha256'])
        stored=transported.get('retained_additional_sensor')
        generation=stored.get('policy_catalog_sha256') if isinstance(stored,dict) else None
        need(transported['root_admission_sha256']==p['root_admission_sha256']
             and (transported['outer_sha256'],transported['selected_session'],transported['measured_closes'])==
                 (p['outer_sha256'],p['source_cursor'],p['completed'])
             and original['root_admission_sha256'] in OWN_POLICY_CLOSED_GENERATIONS.get(generation,())
             and stored==declaration(original,generation),
             'ADDITIONAL_REPORT_PRESERVES_AUTHENTICATED_INITIAL_TRANSPORT_PROVENANCE')
        d=stored
    return dict(retained_uncertainty_model=BRANCH_INPUT,retained_additional_sensor=deepcopy(d))

def selected_declaration(root,cp,spec):
    p=phase(spec)
    if p is not None:
        if 'retained_additional_sensor' in spec:
            from system_campaign_financial_uncertainty import OWN_POLICY_SHA,OWN_POLICY_CLOSED_GENERATIONS
            d=spec['retained_additional_sensor']
            exact=d==declaration(p,OWN_POLICY_SHA)
            if not exact and p['adoption_mode']=='RETAINED':
                original=retained_origin(p)
                generation=d.get('policy_catalog_sha256') if isinstance(d,dict) else None
                need(original['root_admission_sha256'] in OWN_POLICY_CLOSED_GENERATIONS.get(generation,()),
                     'ADDITIONAL_STORED_INITIAL_DECLARATION_CLOSED_GENERATION')
                exact=d==declaration(original,generation)
            need(exact,
                 'ADDITIONAL_REGISTERED_SCOPE_DECLARATION_EXACT')
        return p
    d=spec.get('retained_additional_sensor')
    if d is None:return None
    need('root_admission_sha256' not in spec,'ADDITIONAL_NO_UNREGISTERED_ADMITTED_MODEL_ROOT')
    raw=(Path(root)/'request.json').read_bytes();request=json.loads(raw)
    need(sha(raw)==spec['request_sha256'],'ADDITIONAL_REPORT_ORIGINAL_REQUEST_BYTES')
    found=report_declaration(request,spec['arm'])
    need(found is not None and found['retained_additional_sensor']==d
         and spec['monthly_seed_root_admission_sha256']==request['selected_research_models'][spec['arm']]['root_admission_sha256']
         and cp['sha256']==spec['outer_sha256'] and cp['completed']==spec['measured_closes'],
         'ADDITIONAL_REPORT_EXACT_SAVED_PREFIX_SCOPE')
    from system_campaign_financial_uncertainty import own_policy_catalog
    return own_policy_catalog()['phases'][request['selected_research_models'][spec['arm']]['root_admission_sha256']]


def qualified_source_identity_only(q):
    need(q['schema']=='research.independent-frozen-source-data-validation/1'
         and q['passed'] is True and q['source_identity_qualified_for_separate_future_input_review'] is True
         and q['source_value_or_settlement_timing_qualified'] is False
         and q['financial_authority'] is q['input_adopted'] is q['local_canonical_runtime_executed'] is False
         and type(q['financial_workers_launched']) is int and q['financial_workers_launched']==0
         and q['fresh_archive_and2022_raw_scan_verified'] is True,
         'ADDITIONAL_CLOSED_IDENTITY_ONLY_QUALIFICATION_SCHEMA')
    return True

def common_source_binding(cp,p):
    """Reuse the unchanged source-binding statements preceding ALDR specialization."""
    import system_campaign_financial_uncertainty as u
    raw=Path(u.__file__).read_bytes();fn=function(raw,'own_source_binding')
    need(sha(ast.dump(fn,include_attributes=False).encode())==SOURCE_BINDING_AST,
         'ADDITIONAL_UNCHANGED_GENERIC_SOURCE_BINDING_AST')
    sites=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and
           len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='event']
    need(len(sites)==1,'ADDITIONAL_EXACT_SOURCE_SPECIALIZATION_BOUNDARY')
    fn.body=fn.body[:sites[0]]+[ast.Return(ast.Name(id='payload',ctx=ast.Load()))]
    fields=[n for n in ast.walk(fn) if isinstance(n,ast.Subscript) and ast.unparse(n)=="qualification['source_identity_only']"]
    need(len(fields)==1,'ADDITIONAL_EXACT_QUALIFICATION_IDENTITY_SCHEMA_SITE')
    class Qualification(ast.NodeTransformer):
        def visit_Subscript(self,node):
            if ast.unparse(node)=="qualification['source_identity_only']":
                return ast.copy_location(ast.parse('qualified_source_identity_only(qualification)',mode='eval').body,node)
            return self.generic_visit(node)
    fn=Qualification().visit(fn)
    namespace=dict(vars(u),qualified_source_identity_only=qualified_source_identity_only);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unchanged-additional-source-binding-prefix>','exec'),namespace)
    payload=namespace['own_source_binding'](cp,p)
    c=json.loads(source('system-campaign-zogenix-sensor-contract.json'))
    event=p['event'];native=[t for t in payload['terms'] if t['native_term']['security_id']==c['security_id']]
    need(len(native)==1 and event['security_id']==c['security_id']
         and event['native_term']==native[0]['native_term']==c['native']
         and event['native_term_sha256']==c['native_term_sha256']
         and event['identity_witness']==native[0]['identity_witness']
         and event['parent_positions']==native[0]['parent_positions']==[] and event['parent_pending']==[]
         and event['parent_selected'] is True and c['cash_consideration_range']==[26.,28.],
         'ADDITIONAL_EXACT_UNOWNED_SELECTED_ORIGINAL_EVENT_CONTRACT')
    need(p['original_descriptors']==cp['repairs'] and len(cp['repairs'])==20,
         'ADDITIONAL_EXACT_TWENTY_PARENT_DESCRIPTORS')
    return payload

def descriptors(root,cp):
    values=[]
    for d in cp['repairs']:
        need(d['filename']==d['sha256']+'.json' and Path(d['filename']).name==d['filename'],
             'ADDITIONAL_SAFE_EXACT_DESCRIPTOR_NAME')
        raw=(Path(root)/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'],'ADDITIONAL_ALL_FULL_CHECKPOINT_INPUT_BYTES')
        doc=json.loads(raw)
        need(doc['predecessor_checkpoint_sha256']==d['predecessor_checkpoint_sha256'],
             'ADDITIONAL_DESCRIPTOR_ORIGINAL_PREDECESSOR')
        values.append((d,doc))
    need(len({d['sha256'] for d,doc in values})==len(values),'ADDITIONAL_UNIQUE_DESCRIPTORS')
    return values

def validate_models(root,cp,p,*,origin=None,require_additional=True,input_hash=None):
    """Validate full cp, then visit exactly one authenticated additional descriptor."""
    source('system_campaign_financial_branches.py');source('system_campaign_zogenix_input.py');source('system_campaign_uncertainty_input.py')
    if input_hash is not None:
        need(cp['run']['input_sha256']==input_hash(cp['base'],cp['repairs']),
             'ADDITIONAL_FULL_CANONICAL_INPUT_HASH')
    values=descriptors(root,cp);added=[d for d,doc in values if doc['schema']==SCHEMA]
    need(len(added)==(1 if require_additional else 0)
         and all(doc['schema'] in ('terminal-repair/1',*MODELS) for d,doc in values),
         'ADDITIONAL_EXACT_DECLARED_MODEL_SCHEMAS')
    branch=[d for d,doc in values if doc['schema']==BRANCH_INPUT]
    need(branch==[p['original_branch_descriptor']],'ADDITIONAL_UNCHANGED_ORIGINAL_BRANCH_ORIGIN')
    if added:
        need(origin is not None and origin['schema']=='research.retained-additional-sensor-origin/1'
             and origin['origin_root_admission_sha256']==p['origin_root_admission_sha256']
             and origin['ordinary_origin_outer_sha256']==p['origin_outer_sha256']
             and cp['repairs'][:20]==p['original_descriptors']
             and cp['repairs'][20]==origin['ordinary_descriptor']
             and cp['repairs'][21:]==added and added[0]==origin['sensor_descriptor']
             and added[0]['resume_session']==p['origin_cursor']
             and added[0]['predecessor_checkpoint_sha256']==origin['cp1_inner_sha256'],
             'ADDITIONAL_EXACT_NEUTRAL_CP1_AND_TWENTYTWO_INPUT_ORIGIN')
        from system_campaign_zogenix_input import parse
        from system_campaign_zogenix_facts import evidence
        c=json.loads(source('system-campaign-zogenix-sensor-contract.json'));d=added[0]
        obj=parse(Path(root)/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'],expected_evidence=evidence(Path(root)),
            native_sha256=c['native_term_sha256'])
        need(obj.sha256==d['sha256'],'ADDITIONAL_EXACT_PARSED_SENSOR_OBJECT')
    import system_campaign_financial_branches as b
    fn=function(source('system_campaign_financial_branches.py'),'validate_input')
    loop,=[n for n in fn.body if isinstance(n,ast.For)]
    site,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='schema']
    skip=ast.parse("if schema==ADDITIONAL_SCHEMA:\n need(descriptor==validated_descriptor,'ADDITIONAL_ONLY_VALIDATED_SCHEMA_VISITED')\n continue").body[0]
    loop.body.insert(site+1,skip)
    namespace=dict(vars(b),ADDITIONAL_SCHEMA=SCHEMA,validated_descriptor=added[0] if added else None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<source-qualified-additional-branch-semantic-visitor>','exec'),namespace)
    need(namespace['validate_input'](Path(root),cp)==p['original_branch_descriptor']['sha256'],
         'ADDITIONAL_ORIGINAL_BRANCH_VALIDATOR_RESULT')
    return added

def mixed_growth(returns,*,point,interval):
    values=list(returns)
    return point(values) if all(v.lo==v.hi for v in values) else interval(values)

def suffix_tree():
    """Original B19 loop: iterator + one exact declared-event predicate only."""
    fn=function(source('system_campaign_financial_branches.py'),'review')
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)']
    need(ast.unparse(loop.iter)=='enumerate(rows)','ADDITIONAL_EXACT_SUFFIX_ITERATOR')
    loop.iter=ast.parse('enumerate(rows,start=retained_count)',mode='eval').body
    guards=[n for n in ast.walk(loop) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and
        n.func.id=='need' and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and
        n.args[1].value=='BRANCH_ONLY_DECLARED_EVENT_MAY_VARY']
    need(len(guards)==1 and ast.unparse(guards[0].args[0])==
         "row['session'] == DAY and item['security_id'] == SID or bound.lo == bound.hi",
         'ADDITIONAL_EXACT_ONE_ORIGINAL_VARYING_GUARD')
    old=deepcopy(guards[0].args[0])
    guards[0].args[0]=ast.BoolOp(op=ast.Or(),values=[old,
        ast.parse('additional_event_allows(row,item)',mode='eval').body])
    current,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
        any(isinstance(a,ast.Constant) and a.value=='BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE' for a in n.value.args)]
    return ast.fix_missing_locations(ast.Module(body=[loop,current],type_ignores=[]))

def unchanged_phase(spec):
    p=phase(spec)
    return p is not None and p['adoption_mode']=='RETAINED'

def validate_admission_metadata(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    p=phase(spec)
    need(p is not None and p['adoption_mode']=='RETAINED',
         'ADDITIONAL_ADMISSION_EXPLICIT_REGISTERED_RETAINED_ROOT')
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is True and type(proof['rows']) is type(proof.get('retained_rows',0)) is int
         and proof['rows']==p['proof_new_rows'] and proof.get('retained_rows',0)==p['proof_retained_rows']
         and p['proof_rows']==p['proof_new_rows']+p['proof_retained_rows']
         and proof['all_comparisons_and_state_sets_verified'] is True
         and proof['all_math_watch_financial_chains_verified'] is True,
         'ADDITIONAL_ADMISSION_CURRENT_EXACT_SUFFIX_COUNTS_AND_MATH')
    need(p['origin_root_admission_sha256']!=p['root_admission_sha256']
         and p['retained_rows']==593 and p['retained_prefix_sha256']=='f05bf4dcb4e5b8f78089b27d661fa58dab095740b2d014ccd90ed3d21d222263',
         'ADDITIONAL_ADMISSION_ORIGINAL_MODEL_AND_593_ORIGIN')
    return p
