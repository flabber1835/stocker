"""Hosted actual24-to25 adoption,805 seed bridge and unchanged financial runtime."""
import ast,gzip,json,shutil,stat,tempfile
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_financial_uncertainty as uncertainty
import system_campaign_financial_future as future
import system_campaign_ordinary_augmentation_data as ordinary
import system_campaign_p07_abmd_lifecycle as initial_lifecycle
import system_campaign_p07_vivo_data as data
import system_campaign_p07_vivo_api as input_api
import system_campaign_p07_vivo_boundary as boundary
import system_campaign_p07_vivo_retained as retained
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json

HERE=Path(__file__).parent
FIELD='selected_p07_vivo_ordinary25'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
QUALIFICATION='P07-VIVO25-private-runtime-qualification.json'
BOUNDARY_REVIEW='p07-vivo-ordinary25-neutral-boundary-review.json'
OBSERVATION='p07-vivo-ordinary25-observation'

def selected(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P07' and spec.get('root_admission_sha256')==data.ROOT

def qualification():
    raw=(HERE/QUALIFICATION).read_bytes();q=json.loads(raw)
    data.need(q['schema']=='research.P07-VIVO25-private-runtime-qualification/1' and q['passed'] is True
         and q['root_admission_sha256']==data.ROOT and q['source335_qualification_sha256']==data.QUALIFICATION_SHA
         and q['local_canonical_runtime_executed'] is q['financial_authority'] is q['input_adopted'] is False
         and q['hosted_genuine_neutral_adoption_and_packet_qualification_required'] is True
         and q['tests']['passed']>=50 and q['tests']['whole_source_undo'] is True
         and q['tests']['meaningful_guard_removals']>=5
         and set(q['files'])==(set(source_names())|{'system_campaign_p07_vivo_profile.py'})-{QUALIFICATION}
         and all(dict(bytes=len((HERE/n).read_bytes()),sha256=data.sha((HERE/n).read_bytes()))==pin for n,pin in q['files'].items()),
         'VIVO_CLOSED_PRIVATE_PROFILE_QUALIFICATION_REQUIRED_BEFORE_REQUEST_OR_ACTIVATION')
    return raw,q

def declaration(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);data.need(selected(spec),'VIVO_ONLY_EXACT_REAL_ADMITTED1259_ROOT')
    qraw,q=qualification();catalog=data.catalog()
    return dict(schema='research.P07-VIVO1-genuine-ordinary25-declaration/1',arm='P07',root_admission_sha256=data.ROOT,
        original_outer_sha256=data.OUTER,original_inputs=24,required_actual_neutral_inputs=25,old_committed_proof_rows=805,
        source335_qualification_sha256=data.QUALIFICATION_SHA,catalog_file=data.CATALOG,catalog_sha256=data.sha(data.encoded(catalog)),
        profile_qualification_file=QUALIFICATION,profile_qualification_sha256=data.sha(qraw),cash_terms=23,existing_legal_terms=22,
        genuine_neutral_adoption_required=True,original_canonical_financial_source_changed=False,provider_metadata_upgraded=False,
        actual_future_neutral_checkpoint_known=False,future25_root_restart_selected=False)

def request_selected(spec,request):
    return (selected(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
        and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False
        and request.get(FIELD,{}).get('P07')==declaration(spec))

def require_request(spec,request):
    data.need(request_selected(spec,request),'VIVO_FINANCIAL_PROFILE_EXPLICIT_TRUTHFUL_QUALIFIED_DECLARATION_REQUIRED')
    data.need(request['admitted_checkpoints']['P07']==data.OUTER
         and 'P07' in request['arms'] and type(request['maximum_parallel_financial_workers']) is int
         and 1<=request['maximum_parallel_financial_workers']<=4
         and request['maximum_parallel_readonly_workers']==0
         and request.get('selected_p07_composite_source_bridges',{})=={}
         and request['arm_inputs']['P07']==dict(new_factual_overlay=True,restored_correlation=False),
         'VIVO_FINANCIAL_PROFILE_ACTUAL24_SEED_NEW_ORDINARY25_REQUEST_CLOCK')
    return True

def source_names():return (Path(__file__).name,*input_api.source_names(),*retained.source_names(),QUALIFICATION)

def adoption_tree(raw):
    data.need(data.sha(raw)==retained.U_SHA,'VIVO_WHOLE_ORIGINAL_PAUSED_ADOPTION_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
    mapping,=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    data.need(isinstance(mapping,ast.Dict) and [ast.unparse(k) for k in mapping.keys]==['ORDINARY_ADOPTION','DATE_ADOPTION','MODEL_ADOPTION']
         and [ast.unparse(v) for v in mapping.values]==["'future-financial-overlay.json'",'DATE_OVERLAY',"'branch-uncertainty-input.json'"],
         'VIVO_ONE_ORIGINAL_NEUTRAL_ADOPTION_FILENAME_MAP')
    mapping.keys.append(ast.Constant(boundary.DIRECTORY));mapping.values.append(ast.Constant(boundary.OVERLAY))
    return ast.fix_missing_locations(fn)

def adopter():
    scope=dict(vars(uncertainty))
    exec(compile(ast.Module(body=[adoption_tree(Path(uncertainty.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-paused-adoption-one-VIVO25-filename>','exec'),scope)
    return scope['paused_own_adoption']

def original_seed(old,parent,spec):
    baseline=retained.seed_reader(parent,spec)(old,parent,spec);plan=data.identity_plan()
    raw=(Path(old)/'uncertainty-certificate.jsonl').read_bytes();lines=raw.splitlines(keepends=True)
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==plan['original_entire_file']
         and len(lines)==824 and len(baseline[1])==805
         and all(json.loads(v)['session']>parent['source_cursor'] for v in lines[805:])
         and dict(bytes=len(b''.join(lines[:805])),sha256=data.sha(b''.join(lines[:805])))==plan['committed_prefix'],
         'VIVO_ALL805_COMMITTED_PREFIX_EXCLUDE_AND_PRESERVE19_UNADMITTED_JANUARY_TAILS')
    return baseline

def resources(parent,neutral):
    return [*data.source_names(),boundary.SELECTED,boundary.RAW_PROOF,boundary.OVERLAY,boundary.QUALIFICATION,
        boundary.DIRECTORY+'/checkpoint.json.gz',boundary.DIRECTORY+'/proof.json',boundary.DIRECTORY+'-correlation-inputs.jsonl.gz',
        future.hydration_name(parent),'book/repairs/'+neutral['repairs'][24]['filename']]

def boundary_review(root,parent,spec,rows):
    neutral=strict_json((Path(root)/boundary.DIRECTORY/'checkpoint.json.gz').read_bytes())
    result=boundary.relation(parent,neutral,spec,lambda n:(Path(root)/n).read_bytes(),rows)
    api=input_api.api(parent,spec);earliest=min(t['native_session'] for t in data.catalog()['terms'])
    data.need(api.review_input(parent,Path(root),'P07')==earliest,'VIVO_FULL_SOURCE_AND_DOCUMENT_RECONSTRUCTION_BEFORE_FINANCIAL')
    material=json.loads((Path(root)/future.hydration_name(parent)).read_bytes())
    data.need(material['terms']==data.catalog()['terms'],'VIVO_EXACT23_TERMS_NO_IMPLICIT_OTHER_INPUT')
    summary={k:v for k,v in result.items() if k not in ('parent','neutral')}
    summary.update(original_parent_outer_sha256=parent['sha256'],actual_neutral_outer_sha256=neutral['sha256'],
        original_root_admission_sha256=data.ROOT,original_inputs=24,current_inputs=25,all_original_state_journals_and_stats_unchanged=True)
    return neutral,summary

def owned_view_permissions(view,owned,output):
    """Validate every target before permitting writes to this owned copy only."""
    view,owned,output=Path(view),Path(owned),Path(output)
    root,owner,parent=view.resolve(),owned.resolve(),output.resolve()
    data.need(not view.is_symlink() and not owned.is_symlink() and view.is_dir()
         and root==owner/'view' and owner.parent==parent and owner.name.startswith('p07-vivo-owned-seed-view-'),
         'VIVO_PERMISSION_TARGET_ONLY_EXPLICIT_OWNED_OUTPUT_VIEW')
    members=[view,*view.rglob('*')]
    data.need(all(not path.is_symlink() and path.resolve().is_relative_to(root) for path in members),
         'VIVO_ALL_PERMISSION_TARGETS_WITHIN_OWNED_VIEW_NO_SYMLINKS')
    directories=[path for path in members if path.is_dir()];watch=view/'book/watch.jsonl'
    data.need(watch.is_file() and not watch.is_symlink() and watch.resolve().is_relative_to(root),
         'VIVO_ONLY_ACTUAL_COPIED_NEUTRAL_WATCH_FILE_WRITABLE')
    for path in directories:path.chmod(stat.S_IMODE(path.stat().st_mode)|stat.S_IWUSR|stat.S_IXUSR)
    watch.chmod(stat.S_IMODE(watch.stat().st_mode)|stat.S_IWUSR)
    return dict(owned_directories=len(directories),only_owner_write_search_added=True,
        only_copied_neutral_watch_file_write_added=True,original_source_permissions_changed=False)

@contextmanager
def seed_view(old,out,parent,neutral,spec,evidence,rows):
    from full_system_core import hosted
    hosted()
    old,out,evidence=Path(old),Path(out),Path(evidence)
    original=(old/spec['selected_checkpoint']).read_bytes()
    data.need(dict(bytes=len(original),sha256=data.sha(original))==spec['selected_file'] and strict_json(original)==parent,
         'VIVO_SELECTED_ORIGINAL24_GZIP_NEVER_REPLACED_WITH_NEUTRAL25')
    boundary.relation(parent,neutral,spec,lambda n:(evidence/n).read_bytes(),rows)
    with tempfile.TemporaryDirectory(prefix='p07-vivo-owned-seed-view-',dir=out) as owned:
        view=Path(owned)/'view';shutil.copytree(old,view);added={}
        permissions=owned_view_permissions(view,owned,out)
        for name in resources(parent,neutral):
            raw=(evidence/name).read_bytes();exact(view/name,raw);added[name]=dict(bytes=len(raw),sha256=data.sha(raw))
        watch=(evidence/'book/watch.jsonl').read_bytes();n=neutral['journals']['watch']['bytes']
        data.need(data.sha(watch[:n])==neutral['journals']['watch']['prefix_sha256'],'VIVO_SEED_VIEW_REAL_NEUTRAL_WATCH_PREFIX')
        (view/'book/watch.jsonl').write_bytes(watch[:n])
        data.need((view/spec['selected_checkpoint']).read_bytes()==original,'VIVO_SEED_VIEW_STILL_SELECTS_EXACT_ORIGINAL24_GZIP')
        exact(out/boundary.ORIGIN/'temporary-seed-view-receipt.json',data.encoded(dict(passed=True,selected_checkpoint_replaced=False,
            actual_added_files=added,owned_copy_permissions=permissions,original_watch_sha256=data.sha((old/'book/watch.jsonl').read_bytes()),
            actual_neutral_watch_sha256=data.sha(watch[:n]),financial_sessions_advanced=0)))
        yield view
    data.need(not Path(owned).exists(),'VIVO_TEMPORARY_HOSTED_SEED_VIEW_CLEANUP_OBSERVED')
    exact(out/boundary.ORIGIN/'temporary-seed-view-cleanup.json',data.encoded(dict(passed=True,
        temporary_owned_view_removal_observed=True,original24_and_actual_neutral25_archives_preserved=True,financial_sessions_advanced=0)))

def runtime(root,neutral,parent,spec,evidence,rows,baseline):
    whole=retained.seed_reader(parent,spec,neutral=neutral,evidence=evidence,rows=rows)
    def seed(where,current,target):
        data.need(Path(where)==Path(root) and current==neutral and target==spec,'VIVO_ONLY_INVENTORIED_REAL_NEUTRAL805_SEED_VIEW')
        actual=whole(where,current,target)
        data.need(actual==baseline,'VIVO_WHOLE_NEUTRAL25_SEED_EQUALS_INDEPENDENT_ORIGINAL24_805_SEED')
        return actual
    api=retained.runtime_api(root,neutral,spec,parent,seed);ns=api.run.__globals__;old=ns['ordinary_observers']
    selected_api=input_api.api(parent,spec)
    @contextmanager
    def observers(where,out,p,cp0):
        event=future.ActualEvents.__new__(future.ActualEvents);init=future.ActualEvents.__init__
        bound=FunctionType(init.__code__,dict(init.__globals__,OVERLAY=boundary.OVERLAY,source_scopes=selected_api.source_scopes),
            init.__name__,init.__defaults__);bound.__kwdefaults__=deepcopy(init.__kwdefaults__)
        bound(event,Path(where),'P07',cp=parent)
        data.need(event.scopes==[] and len(event.terms)==23 and all(t['kind']=='CASH_MERGER' for t in event.terms.values()),
             'VIVO_WHOLE_ORIGINAL_ACTUAL_OBSERVER_COMPLETE23_CASH_ONLY_TERMS')
        event.out=Path(out)/OBSERVATION;event.out.mkdir(exist_ok=True)
        with old(where,out,p,cp0) as prior:
            with event:yield prior
    ns['ordinary_observers']=observers
    return SimpleNamespace(**ns)

def run(parent,out,args,rows,observer,execution,spec,old):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    data.parent_contract(parent,spec);old,out=Path(old),Path(out);baseline=original_seed(old,parent,spec)
    source=initial_lifecycle.runtime_api(old,parent,spec,initial_lifecycle.catalog());source.preserve(old,parent,out,spec)
    for name in data.source_names():exact(out/name,(HERE/name).read_bytes())
    exact(out/boundary.SELECTED,(old/spec['selected_checkpoint']).read_bytes())
    exact(out/boundary.RAW_PROOF,(old/'uncertainty-certificate.jsonl').read_bytes())
    api=input_api.api(parent,spec);path,loaded=api.prepare(parent,out,'P07')
    data.need(path==out/boundary.OVERLAY and loaded.earliest_affected_session=='2023-01-30',
         'VIVO_GENUINE_PREPARED23_TERM_ORDINARY25_INPUT_JAN30_EARLIEST')
    neutral=adopter()(parent,out,args,rows,path,loaded.earliest_affected_session,boundary.DIRECTORY)
    actual,proof=boundary_review(out,parent,spec,rows);data.need(actual==neutral,'VIVO_REAL_CANONICAL_NEUTRAL25_BEFORE_FINANCIAL_MAIN')
    exact(out/BOUNDARY_REVIEW,data.encoded(proof))
    with seed_view(old,out,parent,neutral,spec,out,rows) as view:
        bounded=runtime(view,neutral,parent,spec,out,rows,baseline)
        code=bounded.run_retained(neutral,out,args,rows,observer,execution,spec,view,initial_lifecycle.phase(spec))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    data.need(current['repairs']==neutral['repairs'] and current['run']['input_sha256']==neutral['run']['input_sha256'],
         'VIVO_FINANCIAL_SUFFIX_FULL25_HISTORY_UNCHANGED_AFTER_ACTUAL_ADOPTION')
    return code

def cash_tree(raw):
    fn=ordinary.cash_tree(raw)
    retained.models.replace_count(fn,"record['order'] == ['CASH:' + sid]",
        "record['order'] == ['CASH:' + t['security_id'] for t in same_day_terms(term)]",1,'VIVO_CASH_FULL_SAME_DAY_ORDER_GUARD')
    retained.models.replace_count(fn,"len(record['cash']) == 1","len(record['cash']) == len(same_day_terms(term))",1,'VIVO_CASH_FULL_SAME_DAY_ARRAY_GUARD')
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='c']
    data.need(ast.unparse(assignment.value)=="record['cash'][0]",'VIVO_CASH_ONE_ORIGINAL_CASH_ROW_SELECTOR')
    selector=ast.parse("c,=[v for v in record['cash'] if v['security_id']==sid and v['session']==day]").body[0]
    fn.body[fn.body.index(assignment)]=selector
    return ast.fix_missing_locations(fn)

def review_cash(evidence,current,out):
    from system_campaign_uncertainty_review import committed_rows
    terms=data.catalog()['terms'];reached=[t for t in terms if t['added']['session']<=current['source_cursor']]
    observed={}
    for path in (Path(evidence)/OBSERVATION).glob('actual-future-event-20*.json'):
        day=path.stem.removeprefix('actual-future-event-')
        if day<=current['source_cursor']:observed[day]=json.loads(path.read_bytes())
    data.need(set(observed)=={t['added']['session'] for t in reached},'VIVO_ALL_REACHED23_CASH_EVENTS_REQUIRE_COMPLETE_ACTUAL_OBSERVER_RECORDS')
    name='system_campaign_ordinary_augmentation_cash_v1.py';raw=(ordinary.HERE/name).read_bytes()
    data.need(data.sha(raw)==ordinary.catalog()['source_files'][name],'VIVO_WHOLE_ORIGINAL_INDEPENDENT_CASH_REVIEW_SOURCE')
    scope=dict(D=Decimal,need=data.need,same_day_terms=lambda term:sorted(
        [t for t in terms if t['added']['session']==term['added']['session']],key=lambda t:(t['security_id'],t['added']['kind'])))
    exec(compile(ast.Module(body=[cash_tree(raw)],type_ignores=[]),'<whole-cash-review-full-same-day-record-and-exact-SID-selector>','exec'),scope)
    rows=committed_rows(Path(evidence)/'book',current,'daily');events=current['run']['state']['ledger']['events'];checked=[]
    by_sid={t['security_id']:t for t in terms}
    data.need(all(e['session']==by_sid[e['security_id']]['added']['session']
         for e in events if e['event_type']=='CASH_MERGER' and e['security_id'] in by_sid and e['session']>'2022-12-30'),
         'VIVO_NO_EARLY_OR_WRONG_DATE_COMMON_CASH_PAYMENTS_IN_NEW_FINANCIAL_SUFFIX')
    for term in reached:
        day=term['added']['session'];i,=[i for i,r in enumerate(rows) if r['session']==day]
        data.need(i>0,'VIVO_CASH_PRIOR_CLOSING_ACCOUNTING_REQUIRED')
        checked.append(scope['verify_event'](observed[day],term,rows[i-1]['evidence']['research_entry_audit']['closing_accounting'],
            rows[i]['evidence']['research_entry_audit']['opening_accounting'],events))
    exact(Path(out)/'p07-vivo-ordinary25-cash-review.json',data.encoded(dict(passed=True,events=checked,
        complete_observer_records_preserved=True,financial_sessions_reexecuted=0,actual_quantities_and_original_operation_order_verified=True)))
    return checked

def review(parent,evidence,out,spec,old):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_financial_resume import seed_rows
    old,evidence,out=Path(old),Path(evidence),Path(out);data.parent_contract(parent,spec)
    rows=seed_rows(old,parent,spec);baseline=original_seed(old,parent,spec)
    neutral,proof=boundary_review(evidence,parent,spec,rows)
    data.need(json.loads((evidence/BOUNDARY_REVIEW).read_bytes())==proof,'VIVO_INDEPENDENT_GENUINE_NEUTRAL25_BOUNDARY_REVIEW')
    with seed_view(old,out,parent,neutral,spec,evidence,rows) as view:
        bounded=runtime(view,neutral,parent,spec,evidence,rows,baseline)
        bounded.review(neutral,evidence,out,spec,view)
    current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz');review_cash(evidence,current,out)
    exact(out/BOUNDARY_REVIEW,data.encoded(proof))

def api(root,cp,spec):
    from full_system_core import hosted
    hosted()
    data.need(selected(spec),'VIVO_RUNTIME_ONLY_EXACT_ADMITTED1259_ENTRY')
    if len(cp['repairs'])==24:
        data.parent_contract(cp,spec);base=initial_lifecycle.runtime_api(root,cp,spec,initial_lifecycle.catalog())
    else:
        data.need(len(cp['repairs'])==25,'VIVO_RUNTIME_NO_UNQUALIFIED_FUTURE_INPUT_GENERATION')
        base=retained.lifecycle().runtime_api(root,cp,spec,initial_lifecycle.catalog())
    return SimpleNamespace(**dict(vars(base),run=run,review=review))
