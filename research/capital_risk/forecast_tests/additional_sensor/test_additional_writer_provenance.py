"""Actual report/admission DATA helpers across stops; no financial book execution."""
import ast
import copy
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).parent))
from test_additional_sensor import C,DEP,data,env,fixture,fence
from test_additional_lifetimes import current_request


def publish_synthetic_metadata_only(env,monkeypatch,prior,typed,index):
    """Keep all real helper guards; substitute declared test-only transport axes."""
    import system_campaign_financial_partial as partial
    entry=copy.deepcopy(prior)
    a,t=entry['admission'],entry['transport']
    t.update(copy.deepcopy(typed),outer_sha256=str(index+2)*64,
             selected_session=('2022-03-31' if index==1 else '2022-04-29'),measured_closes=1047+index)
    a.update(outer_sha256=t['outer_sha256'],source_cursor=t['selected_session'],completed=t['measured_closes'],
             parent_root_admission_sha256=prior['admission_sha256'])
    entry['admission_sha256']=data.sha(data.encoded(a))
    bundle=json.loads((env.overlay/partial.ROOTS).read_bytes())
    bundle['historical_roots'][prior['admission_sha256']]=copy.deepcopy(prior)
    bundle['arms']['P07']=copy.deepcopy(entry)
    (env.overlay/partial.ROOTS).write_bytes(data.encoded(bundle))
    admissions=dict(partial.ADMISSIONS,P07=entry['admission_sha256'])
    clocks=copy.deepcopy(partial.ADMISSION_CLOCKS)
    clocks['P07'][entry['admission_sha256']]=(a['readonly_run_id'],a['readonly_head'])
    monkeypatch.setattr(partial,'ADMISSIONS',admissions)
    monkeypatch.setattr(partial,'ADMISSION_CLOCKS',clocks)
    p=copy.deepcopy(env.p)
    p.update(root_admission_sha256=entry['admission_sha256'],outer_sha256=t['outer_sha256'],
             completed=t['measured_closes'],source_cursor=t['selected_session'],
             adoption_mode='RETAINED',ordinary_input_mode='UNCHANGED',proof_rows=593+index,
             proof_new_rows=1,proof_retained_rows=592+index,origin_record_sha256=data.sha(data.encoded(env.p)))
    policy=env.u.own_policy_catalog()
    closed=dict(env.u.OWN_POLICY_CLOSED_GENERATIONS)
    closed[env.u.OWN_POLICY_SHA]=tuple(policy['phases'])
    policy['phases'][p['root_admission_sha256']]=p
    raw=data.encoded(policy);(env.overlay/env.u.OWN_POLICY_CATALOG).write_bytes(raw)
    monkeypatch.setattr(env.u,'OWN_POLICY_SHA',data.sha(raw))
    monkeypatch.setattr(env.u,'OWN_POLICY_CLOSED_GENERATIONS',closed)
    return entry,p,partial.root_spec('P07',entry['admission_sha256'])


@pytest.fixture
def writer_env(env,monkeypatch):
    import system_campaign_financial_partial as partial
    bundle=json.loads((DEP/partial.ROOTS).read_bytes())
    root=env.p['root_admission_sha256']
    prior=copy.deepcopy(bundle['arms']['P07'] if bundle['arms']['P07']['admission_sha256']==root
                        else bundle['historical_roots'][root])
    (env.overlay/partial.ROOTS).write_bytes(data.encoded(bundle))
    monkeypatch.setattr(partial,'HERE',env.overlay)
    assert partial.root_spec('P07',root)['root_admission_sha256']==root
    return env,prior


def test_actual_typed_writer_authorized_transport_and_reader_across_two_retained_stops(writer_env,monkeypatch):
    env,prior=writer_env
    assert Path(data.__file__).resolve().parent==C.resolve()
    old=data.function(Path(data.__file__).read_bytes(),'report_declaration')
    inserted,=[n for n in old.body if isinstance(n,ast.If) and ast.unparse(n.test)=="p['adoption_mode'] == 'RETAINED'"]
    old.body.remove(inserted)
    assert data.sha(ast.dump(old,include_attributes=False).encode())=='8674076f6b7616b0c7fdb9243845737d19665a0206077f933a83999c10442f02'
    old_namespace=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[old],type_ignores=[])),'<exact-before-fix-writer>','exec'),old_namespace)
    initial=env.u.typed_reporting_declaration(current_request(env,env.p),'P07')
    assert initial['retained_additional_sensor']['root_admission_sha256']==env.p['root_admission_sha256']
    output=copy.deepcopy(initial)
    baseline=None
    for index in (1,2):
        prior,p,spec=publish_synthetic_metadata_only(env,monkeypatch,prior,output,index)
        assert data.selected_declaration(env.root,env.cp,spec)==p
        request=current_request(env,p)
        output=env.u.typed_reporting_declaration(request,'P07')
        assert output==initial
        assert request['selected_research_models']['P07']['root_admission_sha256']==p['root_admission_sha256']
        # The actual selector updates a saved reporting target with typed output
        # before root admission. Its authority seed is A; provenance stays INITIAL.
        report_root=env.root/('report-'+str(index));report_root.mkdir()
        request_raw=data.encoded(request);(report_root/'request.json').write_bytes(request_raw)
        report=dict(arm='P07',**copy.deepcopy(output),request_sha256=data.sha(request_raw),
                    monthly_seed_root_admission_sha256=p['root_admission_sha256'],
                    outer_sha256=str(index+5)*64,measured_closes=p['completed']+1)
        saved=dict(sha256=report['outer_sha256'],completed=report['measured_closes'])
        assert data.selected_declaration(report_root,saved,report)==p
        wrong=dict(report,monthly_seed_root_admission_sha256=env.p['root_admission_sha256'])
        with pytest.raises(ValueError,match='REPORT_EXACT_SAVED_PREFIX_SCOPE'):
            data.selected_declaration(report_root,saved,wrong)
        # Before the fix the writer emitted current A. At B that transported A
        # is neither INITIAL nor current B, although A's generation is closed.
        if index==1:
            baseline=old_namespace['report_declaration'](request,'P07')['retained_additional_sensor']
            assert baseline==request['selected_research_models']['P07'] and baseline!=initial['retained_additional_sensor']
        else:
            assert baseline['root_admission_sha256']!=p['root_admission_sha256']
            broken=dict(spec,retained_additional_sensor=baseline)
            with pytest.raises(ValueError,match='DECLARATION_EXACT'):
                data.selected_declaration(env.root,env.cp,broken)
    assert initial==output


@pytest.mark.parametrize('bad',['missing','current','source','generation'])
def test_actual_writer_refuses_missing_or_altered_initial_transport(writer_env,monkeypatch,bad):
    env,prior=writer_env
    initial=env.u.typed_reporting_declaration(current_request(env,env.p),'P07')
    entry,p,_=publish_synthetic_metadata_only(env,monkeypatch,prior,initial,1)
    import system_campaign_financial_partial as partial
    bundle=json.loads((env.overlay/partial.ROOTS).read_bytes())
    transported=bundle['arms']['P07']['transport']
    if bad=='missing':transported.pop('retained_additional_sensor')
    if bad=='current':transported['retained_additional_sensor']=current_request(env,p)['selected_research_models']['P07']
    if bad=='source':transported['retained_additional_sensor']['source_payload_sha256']='0'*64
    if bad=='generation':transported['retained_additional_sensor']['policy_catalog_sha256']='0'*64
    (env.overlay/partial.ROOTS).write_bytes(data.encoded(bundle))
    # The actual original admission/transport helper still accepts this DATA;
    # only the added declaration-provenance guard must reject the writer.
    assert partial.root_spec('P07',entry['admission_sha256'])['root_admission_sha256']==p['root_admission_sha256']
    with pytest.raises(ValueError,match='PRESERVES_AUTHENTICATED_INITIAL_TRANSPORT'):
        env.u.typed_reporting_declaration(current_request(env,p),'P07')


def test_writer_initial_provenance_guard_removal_is_meaningful(writer_env,monkeypatch):
    env,prior=writer_env
    initial=env.u.typed_reporting_declaration(current_request(env,env.p),'P07')
    entry,p,_=publish_synthetic_metadata_only(env,monkeypatch,prior,initial,1)
    import system_campaign_financial_partial as partial
    bundle=json.loads((env.overlay/partial.ROOTS).read_bytes())
    bundle['arms']['P07']['transport']['retained_additional_sensor']['source_payload_sha256']='0'*64
    (env.overlay/partial.ROOTS).write_bytes(data.encoded(bundle))
    request=current_request(env,p)
    with pytest.raises(ValueError):data.report_declaration(request,'P07')
    fn=data.function(Path(data.__file__).read_bytes(),'report_declaration')
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
            and isinstance(n.args[-1],ast.Constant) and n.args[-1].value=='ADDITIONAL_REPORT_PRESERVES_AUTHENTICATED_INITIAL_TRANSPORT_PROVENANCE']
    call.args[0]=ast.Constant(True)
    namespace=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-report-provenance-guard>','exec'),namespace)
    assert namespace['report_declaration'](request,'P07')['retained_additional_sensor']['source_payload_sha256']=='0'*64
