"""Unselected P06 proof-only continuation; actual1259 admission is mandatory."""
import ast,json
from pathlib import Path
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_input import need
import system_campaign_p06_abmd_initial_certificate as frozen

FROZEN_SHA='b292b0e4abae5d3856bf4bf1ace64c229e0a97f24336ec73abf8542175e99194'
WITNESS_SHA='177d5906b9ecd6b33512999ef8408704d5814ba5f69a4d8284fb22b62b7f5cf1'
WITNESS_AST='350eb17c2021391839632f7187441ce56169861da89c101679b162a89949aa23'
POINT_SHA='1da8862ccc64dd990c25359d5f1ca03f3e964fa0423df17d9d4865218213a7a0'
MIXED_SHA='06a668304548a09283f0daa0230443fb9774ba8373e0f5b6b21c5e7e960710be'
INITIAL_ROOT='947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e'
SAVED_OUTER='3ca71397d85be2f44a0551bb45ff08b276d5f8b692383f8458f9186c23d1db40'
SAVED_GZIP=dict(bytes=1332560,sha256='95916965553648f260bd582a7a2595504aef7a7ac92de075c50aabe6eb3b03de')
SIX_PREFIX=dict(bytes=97184,sha256='46db300cbb9267683b62148711f14db1bb2b9452680cba18fbee29e2af3927f7')
ENTIRE_OLD_PROOF=dict(bytes=280948,sha256='fa575114e290733777eeaba5f1e2724e6a233d40844cbd71d8b33ae5c0ae74b0')
LAST_CHAIN='6819e517e61682e6ffd22565481ae08de261913dc7938c71b9d81933598eb1e6'

def function(raw,name):
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name];return fn
def compact(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def proof_bytes(rows):return b''.join(compact(v)+b'\n' for v in rows)

def arithmetic_sources(witness_raw,point_raw,mixed_raw):
    need(sha(witness_raw)==WITNESS_SHA and sha(point_raw)==POINT_SHA and sha(mixed_raw)==MIXED_SHA,
         'P06_POINT_WHOLE_FROZEN_WITNESS_POINT_AND_MIXED_SOURCES')
    witness=function(witness_raw,'witness');point=function(point_raw,'point_growth')
    need(sha(ast.dump(witness,include_attributes=False).encode())==WITNESS_AST,
         'P06_POINT_ENTIRE_FROZEN_WITNESS_METHOD_AST')
    a,=[n.value for n in witness.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='change']
    b,=[n.value for n in point.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='change']
    class Names(ast.NodeTransformer):
        def visit_Name(self,node):return ast.copy_location(ast.Name(id='returns',ctx=node.ctx),node) if node.id=='points' else node
    need(ast.dump(a,include_attributes=False)==ast.dump(Names().visit(b),include_attributes=False),
         'P06_POINT_SAME_BUILTIN_SUM_DIVISION_AND_EMPTY_OPERATION_ORDER')
    product,=[n for n in ast.walk(witness) if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Mult)
        and ast.unparse(n.left)=="state['witness_nav'][-1]"]
    returned,=[n.value for n in point.body if isinstance(n,ast.Return)]
    point_change=returned.func.value.args[0]
    need(ast.dump(product.right,include_attributes=False)==ast.dump(point_change,include_attributes=False),
         'P06_POINT_SAME_ONE_PLUS_CHANGE_BEFORE_NAV_MULTIPLICATION')
    return dict(witness_sha256=WITNESS_SHA,whole_witness_AST_sha256=WITNESS_AST,
        point_growth_sha256=POINT_SHA,mixed_growth_sha256=MIXED_SHA)

def mixed_growth(returns):
    import system_campaign_point_growth as point
    import system_campaign_financial_additional_sensor as sensor
    from system_campaign_uncertainty_math import growth
    need(sha(Path(point.__file__).read_bytes())==POINT_SHA and sha(Path(sensor.__file__).read_bytes())==MIXED_SHA,
         'P06_POINT_EXACT_EXISTING_PROOF_ONLY_GROWTH_MODULES')
    return sensor.mixed_growth(returns,point=point.point_growth,interval=growth)

def factory_tree(raw):
    need(sha(raw)==FROZEN_SHA,'P06_POINT_ENTIRE_FROZEN_INITIAL_FACTORY_SOURCE')
    fn=function(raw,'certificate_class')
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='material']
    need(ast.unparse(assignment.value)=='bind_function(base.return_material, SID=SID)',
         'P06_POINT_ONE_EXACT_ORIGINAL_MATERIAL_GROWTH_BINDING')
    assignment.value.keywords.append(ast.keyword(arg='growth',value=ast.Name(id='mixed_growth',ctx=ast.Load())))
    cls,=[n for n in fn.body if isinstance(n,ast.ClassDef)];init,=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__']
    guard,=[n.value for n in init.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='P06_ABMD_INITIAL_HAS_NO_PRIOR_B19_SEED' for v in n.value.args)]
    need(ast.unparse(guard.args[0])=='self.seed == [] and self.math is self.pending is None',
         'P06_POINT_ONE_EXACT_ORIGINAL_EMPTY_SEED_GUARD')
    guard.args[0]=ast.parse('qualified_retained_seed(self.seed,self.source_hashes,event,source,codec) and self.math is self.pending is None',mode='eval').body
    return ast.fix_missing_locations(fn)

def qualify_seed_metadata(current,spec,rows,committed,resolutions,allowed,archive_raw,source_hashes,expected_hashes,*,prefix_pin=SIX_PREFIX):
    need(spec['arm']=='P06' and spec['root_admission_sha256']!=INITIAL_ROOT and spec['artifact_id']==13478656632
        and current['sha256']==spec['outer_sha256']==SAVED_OUTER and spec['selected_file']==SAVED_GZIP
        and (current['completed'],current['source_cursor'])==(1259,'2022-12-30')
        and current['completed']==spec['measured_closes'] and current['source_cursor']==spec['selected_session']
        and current['base']==spec['base'] and current['repairs']==spec['repairs'] and len(current['repairs'])==10
        and current['run']['checkpoint_sha256']==spec['inner_sha256']
        and current['run']['input_sha256']==spec['input_sha256']==digest(dict(base=current['base'],repairs=current['repairs']))
        and current['run']['state_sha256']==spec['state_sha256'],
        'P06_POINT_ACTUAL_ADMITTED_SAVED1259_FULL10_IDENTITY')
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is proof['all_comparisons_and_state_sets_verified']
        is proof['all_math_watch_financial_chains_verified'] is True
        and type(proof['rows']) is type(proof.get('retained_rows',0)) is int
        and proof['rows']==6 and proof.get('retained_rows',0)==0 and len(rows)==len(committed)==6
        and proof_bytes(rows)==proof_bytes(committed)
        and dict(bytes=len(proof_bytes(rows)),sha256=sha(proof_bytes(rows)))==prefix_pin
        and rows[-1]['session']=='2022-12-30' and rows[-1]['next_state_sha256']==spec['state_sha256']
        and rows[-1]['chain_sha256']==LAST_CHAIN,
        'P06_POINT_LITERAL_SIX_ADMITTED_PROOFS_NO_UNADMITTED_TAIL')
    need(source_hashes==expected_hashes and len(source_hashes)==6
        and source_hashes['sentinel/controller/median5.py']==WITNESS_SHA
        and all(current['base']['sources'].get(n)==h for n,h in source_hashes.items()),
        'P06_POINT_EXACT_SIX_UNCHANGED_PHYSICAL_CONTROLLER_SOURCES')
    events=[row for row in rows if row['session']=='2022-12-22']
    need(len(events)==len(resolutions)==1 and events[0]['event_basis']==events[0]['bounded_event_basis']
        and events[0]['bounded_event_basis']['selected'] is False and allowed=={},
        'P06_POINT_ONE_ORIGINAL_UNSELECTED_ABMD_BASIS_NO_SECOND_EVENT')
    event,=events;resolution,=resolutions
    need(resolution['actual']=='book/pre-event/2022-12-22-'+resolution['outer_sha256']+'.json.gz'
        and resolution['state_sha256']==event['prior_state_sha256']
        and resolution['input_sha256']==event['input_sha256']==current['run']['input_sha256']
        and sha(archive_raw)==resolution['gzip_sha256'],'P06_POINT_ACTUAL_ORIGINAL_EVENT_PRODUCER_AND_SOURCE_BYTES')
    return dict(passed=True,committed_rows=6,old_six_proof_bytes_preserved=True,
        unadmitted_tail_rows_used=0,second_event_authorized=False,financial_authority=False)

def certificate_class(event,source,codec,native,*,inherited_root,retained_root,current_checkpoint,admitted_spec):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import validate_root_spec
    from research.pooled_vacancy_funding import journal
    import system_campaign_p06_abmd_models as models
    import system_campaign_p06_abmd_lifecycle_data as data
    import system_campaign_point_growth as point
    import system_campaign_financial_additional_sensor as sensor
    from system_campaign_bounded_sensor_event_review import permissions
    root=Path(retained_root);current=current_checkpoint;spec=admitted_spec
    validate_root_spec(spec)  # Impossible until actual monthly/DATA root admission.
    raw=(root/spec['selected_checkpoint']).read_bytes()
    need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file']==SAVED_GZIP
        and journal.read_checkpoint(root/spec['selected_checkpoint'])==current,
        'P06_POINT_ACTUAL_ADMITTED_GZIP_BEFORE_ANY_FACTORY_OR_SEED_USE')
    catalog=data.catalog();need(event==catalog['event'] and source==catalog['market_source'],
        'P06_POINT_UNCHANGED_V2_CATALOG_SOURCE_AND_TYPED_INPUT')
    need(models.validate_full(root,current,catalog)['full_inputs']==10,'P06_POINT_WHOLE_ORIGINAL8_9_10_HISTORY')
    data.checked_resources(root/models.DIRECTORY/'prior-resources',data.plan())
    full=(root/'uncertainty-certificate.jsonl').read_bytes()
    need(dict(bytes=len(full),sha256=sha(full))==ENTIRE_OLD_PROOF,'P06_POINT_ENTIRE_ORIGINAL18_FILE_PROVENANCE_UNCHANGED')
    committed=frozen.seed_reader(inherited_root=inherited_root)(root,current)
    allowed,resolutions=permissions(root,committed,catalog,through=current['source_cursor'],input_descriptors=current['repairs'])
    need(len(resolutions)==1,'P06_POINT_ACTUAL_ONE_PRIOR_EVENT_ARCHIVE')
    archive=(root/resolutions[0]['actual']).read_bytes()
    expected=json.loads((Path(inherited_root)/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    arithmetic_sources(Path('/variant/sentinel/controller/median5.py').read_bytes(),
        Path(point.__file__).read_bytes(),Path(sensor.__file__).read_bytes())
    point.point_growth(())  # Enforce exact CPython3.12 before installing any hook.
    def qualified_retained_seed(rows,source_hashes,actual_event,actual_source,actual_codec):
        need(actual_event==event and actual_source==source and actual_codec is codec,
             'P06_POINT_EXACT_ACTUAL_CODEC_EVENT_SOURCE')
        need((root/resolutions[0]['actual']).read_bytes()==archive
            and sha(Path('/variant/sentinel/controller/median5.py').read_bytes())==WITNESS_SHA,
             'P06_POINT_FRESH_ACTUAL_EVENT_AND_FROZEN_WITNESS_BYTES')
        qualify_seed_metadata(current,spec,rows,committed,resolutions,allowed,archive,source_hashes,expected)
        return True
    scope=dict(vars(frozen),mixed_growth=mixed_growth,qualified_retained_seed=qualified_retained_seed)
    raw=Path(frozen.__file__).read_bytes();exec(compile(ast.Module(body=[factory_tree(raw)],type_ignores=[]),
        '<whole-frozen-P06-factory-one-admitted-seed-guard-and-proof-growth-namespace>','exec'),scope)
    return scope['certificate_class'](event,source,codec,native,inherited_root=inherited_root)
