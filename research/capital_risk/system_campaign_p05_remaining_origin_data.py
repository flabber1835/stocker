"""Read actual neutral-origin metadata; never construct or restore a checkpoint."""
import ast,gzip,json,math
from copy import deepcopy
from pathlib import Path,PurePosixPath
import system_campaign_p05_remaining_batch_data as data
import system_campaign_p05_remaining_batch_api as api_module
import system_campaign_p05_batch_runtime as old_batch
import system_campaign_retained_cash_materials_v2 as old_materials
from system_campaign_facts import digest

HERE=Path(__file__).parent
DIRECTORY='p05-retained18-origin'
MANIFEST=DIRECTORY+'/origin.json'
PARENT=DIRECTORY+'/actual-parent-checkpoint.json.gz'
NEUTRAL=DIRECTORY+'/actual-neutral-checkpoint.json.gz'
ADOPTION_PROOF=DIRECTORY+'/actual-neutral-proof.json'
need,sha,encoded=data.need,data.sha,data.encoded
MATERIALS_SHA='54a637eba2b34f17efd17125e1eeaa24c30684246c04cfa1ad58bdf3a114d06a'
BATCH_SHA='62cfe5fb30d61b442f2372158f3dab9110f0120ed2470fafdfc9acf84400095b'

def required_resources():
    return {PARENT,NEUTRAL,ADOPTION_PROOF,data.CATALOG,api_module.original.hydration_name({'sha256':data.own.OUTER}),
        api_module.original.OVERLAY,api_module.original.SOURCE_SCOPES,api_module.QUALIFICATION,
        'provider-source/SHARADAR_ACTIONS.zip','P05-retained18-provider-stage.json'}

def actual_json(raw):
    return old_batch.strict_json(raw)

def material(parent):
    data.own.parent_contract(parent)
    sr,_=data.records();terms=data.terms()
    delivered={(r['session'],r['security_id']):r for r in sr['delivery_proof']['delivered_rows']}
    need(len(delivered)==3,'P05_ORIGIN18_THREE_INDEPENDENT_ORIGINAL_DELIVERY_ROWS')
    for t in terms:
        if t['security_id'] not in data.STOCKS:continue
        w=t['delivered_identity_witness'];row=delivered[w['session'],w['security_id']]
        need(all(row[k]==v for k,v in w.items() if k!='source_observation_sha256') and digest(row)==w['source_observation_sha256'],
            'P05_ORIGIN18_WHOLE_CLOSED_DELIVERY_ROW_AND_FULL_IDENTITY')
        price=float(row['raw_open'])
        need(math.isfinite(price) and price>0,'P05_ORIGIN18_POSITIVE_ORIGINAL_DECLARED_RAW_OPEN_CIL')
        t['added']['cash_in_lieu_price_per_delivered_share']=price
    from system_campaign_2021_completions_facts import CIL
    codec=data.codec(parent)
    return dict(schema=api_module.original.REFERENCE,arm='P05',catalog=data.CATALOG,catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha,selector_sha256=sha(Path(api_module.__file__).read_bytes()),
        parent_outer_sha256=parent['sha256'],terms=terms,cil_convention=CIL,native_and_delivery_witnesses_verified=21,
        consumed_native_preserved=[],financial_source_changed=False,provider_metadata_upgraded=False,
        original_validator_description=codec.validator_description)

def qualification(value):
    need(value==dict(passed=True,packet_checks=36,only_terminal_field_changed=True,
        complete_terms_and_canonical_notional_verified=True,original_incomplete_guard_retained=True,
        wrong_predecessor_and_consumed_date_refused=True,wrong_native_and_delivery_witness_refused=True,financial_sessions_advanced=0)
        and type(value['packet_checks']) is type(value['financial_sessions_advanced']) is int,
        'P05_ORIGIN18_COMPLETE_ORIGINAL_36_PACKET_QUALIFICATION')

def origin(value,current,member):
    need(value['schema']=='research.P05-own1175-retained18-actual-neutral-origin/1' and value['passed'] is True
        and value['origin_root_admission_sha256']==data.own.ROOT and value['origin_parent_is_financial_seed'] is False
        and value['financial_state_unchanged'] is True and value['canonical_financial_source_changed'] is False
        and type(value['financial_sessions_advanced']) is int and value['financial_sessions_advanced']==0,
        'P05_ORIGIN18_ONLY_GENUINE_ZERO_ADVANCE_INPUT_PROVENANCE')
    pins=value['resources']
    need(set(pins)==required_resources() and all(isinstance(n,str) and not PurePosixPath(n).is_absolute()
        and '..' not in PurePosixPath(n).parts and ':' not in n and '\\' not in n for n in pins),
        'P05_ORIGIN18_EXACT_SAFE_FULL_RESOURCE_INVENTORY_BEFORE_READ')
    blobs={n:member(n) for n in pins}
    need(all(dict(bytes=len(raw),sha256=sha(raw))==pins[n] for n,raw in blobs.items()),'P05_ORIGIN18_ALL_FULL_RESOURCE_BYTES_BEFORE_PARSE')
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P05',data.own.ROOT)
    need(pins[PARENT]==spec['selected_file'],'P05_ORIGIN18_IMMUTABLE_ACTUAL1175_PARENT_GZIP')
    parent=actual_json(blobs[PARENT]);data.own.parent_contract(parent)
    selected_material=material(parent);hydrated=api_module.original.hydration_name(parent)
    need(blobs[data.CATALOG]==encoded(data.catalog(parent)) and blobs[hydrated]==encoded(selected_material),
        'P05_ORIGIN18_ENTIRE_EXACT_SELECTED_CATALOG_AND_HYDRATED_MATERIAL')
    api=api_module.api(parent)
    document=api.document(parent,selected_material,sha(blobs[hydrated]))
    need(blobs[api_module.original.OVERLAY]==encoded(document) and len(document['source_evidence'])<=128,
        'P05_ORIGIN18_WHOLE_ORIGINAL_DOCUMENT_AND_UNCHANGED128_EVIDENCE_LIMIT')
    scopes=api.source_scopes(parent,selected_material,sha(blobs[api_module.original.OVERLAY]),sha(blobs[hydrated]))
    need(len(scopes)==1 and blobs[api_module.original.SOURCE_SCOPES]==encoded(scopes),'P05_ORIGIN18_ONE_WHOLE_ORIGINAL_CTXS_SOURCE_ONLY_SCOPE')
    qualification(json.loads(blobs[api_module.QUALIFICATION]))
    need(sha(blobs['provider-source/SHARADAR_ACTIONS.zip'])=='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
        and len(blobs['provider-source/SHARADAR_ACTIONS.zip'])==9855560,'P05_ORIGIN18_ENTIRE_ORIGINAL_PROVIDER_OBJECT')
    stage=json.loads(blobs['P05-retained18-provider-stage.json'])
    need(stage==dict(passed=True,provider_sha256='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02',
        original_provider_rows_verified=9,financial_sessions_advanced=0,original_stage_code_unchanged=True,metadata_authority_upgraded=False),
        'P05_ORIGIN18_ALL_NINE_ORIGINAL_PROVIDER_ROWS_CLOSED')
    neutral=actual_json(blobs[NEUTRAL])
    from system_campaign_pxd_pause import adoption
    event=adoption(neutral,parent,sha(blobs[api_module.original.OVERLAY]),'2022-09-29')
    proof=json.loads(blobs[ADOPTION_PROOF])
    need(proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(blobs[NEUTRAL]),original_outer_sha256=parent['sha256'],
        financial_state_unchanged=True,financial_sessions_advanced=0) and len(neutral['repairs'])==20,
        'P05_ORIGIN18_ORIGINAL_REAL_GATE_PROOF_AND_EXACT_NEUTRAL20')
    need(current['sha256']==digest({k:v for k,v in current.items() if k!='sha256'})
        and current['run']['checkpoint_sha256']==digest({k:v for k,v in current['run'].items() if k!='checkpoint_sha256'})
        and current['run']['state_sha256']==digest(current['run']['state'])
        and current['run']['input_sha256']==digest(dict(base=current['base'],repairs=current['repairs']))
        and current['repairs']==neutral['repairs'] and current['base']==parent['base']
        and current['completed']>=parent['completed'] and current['source_cursor']>=parent['source_cursor']
        and current['source_cursor']==current['run']['state']['last_processed_session'],
        'P05_ORIGIN18_ACTUAL_CURRENT_COMPLETE20_STATE_AND_INPUT_COMMITMENTS_NO_PROJECTION')
    for name,pin in current['journals'].items():
        raw=member('book/'+name+'.jsonl')
        need(len(raw)>=pin['bytes'] and sha(raw[:pin['bytes']])==pin['prefix_sha256'],'P05_ORIGIN18_ALL_CURRENT_COMMITTED_JOURNAL_PREFIXES')
    watch=member('book/watch.jsonl');a,b=parent['journals']['watch'],neutral['journals']['watch']
    need(sha(watch[:a['bytes']])==a['prefix_sha256'] and sha(watch[:b['bytes']])==b['prefix_sha256']
        and [json.loads(line) for line in watch[a['bytes']:b['bytes']].splitlines()]==[event],
        'P05_ORIGIN18_EXACT_SINGLE_ORIGINAL_WATCH_APPEND')
    need(value['parent_outer_sha256']==parent['sha256'] and value['neutral_outer_sha256']==neutral['sha256']
        and value['descriptor']==neutral['repairs'][-1],'P05_ORIGIN18_EXACT_ACTUAL_MANIFEST_CLOCK_AND_DESCRIPTOR')
    old_batch.chain_relations(json.loads(member(old_batch.CHAIN)),current,member)
    return dict(parent=parent,neutral=neutral,material=selected_material,scopes=scopes,resources=blobs,
        cash_terms=[t for t in selected_material['terms'] if t['added']['kind']=='CASH_MERGER' and t['security_id']!=data.own.SID],
        descriptor=neutral['repairs'][-1])

def composite(cp,descriptor,names,member):
    need(len(cp['repairs'])==20 and descriptor==cp['repairs'][19],'P05_ORIGIN18_ONE_EXACT_TWENTIETH_DESCRIPTOR')
    raw=member(MANIFEST);result=origin(json.loads(raw),cp,member)
    need(descriptor==result['descriptor'] and len(result['cash_terms'])==14,'P05_ORIGIN18_FULL_COMPOSITE_DISPATCH_BEFORE_CASH_VISITOR')
    return dict(terms=result['cash_terms'],resources=dict(result['resources'],**{MANIFEST:raw}),
        entry=dict(descriptor=deepcopy(descriptor),material_file=api_module.original.hydration_name(result['parent']),
            material_sha256=sha(encoded(result['material'])),overlay_file=api_module.original.OVERLAY,
            selected_terms=14,whole_composite_terms=18,source_only_terms=1,stock_or_mixed_terms=3,origin_manifest=MANIFEST))

def remaining_cash(term):
    return remaining_cash_from(term,data.terms())

def remaining_cash_from(term,expected):
    found=[t for t in expected if t['security_id']==term['security_id'] and t['added']['kind']=='CASH_MERGER' and t['security_id']!=data.own.SID]
    if not found:return False
    need(len(found)==1 and encoded(term)==encoded(found[0]),'P05_ORIGIN18_ONLY_FOURTEEN_BYTE_EXACT_RETAINED_NEXT_CASH_TERMS')
    return True

def inventory_tree(raw):
    need(sha(raw)==MATERIALS_SHA,'P05_ORIGIN18_ENTIRE_ORIGINAL_MATERIALS_AST_SOURCE')
    fn,=[deepcopy(n) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inventory']
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='descriptor']
    index,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n)=='doc = json.loads(raw)']
    branch=ast.parse("""if len(cp['repairs']) == 20 and descriptor == cp['repairs'][19]:
    extra = composite(cp, descriptor, names, member)
    for term in extra['terms']:
        key = term['added']['session'], term['security_id']
        need(key not in keys, 'P05_ORIGIN18_NO_CASH_COLLISION_WITH_ANY_PRIOR_INPUT')
        keys.add(key)
        terms.append(deepcopy(term))
    need(not set(resources).intersection(extra['resources']), 'P05_ORIGIN18_NO_RESOURCE_NAMESPACE_REPLACEMENT')
    resources.update(extra['resources'])
    entries.append(extra['entry'])
    continue
""").body[0]
    loop.body.insert(index+1,branch)
    undo=deepcopy(fn);undo_loop,=[n for n in undo.body if isinstance(n,ast.For) and ast.unparse(n.target)=='descriptor'];undo_loop.body.pop(index+1)
    old,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inventory']
    need(ast.dump(undo,include_attributes=False)==ast.dump(old,include_attributes=False),'P05_ORIGIN18_WHOLE_MATERIALS_AST_SINGLE_BRANCH_UNDO')
    return ast.fix_missing_locations(fn)

def batch_inventory_tree(raw):
    need(sha(raw)==BATCH_SHA,'P05_ORIGIN18_ENTIRE_ORIGINAL_BATCH_AST_SOURCE')
    fn,=[deepcopy(n) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inventory']
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='term']
    loop.body.insert(0,ast.parse('if remaining_cash(term):\n    continue').body[0])
    undo=deepcopy(fn);undo_loop,=[n for n in undo.body if isinstance(n,ast.For) and ast.unparse(n.target)=='term'];undo_loop.body.pop(0)
    old,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inventory']
    need(ast.dump(undo,include_attributes=False)==ast.dump(old,include_attributes=False),'P05_ORIGIN18_WHOLE_BATCH_AST_SINGLE_EXACT_CASH_BRANCH_UNDO')
    return ast.fix_missing_locations(fn)

def inventory_function():
    raw=Path(old_materials.__file__).read_bytes();namespace=dict(vars(old_materials),composite=composite)
    exec(compile(ast.Module(body=[inventory_tree(raw)],type_ignores=[]),'<whole-original-materials-plus-one-full-composite-visitor>','exec'),namespace)
    material_inventory=namespace['inventory']
    expected=data.terms()
    namespace=dict(vars(old_batch),ORIGINAL_INVENTORY=material_inventory,remaining_cash=lambda term:remaining_cash_from(term,expected))
    exec(compile(ast.Module(body=[batch_inventory_tree(Path(old_batch.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-P05-inventory-plus-fourteen-exact-NEXT-terms>','exec'),namespace)
    return namespace['inventory']
