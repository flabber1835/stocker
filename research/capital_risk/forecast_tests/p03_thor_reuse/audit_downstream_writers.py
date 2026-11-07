import ast,json
from pathlib import Path
from forecast_tests.p03_thor_reuse import review_FIN337_DATA as actual
from system_campaign_uncertainty_archive import resolve
from system_campaign_bounded_sensor_suffix_v2 import actual_archive
D=Path('C:/GitHub/stocker/.codex-tmp/p03-fin337-thor-qualified-reuse-20261106')
def audit():
    root,members,member,spec,parent,neutral,seed,qualified,boundary=actual.read()
    oldcap=actual.R/'financial324-source-snapshot/capture-P03-13476494369-001'
    old=actual.long(oldcap/'verified-output');oldmanifest=json.loads((oldcap/'authenticated-manifest.json').read_bytes())['members']
    for n,pin in oldmanifest.items():
        raw=(old/n).read_bytes();assert dict(bytes=len(raw),sha256=actual.sha(raw))==pin,n
    assert (old/spec['selected_checkpoint']).read_bytes()==member(actual.thor.SELECTED)
    assert (old/'branch-controller-qualification.json').read_bytes()==qualified
    assert (old/'uncertainty-certificate.jsonl').read_bytes()==member(actual.thor.RAW_PROOF)
    alder,proof=resolve(old);alder_target='book/pre-event/'+alder.name
    event=actual.thor.typed.catalog()['event'];row,=[r for r in seed if r['session']==event['effective_session']]
    dova,raw,_=actual_archive(old,row,actual.thor.typed.catalog());dova_target='book/pre-event/'+dova.name
    absent=['retained-proof-admission/alder-source.json','retained-proof-admission/seed.json',
        actual.thor.uncertainty.UNCHANGED_INPUT,'uncertainty-certificate.jsonl','uncertainty-event-archive-preservation.json',alder_target,dova_target]
    assert all(n not in members for n in absent)
    assert not any(n=='retained-proof-admission' or n.startswith('retained-proof-admission/') for n in members)
    u_raw=(actual.C/'system_campaign_financial_uncertainty.py').read_bytes();tree=ast.parse(u_raw)
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_retained']
    with_node,=[n for n in fn.body if isinstance(n,ast.With) and 'branch-controller-qualification.json' in ast.unparse(n)]
    assert ast.unparse(with_node.items[0].context_expr)=="(out / 'branch-controller-qualification.json').open('xb')"
    binding=(actual.C/'system_campaign_bounded_sensor_binding.py').read_bytes()
    ctor,=[n for n in ast.walk(ast.parse(binding)) if isinstance(n,ast.FunctionDef) and n.name=='__init__']
    need_call,=[n for n in ast.walk(ctor) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need']
    assert need_call.args[1].value=='PRIOR_COMMITTED_B19_SEED'
    assert ast.unparse(need_call.args[0])=="self.seed and self.seed[-1]['session'] < event['native_session']"
    assert seed[-1]['session']=='2019-12-31' and seed[-1]['session']>=event['native_session']
    result=dict(schema='research.P03-FIN337-complete-downstream-writer-audit/1',passed=True,financial_authority=False,
        local_canonical_runtime_executed=False,financial_sessions_advanced=0,all337_members_hashed=182,all324_original_members_hashed=len(oldmanifest),
        original_current_parent_and_full_proof_bytes_equal=True,
        existing_exclusive_writer_collision=dict(name='branch-controller-qualification.json',bytes=len(qualified),sha256=actual.sha(qualified)),
        exclusive_directory_absent='retained-proof-admission',subsequent_new_resource_names_absent=absent,
        original_archive_preserve_target=dict(name=alder_target,old_actual_name=alder.relative_to(old).as_posix(),old_pin=oldmanifest[alder.relative_to(old).as_posix()]),
        original_DOVA_preserve_target=dict(name=dova_target,old_actual_name=dova.relative_to(old).as_posix(),old_pin=oldmanifest[dova.relative_to(old).as_posix()],writer='existing exact() helper'),
        projection_for_P03='original P07-specific initial_context returns nullcontext; qualify_initial returns without writing',
        original_Certificate_construction_must_remain=True,original_Certificate_exclusive_stream_path_absent=True,
        known_retained_constructor_blocker=dict(guard='PRIOR_COMMITTED_B19_SEED',actual_seed_last='2019-12-31',already_consumed_native=event['native_session'],original_predicate=False),
        blanket_IO_or_overwrite_changes_authorized=False,downstream_actual_financial_and_review_positive_unknown=True)
    return result
if __name__=='__main__':
    value=audit();raw=actual.enc(value)
    with (D/'P03-FIN337-downstream-writer-audit.json').open('xb') as s:s.write(raw)
    print(json.dumps(dict(passed=True,sha256=actual.sha(raw),absent_writer_targets=len(value['subsequent_new_resource_names_absent']),old_members=value['all324_original_members_hashed'],constructor_guard_also_requires_finite_fix=True)))
