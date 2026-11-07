"""Original pinned host provider stage and real28-packet preflight before finance."""
import ast,gzip,json,os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_p03_cash14_runtime as runtime
import system_campaign_p03_cash14_data as data
import system_campaign_p03_cash14_api as batch
import system_campaign_p05_remaining_source_preparation as prior
HERE=Path(__file__).parent
ORIGINAL_STAGE=batch.original.stage_selected_sources
PRIOR_PREPARATION_SHA='260cc0d5a9a30deced07bf55b8cbfe8c0b8e4f57e0356f0e146a33126bdefe9e'
def provider_stage_function():
    fn=ORIGINAL_STAGE;phase=('P03','2020-01-31')
    tables=dict(SINGLE_PHASES={('P07','2020-02-28'):batch.original.SINGLE_PHASES['P07','2020-02-28'],phase:('EXACT_P03_CASH14_PROVIDER',)},
        FOLLOWING_PHASES={},ADDITIONAL_SENSOR_ALIAS_PHASES={},ROOT_BOUND_ALIAS_SOURCE_PHASES={phase:(data.ROOT,data.OUTER,524)})
    bound=FunctionType(fn.__code__,dict(fn.__globals__,**tables),fn.__name__,fn.__defaults__)
    data.need(bound.__code__ is fn.__code__,'P03_14_WHOLE_ORIGINAL_PROVIDER_HOST_STAGE_CODE')
    return bound
def stage_provider(spec,old,out):
    runtime.validate_spec(spec);old,out=Path(old),Path(out)
    raw=(old/spec['selected_checkpoint']).read_bytes();data.need(dict(bytes=len(raw),sha256=data.sha(raw))==spec['selected_file'],'P03_14_REAL_AUTHENTICATED_PARENT_BEFORE_PROVIDER_STAGE')
    data.need(not (out/'provider-source').exists(),'P03_14_ONE_ORIGINAL_PROVIDER_STAGE_PER_DESTINATION')
    provider_stage_function()(spec,old,out);proof=batch.provider(out/'provider-source/SHARADAR_ACTIONS.zip')
    batch.original.save(out/'P03-cash14-provider-stage.json',dict(proof,financial_sessions_advanced=0,whole_original_stage_unchanged=True))
def worker_tree():
    raw=Path(prior.__file__).read_bytes();data.need(data.sha(raw)==PRIOR_PREPARATION_SHA,'P03_14_WHOLE_ORIGINAL_HOST_PREFLIGHT_MOUNT_READER_SOURCE')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='preflight_worker_old')
    class Arm(ast.NodeTransformer):
        hits=0
        def visit_Constant(self,node):
            if node.value=='capital-system-resume-p05-preflight-':self.hits+=1;return ast.copy_location(ast.Constant('capital-system-resume-p03-preflight-'),node)
            if node.value=='financial-resume-preflight-P05':self.hits+=1;return ast.copy_location(ast.Constant('financial-resume-preflight-P03'),node)
            return node
    change=Arm();fn=change.visit(fn);data.need(change.hits==2,'P03_14_EXACT_TWO_ORIGINAL_PREFLIGHT_NAME_BINDINGS')
    return ast.fix_missing_locations(fn)
def worker_old(values,name,output,*,run_id,runner_temp):
    ns=dict(vars(prior));exec(compile(ast.Module(body=[worker_tree()],type_ignores=[]),'<whole-original-host-prefight-mount-parser-P03>','exec'),ns)
    return ns['preflight_worker_old'](values,name,output,run_id=run_id,runner_temp=runner_temp)
def prepare_after_preflight(old,out,spec):
    from full_system_core import hosted
    hosted();old,out=Path(old),Path(out);runtime.validate_spec(spec)
    selected=old/spec['selected_checkpoint'];raw=selected.read_bytes();parent=runtime.lifecycle.strict_json(raw);data.parent_contract(parent,spec)
    runtime.observers(old,parent,19)
    from system_campaign_financial_partial import model_context
    with model_context(old,parent,spec):path,loaded=batch.api(parent,spec,provider_root=out).prepare(parent,out,'P03')
    qraw=(out/batch.QUALIFICATION).read_bytes();q=json.loads(qraw)
    data.need(q==dict(passed=True,packet_checks=28,only_terminal_field_changed=True,complete_terms_and_canonical_notional_verified=True,
        original_incomplete_guard_retained=True,wrong_predecessor_and_consumed_date_refused=True,wrong_native_and_delivery_witness_refused=True,financial_sessions_advanced=0),
        'P03_14_ALL_ORIGINAL28_PACKET_CHECKS_AND_NEGATIVE_GUARDS')
    data.need(path==out/batch.OVERLAY and loaded.sha256==data.sha(path.read_bytes()) and loaded.earliest_affected_session=='2020-02-19'
        and selected.read_bytes()==raw,'P03_14_ACTUAL_INPUT_PARSER_BOUNDARY_AND_PARENT_GZIP_UNCHANGED')
    data.need(not any((out/n).exists() for n in ('book/checkpoint.json.gz','book/formation.jsonl','book/daily.jsonl','book/monthly.jsonl')),'P03_14_PREFLIGHT_CANNOT_WRITE_CANONICAL_STATE_OR_JOURNALS')
    result=dict(schema='research.P03-cash14-original28-packet-preparation/1',passed=True,root_admission_sha256=data.ROOT,parent_outer_sha256=data.OUTER,
        packet_checks=28,batch_terms=14,qualification_sha256=data.sha(qraw),overlay_sha256=loaded.sha256,earliest_affected_session='2020-02-19',
        original_parent_unchanged=True,genuine_neutral18_created=False,financial_sessions_advanced=0,canonical_state_written=False)
    batch.original.save(out/runtime.PREPARATION,result);return result
def bind_preflight(original):
    def preflight(old,out,spec):
        request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
        enabled=runtime.request_selected(spec,request)
        result=original(old,out,spec)
        if enabled:prepare_after_preflight(old,out,spec)
        return result
    return preflight
@contextmanager
def launch_context(module,spec,request):
    from probe import check_context
    check_context(os.environ);data.need(runtime.request_selected(spec,request),'P03_14_EXACT_HOST_FINANCIAL_REQUEST_AND_ROOT')
    old_stopped=module.stopped_run;old_stage=batch.original.stage_selected_sources
    def stopped(values,name,output,*a,**k):
        if '/driver/system_campaign_financial_resume.py' in values and '--mode' in values and values[values.index('--mode')+1]=='preflight':
            old=worker_old(values,name,output,run_id=os.environ['GITHUB_RUN_ID'],runner_temp=os.environ['RUNNER_TEMP']);stage_provider(spec,old,Path(output))
        return old_stopped(values,name,output,*a,**k)
    def stage(target,old,out):
        if runtime.selected(target):data.need(target==spec,'P03_14_ONLY_EXACT_SELECTED_ROOT_HOST_STAGE');return stage_provider(target,old,out)
        return old_stage(target,old,out)
    module.stopped_run=stopped;batch.original.stage_selected_sources=stage
    try:yield
    finally:module.stopped_run=old_stopped;batch.original.stage_selected_sources=old_stage
def bind_launch(original,module):
    def launch(args):
        request=json.loads(Path(args.request).read_bytes())
        if args.arm!='P03' or not request.get(runtime.FIELD):return original(args)
        spec=module.root_spec('P03')
        with launch_context(module,spec,request):return original(args)
    return launch
