"""Finite host-only seal/stop wrappers; original worker and launcher bodies stay whole."""
import ast,json,os,re,types
from pathlib import Path
from system_campaign_p07_lossless_export import (FIELD,ROOT,SEAL_SHA,TEMPLATE_SHA,diagnostics,
    digest,encoded,linked,need,pin,safe_diagnostics,seal_represented,sha)

HERE=Path(__file__).parent
QUALIFICATION='P07-lossless-export-qualification.json'
SOURCE_NAMES=('system_campaign_p07_lossless_export.py','system_campaign_p07_lossless_export_host.py',
              'P07-codec-copy-inventory-template.json',QUALIFICATION)
def declaration():
    raw=(HERE/QUALIFICATION).read_bytes();value=json.loads(raw)
    need(value['passed'] is True and value['financial_runtime_executed'] is False,'CLOSED_PRIVATE_QUALIFICATION')
    need(set(value['runtime_files'])==set(SOURCE_NAMES)-{QUALIFICATION},'COMPLETE_EXACT_THREE_RUNTIME_FILE_GATE')
    for name,expected in value['runtime_files'].items():need(pin(HERE/name)==expected,'EXACT_QUALIFIED_RUNTIME_SOURCE')
    return dict(schema='research.P07-lossless-codec-export-selection/1',root_admission_sha256=ROOT,
        template_sha256=TEMPLATE_SHA,qualification_sha256=sha(raw),export_cap_changed=False,
        financial_source_changed=False,per_file_copy_equivalence_required=True)
def source_names():return SOURCE_NAMES
def bind_expected_request(original):
    def expected():
        value=original()
        # Only the already selected original d9 VIVO continuation may opt in.
        selected=value.get('selected_p07_vivo_ordinary25',{}).get('P07')
        if not (selected and value.get('execution_mode')=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
                and value.get('financial_resume_authorized') is True and 'P07' in value.get('arms',[])):
            return value
        need(selected['root_admission_sha256']==ROOT,'FINITE_EXISTING_VIVO_ROOT_SELECTION')
        value=dict(value,sources=dict(value['sources']));value[FIELD]=declaration()
        for name in source_names():
            actual=pin(HERE/name)['sha256']
            need(name not in value['sources'] or value['sources'][name]==actual,'NO_EXISTING_SOURCE_PIN_REPLACEMENT')
            value['sources'][name]=actual
        return value
    return expected
def publish(public_path,records,output_root=None):
    """Only safe aggregates enter the existing public receipt."""
    need(records and Path(public_path).is_file(),'EXISTING_PUBLIC_RECEIPT_REQUIRED')
    need(not linked(public_path) and (output_root is None or not Path(public_path).resolve().is_relative_to(Path(output_root).resolve())),
         'PUBLIC_DIAGNOSTICS_OUTSIDE_FINANCIAL_INPUT_TREE')
    original=Path(public_path).read_bytes();value=json.loads(original)
    need(value['arm']=='P07' and value['performance_admitted'] is False,'EXACT_UNADMITTED_P07_PUBLIC_RECEIPT')
    value['p07_export_diagnostics']=records
    target=Path(str(public_path)+'.p07-export-diagnostics.tmp')
    created=False
    try:
        with target.open('xb') as stream:created=True;stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
        need(Path(public_path).read_bytes()==original,'PUBLIC_RECEIPT_UNCHANGED_BEFORE_ATOMIC_REPLACE')
        os.replace(target,public_path);created=False
    finally:
        if created:target.unlink()
class Tracker:
    def __init__(self,original,run_id):self.original=original;self.run_id=run_id;self.records=[]
    def __call__(self,*args,**kwargs):
        argv,name,output=args[:3]
        match=re.fullmatch('capital-system-resume-p07-(preflight|worker|review)-'+self.run_id+'-1',name)
        need(match is not None,'EXACT_CURRENT_P07_WRITER_NAME')
        role='economic' if match[1]=='worker' else match[1]
        record=dict(role=role,returned=False);self.records.append(record)
        result=self.original(*args,**kwargs)
        record.update(returned=True,result=result,inspection=None,inspection_sha256=None)
        try:
            inspection_path=Path(output)/'worker-inspect.json';inspection=json.loads(inspection_path.read_bytes())
            record.update(inspection=inspection,inspection_sha256=digest(inspection))
        except Exception:pass  # Observation failure forbids representation, preserving the original result.
        return result
def bound_sources(m,request):
    original=m.seal;stop=m.stopped_run
    need(pin(m.__file__)['sha256']==request['sources']['system_campaign_financial_resume.py'],'EXACT_HOST_DRIVER_SOURCE')
    need(type(original) is types.FunctionType and original.__globals__.get('seal') is original
         and pin(original.__code__.co_filename)['sha256']==SEAL_SHA==request['sources']['full_system_trials_job.py'],
         'WHOLE_ORIGINAL_SEAL_SOURCE_AND_FUNCTION_OWNER')
    need(type(stop) is types.FunctionType and stop.__globals__.get('stopped_run') is stop
         and pin(stop.__code__.co_filename)['sha256']==request['sources']['alpaca_fit_job.py'],
         'WHOLE_ORIGINAL_STOP_SOURCE_AND_FUNCTION_OWNER')
    for function,name in ((original,'seal'),(stop,'stopped_run')):
        # Compile, never execute, the WHOLE original module. Its import/symbol
        # context affects bytecode even when this function's AST is identical.
        raw=Path(function.__code__.co_filename).read_bytes()
        module=compile(raw,function.__code__.co_filename,'exec',dont_inherit=True)
        expected,=[v for v in module.co_consts if isinstance(v,types.CodeType) and v.co_name==name]
        need(function.__code__==expected,'WHOLE_ORIGINAL_FUNCTION_CODE_EQUALS_PHYSICAL_SOURCE')
    return original,stop
def bind_launch(m):
    original_launch=m.launch
    def launch(args):
        request=json.loads(Path(args.request).read_bytes())
        if args.arm!='P07' or FIELD not in request:return original_launch(args)
        need(request[FIELD]==declaration() and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
             and request['financial_resume_authorized'] is True and request['readonly_partial_review'] is False
             and request.get('readonly_source_witnesses',False) is False,'EXACT_FINITE_P07_FINANCIAL_DECLARATION')
        spec=m.root_spec('P07')
        need(spec['root_admission_sha256']==ROOT and spec['outer_sha256']=='1e1e4dbce5a3b13c329bfb2c16a99e6f6043bcc8628a9852971f7100d9295a3a'
             and spec['measured_closes']==1259 and len(spec['repairs'])==24,'ONLY_REAL_ORIGINAL1259_FULL24_PARENT')
        original_seal,original_stop=bound_sources(m,request)
        run_id=os.environ['GITHUB_RUN_ID'];need(re.fullmatch('[0-9]+',run_id) is not None,'REAL_CURRENT_RUN_ID')
        tracker=Tracker(original_stop,run_id);records=[]
        expected_root=Path(os.environ['RUNNER_TEMP'])/'financial-resume-output-P07'
        def log_safe(value):
            try:print(json.dumps(value,sort_keys=True),flush=True)
            except Exception:pass
        def publish_safe():
            try:publish(args.output,records,expected_root)
            except Exception:log_safe(dict(p07_export_diagnostics_write_failed=True))
        def emit(root,phase,status):
            value=safe_diagnostics(root,reader=diagnostics)
            value.update(phase=phase,representation_status=status);records.append(value)
            log_safe(dict(p07_export_diagnostics=value))
            publish_safe()
        def seal(root,*a,**kw):
            # The original synthetic zero-session export probe stays exact.
            if Path(root).resolve()!=expected_root.resolve():return original_seal(root,*a,**kw)
            need(kw.get('stage')=='campaign-factual-suffix' and len(a)>=4 and a[3]=='P07','EXACT_EXISTING_FINANCIAL_SEAL_CALL')
            emit(root,'BEFORE','NOT_ATTEMPTED')
            try:
                # Validate before changing anything; refusal falls back to whole
                # original export with every byte still physical.
                from system_campaign_p07_lossless_export import plan
                plan(root,tracker.records)
            except Exception:
                emit(root,'UNREPRESENTED','REFUSED')
                return original_seal(root,*a,**kw)
            def observe(value):emit(root,'PHYSICAL_REPRESENTATION','VALIDATED')
            try:return seal_represented(root,original_seal,a,kw,tracker.records,observe=observe)
            finally:emit(root,'RESTORED','TRANSACTION_FINISHED')
        m.stopped_run=tracker;m.seal=seal
        try:return original_launch(args)
        finally:
            m.seal=original_seal;m.stopped_run=original_stop
            if records:publish_safe()
    return launch
