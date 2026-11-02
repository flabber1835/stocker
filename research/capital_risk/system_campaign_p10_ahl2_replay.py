"""Reuse the frozen suffix AST and original native21 canonical transitions."""
import ast
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil

from system_campaign_p10_ahl2_contract import (TAINT, CURSOR, NEXT, AFFECTED, HERE, PRIOR, PRIOR_SHA,
    CHECKPOINT, encoded, sha, digest, need, function)
from system_campaign_p10_ahl2_epoch import bind_checkpoint, write_new, write_json
from system_campaign_p10_ahl2_observe import Observer

COMMON = {
    'system_campaign_discovery_suffix_replay.py': 'df501aa487c981911dda659ae7a29b8a72e80d2318fbb0d3c22e3d5f7afe5a92',
    'system_campaign_p01_discovery_suffix_replay.py': '31e26a827f8dad306f7e2d095c24e449987fa9a44abfdd87e345a3b76a05e15d',
    'system_campaign_anchor_proofs.py': '24f4c29ac2e4d5fe0392e86fb22cc24d00a8ec3493165fb98cbdbc21e3745193',
}


def exact_replay():
    raw = (HERE / PRIOR).read_bytes()
    need(sha(raw) == PRIOR_SHA, 'P10_EXACT_OLD427_REPLAY_SOURCE_BINDING')
    sources = json.loads(raw)['sources']
    name = 'system_campaign_discovery_replay.py'
    body = (HERE / name).read_bytes()
    need(sha(body) == sources[name], 'P10_ORIGINAL_CANONICAL_DISCOVERY_AST_BYTES')
    for name, expected in COMMON.items():
        need(sha((HERE / name).read_bytes()) == expected, 'P10_FROZEN_SHARED_SUFFIX_HELPER:' + name)
    return body


def iterator_tree():
    import system_campaign_p01_discovery_suffix_replay as proven
    tree = proven.iterator_tree(exact_replay())
    sites = dict(descriptors=0, path=0)
    class Bind(ast.NodeTransformer):
        def visit_Subscript(self, node):
            if ast.unparse(node) == "parent['repairs']":
                sites['descriptors'] += 1
                return ast.copy_location(ast.Name(id='input_descriptors', ctx=ast.Load()), node)
            return self.generic_visit(node)
        def visit_Assign(self, node):
            if len(node.targets) == 1 and ast.unparse(node.targets[0]) == 'path' and ast.unparse(node.value) == \
                    "Path(root) / 'book/repairs' / descriptor['filename']":
                sites['path'] += 1
                node.value = ast.parse('input_path(descriptor)', mode='eval').body
            return self.generic_visit(node)
    tree = Bind().visit(tree)
    need(sites == dict(descriptors=2, path=1), 'P10_EXACT_SOURCE_ITERATOR_INPUT_EPOCH_BINDING_SITES')
    return ast.fix_missing_locations(tree)


def replay_tree(mode):
    from system_campaign_discovery_suffix_replay import suffix_tree
    need(mode in ('FAST', 'REFERENCE'), 'P10_ONLY_DECLARED_NATIVE_TRANSPORTS')
    tree = suffix_tree(exact_replay())
    fn = tree.body[0]
    execution = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'Execution']
    need(len(execution) == 1 and ast.unparse(execution[0]) == "Execution('FAST', signal_closes=1)",
         'P10_ONE_CANONICAL_NATIVE_TRANSPORT_SITE')
    execution[0].args = [ast.Constant(mode)]
    execution[0].keywords[0].value = ast.Constant(21)
    source_at, = [i for i,n in enumerate(fn.body) if isinstance(n, ast.Assign)
                  and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == 'source_iterator']
    fn.body[source_at+1:source_at+1] = ast.parse("wanted=[d for d in wanted if d<=processing_end]").body
    cp, = [n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef) and n.name == 'checkpoint']
    at, = [i for i,n in enumerate(cp.body) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
           and ast.unparse(n.value.func) == 'journal.write_checkpoint']
    cp.body[at:at] = ast.parse('value=bind_checkpoint(value,binding)').body
    advance, = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                and ast.unparse(n.targets[0]) == 'next_run' and ast.unparse(n.value) == 'runtime.advance(run, published)']
    advance.value = ast.parse('advance_recorded(run,published)', mode='eval').body
    loop, = [n for n in ast.walk(fn) if isinstance(n, ast.For) and ast.unparse(n.iter) == 'wanted']
    prepared, = [i for i,n in enumerate(loop.body) if isinstance(n, ast.Assign)
                 and ast.unparse(n.targets[0]) == 'published']
    loop.body[prepared:prepared] = ast.parse("""
if packet.terminal or packet.spins:
    checkpoint()
    write_new(book/'pre-event'/(packet.day+'.json.gz'),(book/'discovery-checkpoint.json.gz').read_bytes())
""").body
    loop.body.append(ast.parse("if packet.day==AFFECTED: checkpoint()").body[0])
    return ast.fix_missing_locations(tree)


def path_record(out, record):
    target = Path(out) / 'actual-runtime-path' / (record['session'] + '.json.gz')
    raw = encoded(record) + b'\n'
    write_new(target, gzip.compress(raw, compresslevel=1, mtime=0))


def replay(binding, *, mode='FAST', processing_end=None, observer=None):
    """Canonical loop is the source-bound frozen AST, never a second engine."""
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import runtime
    from research.pooled_input_support import bundle
    import system_campaign_discovery_replay as original
    import system_campaign_discovery_suffix_replay as common
    from system_campaign_anchor_proofs import AnchorQualification
    from system_campaign_discovery_suffix_parent import verify_prefix
    spec, saved = binding.spec, binding.active
    previous, root, out, parent = binding.previous, binding.root, binding.out, binding.parent
    processing_end = processing_end or spec['target_end']
    axis = bundle.axis()
    full_wanted = axis[axis.index(parent['source_cursor'])+1:axis.index(processing_end)+1]
    old_daily = verify_prefix((previous / 'diagnostic-book/daily.jsonl').read_bytes(), saved['journals']['daily'])
    old_days = [json.loads(line)['session'] for line in old_daily.splitlines()]
    need(old_days == [CURSOR] and full_wanted[:1] == old_days and full_wanted[1] == NEXT,
         'P10_ONLY_COMMITTED_FEB1_SEED_FIRST_FRESH_SESSION_FEB4')
    reference = dict(schema='research.p10-own-diagnostic-reference/1', authority=TAINT,
        financial_authority=False, run_id=spec['run_id'], head=spec['head'], artifact_id=spec['artifact_id'],
        checkpoint_sha256=spec['diagnostic_checkpoint_sha256'], runtime_checkpoint_sha256=spec['runtime_checkpoint_sha256'],
        source_cursor=CURSOR, transitions=1, input_epoch=deepcopy(binding.epoch))
    observer = observer or Observer(binding)
    with common.Anchors(out, binding.run.state, source_sha256=digest(parent['base']['sources']),
            input_sha256=binding.run.input_sha256,
            expected_adapter_sha256=parent['base']['sources']['research/pooled_input_support/adapter.py'],
            previous=previous, saved=binding.saved) as anchors, observer:
        gate = AnchorQualification(out, anchors, predecessor=reference)
        class First:
            def __init__(self): self.started = False
            def prepare(self, buffer, run):
                if not self.started:
                    need(buffer.current.day == NEXT and runtime.checkpoint(run) == saved['runtime_checkpoint'],
                         'P10_FIRST_ACTUAL_ADJACENCY_FULL_ZERO_RUNTIME_INPUT')
                    self.started = True
                try:
                    publication = gate.prepare(buffer, run)
                except BaseException as error:
                    write_new(out / 'actual-prepare-refusals' / (buffer.current.day + '.json.gz'),
                        gzip.compress(encoded(dict(session=buffer.current.day, prior=runtime.checkpoint(run),
                            source_packet=observer.material(buffer.current), refusal=dict(type=type(error).__name__,
                                message=str(error), committed=False))) + b'\n', compresslevel=1, mtime=0))
                    raise
                observer.begin(run, publication)
                return publication
            def after(self, prior, following):
                record = observer.current
                try:
                    record = observer.finish(prior, following)
                    gate.after(prior, following)
                except BaseException as error:
                    record['postcondition_refusal'] = dict(type=type(error).__name__, message=str(error), committed=False)
                    path_record(out, record)
                    observer.current = None
                    raise
                if record['session'] <= AFFECTED:
                    path_record(out, record)
                compact = dict(session=record['session'], state_sha256=following.state.state_hash,
                    risk=record['risk'], engines=[dict(eligible=x['eligible'], risk_calls=x['risk_calls']) for x in record['engines']],
                    original_native_guard_delegated=True)
                with (out / 'actual-native-guard-trace.jsonl').open('ab') as stream:
                    stream.write(encoded(compact) + b'\n')
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
        first = First()
        def seed_book(book, previous, saved):
            common.seed_book(book, previous, saved)
            (Path(book) / 'pre-event').mkdir()
        def advance_recorded(run, published):
            try:
                return runtime.advance(run, published)
            except BaseException as error:
                record = observer.refusal(run, error)
                path_record(out, record)
                raise
        scope = dict(vars(original), saved=saved, anchors=anchors,
            input_descriptors=binding.descriptors,
            input_path=lambda d:out / 'book/repairs' / d['filename'])
        exec(compile(iterator_tree(), '<exact-p10-input-epoch-source-iterator>', 'exec'), scope)
        scope.update(binding=binding, bind_checkpoint=bind_checkpoint, processing_end=processing_end,
            previous=previous, old_days=old_days, full_wanted=full_wanted,
            seed_book=seed_book, recovered_stream=common.recovered_stream,
            ContinuedContext=common.ContinuedContext, first=first, anchor_gate=gate,
            diagnostic_reference=reference, shutil=shutil, advance_recorded=advance_recorded,
            write_new=write_new, AFFECTED=AFFECTED)
        if binding.new_input:
            scope['CHECKPOINT'] = CHECKPOINT
        exec(compile(replay_tree(mode), '<exact-p10-native21-diagnostic-suffix>', 'exec'), scope)
        try:
            return scope['replay'](root, parent, out,
                selected_file=spec['financial_strict_predecessor']['selected_checkpoint'],
                strict_admission_sha256=spec['strict_client_admission_sha256'])
        finally:
            write_json(out / 'p10-observer-summary.json', dict(schema='research.p10-actual-observer-summary/1',
                mode=mode, new_input=binding.new_input, processing_end=processing_end,
                retained_actual_sessions=[r['session'] for r in observer.records],
                packet_changes=observer.packet_records, source_contract=binding.source_contract,
                financial_authority=False, qualifier_state_adopted=False))
