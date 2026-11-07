"""Actual FIN340 P03 JSON/hash, accounting, and branch DATA; no engine imports."""
import ast,gzip,importlib.util,json,sys
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal,localcontext
from pathlib import Path
from forecast_tests.p03_full17_reporting.prepare_target_DATA import *
P1=D.parent/'p01-progress'
sys.path.insert(0,str(P1))
import review_progress as mature
mature.CAP=C
old_reader=R/'financial324-source-snapshot/p03_bounded_financial_DATA.py'
need(sha(old_reader.read_bytes())=='c55bd3c05dce1100b566f8cb2cce456552c5e84c4927ca8243030f3d507090f0','WHOLE_CLOSED_PRIOR_DATA_READER')
module_spec=importlib.util.spec_from_file_location('closed_p03_DATA',old_reader);data=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(data)
sys.path.insert(0,str(C))
import system_campaign_p03_thor_runtime as thor
from system_campaign_financial_partial import root_spec
from system_campaign_uncertainty_review import committed_rows
from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth
from system_campaign_bounded_sensor_event_review import event_basis

def actual():
    root,members,member,current,request,spec=read_actual()
    parent=mature.checkpoint(member(thor.SELECTED));neutral=mature.checkpoint(member(thor.api_module.DIRECTORY+'/checkpoint.json.gz'))
    corr=gzip.decompress(member(thor.api_module.DIRECTORY+'-correlation-inputs.jsonl.gz')).splitlines(keepends=True)
    boundary=thor.boundary_relation(parent,neutral,spec,member,corr)
    need(parent['sha256']==spec['outer_sha256'] and neutral['sha256']=='5fb4362552632deb492c59b4348c73aa3be0b18733c2a7a4303c482efef191fc'
        and current['base']==neutral['base'] and current['repairs']==neutral['repairs'] and current['run']['input_sha256']==neutral['run']['input_sha256'],'REAL_NEUTRAL17_THEN_UNCHANGED')
    prior=member(thor.RAW_PROOF);priorlines=prior.splitlines(keepends=True)
    proofraw=member('uncertainty-certificate.jsonl');lines=proofraw.splitlines(keepends=True)
    allrows=[json.loads(v) for v in lines];rows=[v for v in allrows if v['session']<=current['source_cursor']]
    need(len(priorlines)==63 and len(rows)==70 and b''.join(lines[:49])==b''.join(priorlines[:49])
        and all(json.loads(v)['session']>parent['source_cursor'] for v in priorlines[49:])
        and all(v['session']>current['source_cursor'] for v in allrows[70:]),'EXACT_49_PROOF_PREFIX_AND_EXCLUDED_OLD_AND_CURRENT_TAILS')
    daily=committed_rows(root/'book',current,'daily');financial=[v for v in daily if v['session']>parent['source_cursor']]
    need(len(financial)==21 and [v['session'] for v in rows[49:]]==[v['session'] for v in financial],'ALL21_PROOF_FINANCIAL_AXIS')
    oracle=json.loads(member('stopped-review/uncertainty-certificate-review.json'))
    need(oracle['passed'] is oracle['every_reachable_decision_identical'] is oracle['all_financial_watch_and_proof_identities_verified'] is True
        and (oracle['retained_rows'],oracle['rows'],oracle['checkpoint_sha256'],oracle['parent_sha256'])==(49,21,current['sha256'],neutral['sha256'])
        and oracle['prior_proof_rows_reexecuted']==0 and oracle['prior_qualification_reexecuted'] is False,'EXACT_SEPARATE_SUFFIX_ORACLE')
    old_manifest=json.loads((R/'financial324-source-snapshot/capture-P03-13476494369-001/authenticated-manifest.json').read_bytes())['members']
    for name in ('branch-controller-qualification.json','uncertainty-certificate.jsonl'):
        raw=member(name) if name=='branch-controller-qualification.json' else prior
        need(dict(bytes=len(raw),sha256=sha(raw))==old_manifest[name],'ENTIRE_QUALIFIED_OLD_RESOURCE:'+name)
    reuse=json.loads(member('p03-thor-ordinary17-qualification-reuse.json'))
    need(reuse['passed'] is True and reuse['unadmitted_tail_rows_seeded']==0,'QUALIFIED49_ONLY_REUSE')
    resolution,=oracle['event_resolution'];eventcp=mature.checkpoint(member(resolution['actual']))
    need(sha(member(resolution['actual']))==resolution['gzip_sha256'] and eventcp['sha256']==resolution['outer_sha256']
        and eventcp['run']['state_sha256']==resolution['state_sha256'] and eventcp['run']['input_sha256']==resolution['input_sha256']
        and resolution['prior_event_basis_revalidated'] is True and resolution['prior_transition_reexecuted'] is False,'ACTUAL_RETAINED_DOVA_EVENT_ARCHIVE')
    eventrow=next(v for v in rows[:49] if v['session']=='2019-11-12')
    import system_campaign_bounded_sensor_runtime_v2 as runtime
    event_basis(eventrow,eventcp['run']['state'],runtime.catalog())
    return dict(root=root,members=members,member=member,parent=parent,neutral=neutral,current=current,request=request,spec=spec,rows=rows,financial=financial,oracle=oracle,boundary=boundary,raw_proof_rows=len(lines))

def branch(a,*,rows=None,financial=None,current=None,oracle=None,tree=None):
    helper=data.independent_helpers();old=a['rows'][48]
    ns=dict(vars(helper),Interval=Interval,RollingWitnessBounds=RollingWitnessBounds,growth=growth,
        cp=deepcopy(a['current'] if current is None else current),rows=deepcopy(a['rows'][49:] if rows is None else rows),retained_count=49,
        math_state=RollingWitnessBounds.restore(old['math']),possible=deepcopy(old['possible_after']),
        representative={k:deepcopy(a['neutral']['run']['state']['median5'][k]) for k in helper.FIELDS},
        fins={v['session']:deepcopy(v) for v in (a['financial'] if financial is None else financial)},digest=digest,
        total=0,maximum=len(old['possible_after']),cardinalities=[],oracle=deepcopy(a['oracle'] if oracle is None else oracle),
        additional_event_allows=lambda row,item:False)
    exec(compile(data.induction_tree(data.read(data.INDEPENDENT)) if tree is None else tree,'<complete-closed-independent49plus21-induction>','exec'),ns)
    return dict(rows=len(ns['rows']),retained_rows=49,exhaustive_leaves=ns['total'],maximum_possible_states=ns['maximum'],binary64_domain_cardinalities=ns['cardinalities'])

def accounting(a,financial=None):
    parent,current=a['neutral'],a['current'];functions=mature.accounting_functions(a['request'])
    events=mature.inherited_ledger(parent,current);prior=parent['economics'];chain=parent['chain'];previous=parent['source_cursor'];snapshots=0
    with localcontext() as context:
        context.prec=50
        for row in deepcopy(a['financial'] if financial is None else financial):
            need(row['phase']=='MEASURED' and row['input_sha256']==current['run']['input_sha256']
                 and row['economics'].get('measurement_anchor_session')==parent['economics'].get('measurement_anchor_session'),'EXACT_MEASURED_FINANCIAL_INPUT_ANCHOR')
            need(previous<row['session']<=current['source_cursor'],'STRICT21_FINANCIAL_ORDER');previous=row['session']
            for key,valuation in [('opening_accounting','parent_core_open_equity'),('closing_accounting','parent_core_close_equity')]:
                snapshot=row['evidence']['research_entry_audit'][key];n=snapshot['ledger'].pop('event_count')
                need(type(n) is int and 0<=n<=len(events),'EXACT_LEDGER_PREFIX')
                need(snapshot['session']==row['session'] and snapshot['phase']==('OPEN_BEFORE_FILLS' if key=='opening_accounting' else 'CLOSE_AFTER_DECISION'),'EXACT_ACCOUNTING_PHASE')
                snapshot['ledger']['events']=events[:n];functions['reconcile'](snapshot);mature.current_held_marks(snapshot)
                functions['near'](snapshot['resolved_equity'],row['economics'][valuation],'EXACT_RAW_EQUITY');snapshots+=1
            functions['factor'](prior,row);prior=row['economics']
            chain=digest(dict(previous=chain,session=row['session'],state_sha256=row['state_sha256'],economics=row['economics']))
            need(chain==row['chain_sha256'],'EVERY_FINANCIAL_CHAIN')
    need(snapshots==42 and chain==current['chain'] and prior==current['economics'] and previous==current['source_cursor'],'COMPLETE_FINANCIAL_SUFFIX_ENDPOINT')
    return dict(new_rows=21,raw_accounting_snapshots=snapshots,all_raw_marks_cash_shares_receivables_factors_and_chains_verified=True)

def ordinary_tree():
    raw=old_reader.read_bytes();need(sha(raw)=='c55bd3c05dce1100b566f8cb2cce456552c5e84c4927ca8243030f3d507090f0','WHOLE_CLOSED_OBSERVER_DATA_SOURCE')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='ordinary_review')
    class Full17(ast.NodeTransformer):
        hits=merge=reported=0
        def visit_Compare(self,node):
            if ast.unparse(node)=="len(current['repairs']) == 16":
                self.hits+=1;node.comparators[0]=ast.Constant(17)
            return self.generic_visit(node)
        def visit_Assign(self,node):
            if ast.unparse(node)=="terms = inventory['terms']":
                self.merge+=1;node.value=ast.parse("ordinary.merge(inventory['terms'], ordinary.tail_materials(root,current)[0])",mode='eval').body
            return self.generic_visit(node)
        def visit_keyword(self,node):
            if node.arg=='observation_terms' and isinstance(node.value,ast.Constant) and node.value.value==18:
                self.reported+=1;node.value=ast.parse('len(terms)',mode='eval').body
            return self.generic_visit(node)
    change=Full17();fn=change.visit(fn);need(change.hits==change.merge==change.reported==1,'EXACT_THREE_ORDINARY_READER_FULL17_TAIL_SITES')
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))

def inputs_and_observers(a):
    import system_campaign_financial_branches as branch_source
    import system_campaign_bounded_sensor_runtime_v2 as runtime
    import system_campaign_bounded_sensor_origin_v2 as origin
    import system_campaign_bounded_sensor_lifecycle_data as lifecycle
    import system_campaign_bounded_sensor_full_models_v2 as models
    import system_campaign_bounded_sensor_models as visitor
    from system_campaign_bounded_sensor_input import SCHEMA
    from system_campaign_bounded_sensor_lifecycle_data import evidence
    root,current,member=a['root'],a['current'],a['member'];catalog=runtime.catalog();metadata=runtime.metadata()
    selected=models.descriptor(root,current,catalog,evidence(catalog),input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)),root_metadata=metadata)
    need(len(current['repairs'])==17 and selected==current['repairs'][15],'ACTUAL_FULL17_DESCRIPTOR_NO_PROJECTION')
    for d in current['repairs']:need(sha(member('book/repairs/'+d['filename']))==d['sha256'],'ALL17_INPUT_RAW_BYTES')
    typed=lifecycle.validate_document(root/'book/repairs'/selected['filename'],catalog,root_lookup=lambda arm,pin:metadata)
    pause=(C/'system_campaign_pxd_pause.py').read_bytes();need(sha(pause)==a['request']['sources']['system_campaign_pxd_pause.py'],'WHOLE_ORIGINAL_NEUTRAL_ADOPTION_REVIEW')
    original,neutral=origin.validate_bundle(json.loads(member(origin.ORIGIN)),current,catalog,typed,metadata,member,
        input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)),zero_adoption=lambda after,before,doc,earliest:mature.input_zero_adoption(pause,after,before,doc,earliest))
    fn=visitor.visitor_tree((C/'system_campaign_financial_branches.py').read_bytes());scope=dict(vars(branch_source),BOUNDED_SCHEMA=SCHEMA,validated_descriptor=selected)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-full17-input-visitor-DATA>','exec'),scope)
    need(scope['validate_input'](root,current)==original['repairs'][-1]['sha256'],'WHOLE_ORIGINAL_BRANCH_MODEL_IDENTITY')
    ns=dict(vars(data));exec(compile(ordinary_tree(),'<whole-original-observer-DATA-one-full17-count-site>','exec'),ns)
    return dict(full_inputs=17,all_descriptors_bytes_verified=True,actual_typed_origin_verified=True,whole_original_input_visitor=True,
        original_observers=ns['ordinary_review'](root,original,current,member,a['request']))

def review():
    a=actual();current=a['current'];member=a['member'];prefixes={}
    for name,end in current['journals'].items():
        raw=member('book/'+name+'.jsonl');before=a['neutral']['journals'][name]
        need(sha(raw[:before['bytes']])==before['prefix_sha256'] and sha(raw[:end['bytes']])==end['prefix_sha256']
            and sha(raw[:end['bytes']].splitlines(keepends=True)[-1])==end['last_record_sha256'],'ALL_COMMITTED_PREFIXES_AND_FINAL_RECORDS:'+name)
        prefixes[name]=dict(committed_bytes=end['bytes'],tail_bytes=len(raw)-end['bytes'],tail_sha256=sha(raw[end['bytes']:]))
    report=dict(schema='research.P03-FIN340-full17-independent-financial-DATA/1',passed=True,artifact_id=13525097150,
        full_members=209,logical_bytes=142622219,all_member_hashes_verified=True,all620_captured_source_pins_verified=True,
        checkpoint_sha256=current['sha256'],completed=524,source_cursor='2020-01-31',full_inputs=17,
        neutral17_boundary=a['boundary'],branch=branch(a),accounting=accounting(a),inputs_and_observers=inputs_and_observers(a),prefixes=prefixes,
        all70_committed_proof_rows_verified=True,retained49_byteexact=True,raw_proof_rows=a['raw_proof_rows'],
        monthly_reproduction='PENDING_SEPARATE_HOSTED_READONLY',financial_authority=False,root_admitted=False,
        local_canonical_runtime_executed=False,financial_transitions_reexecuted=0)
    raw=enc(report)
    with (D/'P03-FIN340-full17-independent-financial-DATA-v2.json').open('xb') as stream:stream.write(raw)
    print(json.dumps(dict(passed=True,bytes=len(raw),sha256=sha(raw),branch_rows=report['branch']['rows'],snapshots=42)))
if __name__=='__main__':review()
