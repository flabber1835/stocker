"""Hosted-only entrypoint restoring the exact admitted diagnostic runtime."""
import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_discovery_context import require_strict_checkpoint, digest
from system_campaign_parallel_discovery import check_parent
from system_campaign_parallel_discovery_run import retained_inputs
from system_campaign_discovery_suffix_parent import specification, validate_contents
from system_campaign_discovery_suffix_replay import Anchors, replay


def bind_checkpoint(value, context, spec):
    value = deepcopy(value)
    if spec['arm'] in ('P09','P11'):
        policy = context.policy_commitment()
        if policy is not None: value['diagnostic_policy'] = policy
    if spec['arm'] == 'P10':
        value.update(schema=spec['checkpoint_schema'],input_descriptors=spec['input_descriptors'],
            diagnostic_input_epoch=spec['diagnostic_input_epoch'],
            original_diagnostic_checkpoint_sha256=spec['original_diagnostic_checkpoint_sha256'],
            source_binding_sha256=spec['source_binding_sha256'])
        value.pop('sha256',None)
        value['sha256'] = digest(value)
    return value


def selected_tree(raw, spec):
    from system_campaign_discovery_suffix_replay import suffix_tree
    tree = suffix_tree(raw)
    execution, = [n for n in ast.walk(tree) if isinstance(n,ast.Call) and ast.unparse(n.func) == 'Execution']
    need(ast.unparse(execution) == "Execution('FAST', signal_closes=1)", 'SUFFIX_ONE_NATIVE_TRANSPORT_SITE')
    execution.keywords[0].value = ast.Constant(spec['native_horizon'])
    cp, = [n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name == 'checkpoint']
    at, = [i for i,n in enumerate(cp.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
           and ast.unparse(n.value.func) == 'journal.write_checkpoint']
    cp.body[at:at] = ast.parse('value=bind_selected_checkpoint(value,context)').body
    return ast.fix_missing_locations(tree)


def continued_replay(*args, spec, **kwargs):
    """Select only transport, existing input codec and diagnostic carrier sites."""
    import system_campaign_discovery_suffix_replay as common
    from system_campaign_parallel_discovery import compile_body
    fn, = [n for n in ast.parse(Path(common.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name == 'replay']
    scope_site, = [i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
                  and ast.unparse(n.targets[0]) == 'scope']
    fn.body[scope_site+1:scope_site+1] = ast.parse('scope.update(selected_runtime_scope)').body
    iterator = common.proven.iterator_tree
    if spec['arm'] == 'P10':
        from system_campaign_p10_ahl2_replay import iterator_tree
        iterator = lambda raw: iterator_tree()
    selected_scope = dict(input_descriptors=spec.get('input_descriptors',spec['financial_strict_predecessor']['repairs']),
        input_path=lambda d:Path(args[2])/'book/repairs'/d['filename'],CHECKPOINT=spec['checkpoint_schema'],
        bind_selected_checkpoint=lambda value,context:bind_checkpoint(value,context,spec))
    class Select(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node.func) == 'proven.iterator_tree': node.func = ast.Name(id='selected_iterator',ctx=ast.Load())
            if ast.unparse(node.func) == 'suffix_tree': node.func = ast.Name(id='selected_suffix_tree',ctx=ast.Load())
            return self.generic_visit(node)
    fn = ast.fix_missing_locations(Select().visit(fn))
    scope = dict(vars(common),selected_iterator=iterator,selected_suffix_tree=lambda raw:selected_tree(raw,spec),
                 seed_book=lambda book,previous,saved:seed_selected_book(book,previous,saved,spec),
                 selected_runtime_scope=selected_scope)
    return compile_body(fn,scope)(*args,spec=spec,**kwargs)


def seed_selected_book(book, previous, saved, spec):
    """Keep raw predecessor CPs/streams/tails; reference closed bulky Q paths."""
    from full_system_benchmark import save
    from system_campaign_discovery_suffix_replay import write_new
    book,previous=Path(book),Path(previous);book.mkdir()
    lineage=book.parent/'lineage/diagnostic-predecessor';lineage.mkdir(parents=True)
    names=set(spec['full_current_streams'])|{spec['diagnostic_checkpoint'],'source-bindings.json',spec['original_qualification']['file']}
    names.update(spec.get('epoch_files',{}))
    names.update(p.relative_to(previous).as_posix() for p in (previous/'diagnostic-book').rglob('*.json.gz'))
    for name in sorted(names):
        target=lineage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(previous/name,target)
    for name in saved['journals']:
        write_new(book/(name+'.jsonl'),(previous/'diagnostic-book'/(name+'.jsonl')).read_bytes())
    (book/'retained-checkpoints').mkdir()
    save(book.parent/'retained-predecessor-reference.json',dict(run_id=spec['run_id'],head=spec['head'],artifact_id=spec['artifact_id'],
        complete_immutable_inventory_sha256=spec['inventory_sha256'],complete_immutable_inventory_members=spec['inventory_members'],
        encrypted_output=spec['encrypted_output'],copied_paths=sorted(names),completed_qualification_recomputed=False,
        old_runtime_path_and_qualification_payloads_reexported=False,financial_authority=False))


def preserve_epoch(previous, out, saved, spec):
    from research.pooled_vacancy_funding import backtest
    from system_campaign_p10_ahl2_contract import specification as original_specification
    from system_campaign_p10_ahl2_input import load
    original = original_specification()
    need(saved['input_descriptors'][:-1] == original['old_descriptors'], 'SUFFIX_P10_ORIGINAL_THREE_INPUTS_RETAINED')
    for name in spec['epoch_files']:
        target=out/name; target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists(): need(target.read_bytes()==(previous/name).read_bytes(), 'SUFFIX_P10_EXISTING_COPY_COLLISION')
        else: shutil.copyfile(previous/name,target)
    obj = load(out/'book/repairs'/saved['input_descriptors'][-1]['filename'],original,backtest.load_repair)
    need(obj.sha256 == saved['input_descriptors'][-1]['sha256']
         and backtest.input_hash(spec['financial_strict_predecessor']['base'],saved['input_descriptors']) == spec['input_sha256'],
         'SUFFIX_P10_FOUR_EXISTING_CODECS_SAME_RUNTIME_INPUT_NO_ADOPTION')


def review(evidence, previous, out, parent, saved, spec):
    """Stopped data and full canonical checkpoint restore; no forward sessions."""
    import gzip
    from full_system_benchmark import save
    from research.pooled_vacancy_funding import runtime,backtest
    from research.pooled_input_support import bundle
    from system_campaign_discovery_suffix_parent import verify_prefix,verify_chain
    from system_campaign_anchor_proofs import proof_prefix_evidence
    need(backtest.source_files() == parent['base']['sources'], 'SUFFIX_REVIEW_EXACT_ORIGINAL_CANONICAL_SOURCE_MAP')
    need((evidence/'source-bindings.json').read_bytes() == (previous/'source-bindings.json').read_bytes()
         and json.loads((evidence/'spec.json').read_bytes()) == spec,
         'SUFFIX_REVIEW_EXACT_OWN_SOURCE_AND_PREDECESSOR')
    axis=bundle.axis(); checks=[]
    paths=sorted((evidence/'diagnostic-book/retained-checkpoints').glob('*.json.gz'))
    paths.append(evidence/'diagnostic-book/discovery-checkpoint.json.gz')
    for path in paths:
        cp=json.loads(gzip.decompress(path.read_bytes())); inner=cp['runtime_checkpoint']
        need(cp['schema'] == spec['checkpoint_schema'] and cp['authority'] == saved['authority']
             and cp['financial_authority'] is False and cp['account_performance_computed'] is False
             and cp['strict_parent_outer_sha256'] == saved['strict_parent_outer_sha256']
             and inner['input_sha256'] == spec['input_sha256'] and inner['policy'] == parent['base']['policy']
             and inner['checkpoint_sha256'] == digest({k:v for k,v in inner.items() if k!='checkpoint_sha256'})
             and inner['state_sha256'] == digest(inner['state'])
             and inner['state']['last_processed_session'] == cp['source_cursor'], 'SUFFIX_REVIEW_WHOLE_CARRIER_RUNTIME_STATE_INPUT')
        need(runtime.checkpoint(runtime.restore(inner,policy=parent['base']['policy'],input_sha256=spec['input_sha256'])) == inner,
             'SUFFIX_REVIEW_EVERY_CURRENT_RETAINED_FULL_CANONICAL_ROUNDTRIP')
        days=axis[axis.index(saved['source_cursor'])+1:axis.index(cp['source_cursor'])+1]
        streams={}
        for name,commitment in cp['journals'].items():
            full=(evidence/'diagnostic-book'/(name+'.jsonl')).read_bytes()
            prefix=verify_prefix(full,commitment,last=True)
            old=verify_prefix((previous/'diagnostic-book'/(name+'.jsonl')).read_bytes(),saved['journals'][name],last=True)
            need(prefix.startswith(old),'SUFFIX_REVIEW_ALL_ORIGINAL_COMMITTED_JOURNAL_BYTES')
            streams[name]=[json.loads(line) for line in prefix[len(old):].splitlines()]
        need([row['session'] for row in streams['daily']] == days and not streams['formation']
             and cp['discovery_transitions'] == saved['discovery_transitions']+len(days), 'SUFFIX_REVIEW_COMPLETE_ORDERED_NEW_AXIS_NO_RESTART')
        full=(evidence/'discovery-events.jsonl').read_bytes()
        events=verify_chain(full,cp['events'])
        need(verify_prefix(full,cp['events']).startswith(verify_prefix((previous/'discovery-events.jsonl').read_bytes(),saved['events'])),
             'SUFFIX_REVIEW_ALL_ORIGINAL_EVENT_BYTES')
        new=events[saved['events']['rows']:]; committed=[e for e in new if e['kind']=='CORE_TRANSITION_COMMITTED']
        need([e['session'] for e in committed] == days,'SUFFIX_REVIEW_NEW_CANONICAL_EVENT_AXIS')
        chain=saved['transition_chain_sha256']; ledger=deepcopy(saved['runtime_checkpoint']['state']['ledger']['events'])
        for row,event in zip(streams['daily'],committed,strict=True):
            chain=digest(dict(previous=chain,session=row['session'],next_state_sha256=row['state_sha256'],event_chain_sha256=row['event_chain_sha256']))
            need(row['chain_sha256'] == chain and row['input_sha256'] == spec['input_sha256']
                 and row['state_sha256'] == event['context']['next_state_sha256']
                 and event['source_sha256'] == digest(parent['base']['sources']) and event['input_sha256']==spec['input_sha256'],
                 'SUFFIX_REVIEW_EVERY_NEW_STATE_SOURCE_INPUT_AND_CHAIN')
            ledger.extend(event['context']['new_ledger_events'])
        need(chain==cp['transition_chain_sha256'] and ledger==inner['state']['ledger']['events'],
             'SUFFIX_REVIEW_ENTIRE_INHERITED_LEDGER_AND_LOGGED_SUFFIX')
        anchors=verify_chain((evidence/'retained-anchor-events.jsonl').read_bytes(),cp['retained_source_anchors'],anchor=True)
        need(all(e['source_sha256']==digest(parent['base']['sources']) and e['input_sha256']==spec['input_sha256'] for e in anchors),
             'SUFFIX_REVIEW_ALL_AUXILIARY_ANCHORS_SOURCE_INPUT_BOUND')
        proof_prefix_evidence(evidence,cp['retained_anchor_qualifications'],predecessor=cp['diagnostic_predecessor'])
        if spec['arm']=='P10':
            need(cp['input_descriptors']==saved['input_descriptors'] and cp['diagnostic_input_epoch']==saved['diagnostic_input_epoch']
                 and cp['sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
                 and (evidence/'diagnostic-input-epochs.jsonl').read_bytes()==(previous/'diagnostic-input-epochs.jsonl').read_bytes(),
                 'SUFFIX_REVIEW_P10_NO_INPUT_READOPTION_OR_SECOND_ZERO_BOUNDARY')
        elif days:
            from discovery_approximations import DiscoveryPolicy
            from seal import sha256_file
            expected=DiscoveryPolicy(arm=spec['arm'],native_risk_source_sha256=spec['native_risk_source_sha256'],
                implementation_sha256=sha256_file(Path(__file__).with_name('discovery_approximations.py'))).commitment()
            policy=cp['diagnostic_policy']
            boundary_ok = (policy == saved['diagnostic_policy'] if saved.get('diagnostic_policy') else
                policy['first_session']==spec['next_session'] and any(
                    e['kind']=='DIAGNOSTIC_POLICY_BOUND' and e['context']['policy']==expected for e in new))
            need(policy['policy']==expected['policy'] and policy['sha256']==expected['sha256'] and boundary_ok,
                 'SUFFIX_REVIEW_EXPLICIT_APPROVED_DIAGNOSTIC_POLICY_PROVENANCE')
        checks.append(dict(file=path.relative_to(evidence).as_posix(),through=cp['source_cursor'],
                           transitions=cp['discovery_transitions'],full_canonical_roundtrip=True))
    save(out/'diagnostic-review.json',dict(schema='research.remaining-discovery-stopped-review/1',
        status='STOPPED_DIAGNOSTIC_PREFIX_REVIEWED_PENDING_CLIENT',arm=spec['arm'],checks=checks,
        full_original_prefixes_and_ledger=True,forward_sessions_executed=0,financial_authority=False,
        account_performance_computed=False,production_contacted=False))


def main(args):
    hosted()
    from research.pooled_vacancy_funding import journal, runtime
    spec = specification(args.arm); financial = spec['financial_strict_predecessor']
    need(json.loads(args.spec.read_bytes()) == spec, 'SUFFIX_EXACT_MOUNTED_OWN_SPEC')
    root, out, previous = Path('/old'), Path('/out'), Path('/previous')
    parent = require_strict_checkpoint(journal.read_checkpoint(root / financial['selected_checkpoint']))
    check_parent(parent, financial)
    saved = validate_contents(previous, spec)
    need((root / 'source-bindings.json').read_bytes() == (previous / 'source-bindings.json').read_bytes(),
         'SUFFIX_DIAGNOSTIC_SOURCE_IDENTICAL_TO_DISTINCT_ORIGINAL_FINANCIAL_SOURCE')
    factory = None
    if args.arm in ('P06', 'P07'):
        from system_campaign_discovery_spinoff_deferral import context_class
        factory = lambda base: context_class(base, expected_first=spec['first_expected_unresolved'])
    with retained_inputs(root, parent, out):
        if args.arm == 'P10': preserve_epoch(previous,out,saved,spec)
        if args.mode=='review': return review(Path('/evidence'),previous,out,parent,saved,spec)
        run = runtime.restore(saved['runtime_checkpoint'], policy=parent['base']['policy'], input_sha256=spec['input_sha256'])
        need(runtime.checkpoint(run) == saved['runtime_checkpoint'], 'SUFFIX_ACTUAL_CANONICAL_DIAGNOSTIC_RUNTIME_ROUNDTRIP')
        with Anchors(out, run.state, source_sha256=digest(parent['base']['sources']), input_sha256=run.input_sha256,
            expected_adapter_sha256=parent['base']['sources']['research/pooled_input_support/adapter.py'],
            previous=previous, saved=saved) as anchors:
            if args.arm in ('P09','P11'):
                from discovery_approximations import DiscoveryPolicy, context_class
                from seal import sha256_file
                policy=DiscoveryPolicy(arm=args.arm,native_risk_source_sha256=spec['native_risk_source_sha256'],
                    implementation_sha256=sha256_file(Path(__file__).with_name('discovery_approximations.py')))
                factory=lambda base:context_class(base,policy)
            selected_replay = continued_replay if args.arm in ('P09','P10','P11') else replay
            selected_replay(root, parent, out, selected_file=financial['selected_checkpoint'],
                strict_admission_sha256=saved['strict_client_admission_sha256'],
                previous=previous, spec=spec, anchors=anchors, context_class=factory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--arm', required=True)
    parser.add_argument('--mode',choices=('discovery','review'),default='discovery')
    for name in ('spec', 'request'): parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
