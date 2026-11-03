"""Reuse exact canonical loop; only Q FAST resumes the admitted cached prefix."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil

from system_campaign_p10_ahl2_contract import need, sha, encoded, AFFECTED, CURSOR
from system_campaign_p10_ahl2_context import frozen_namespace
from system_campaign_p10_ahl2_epoch import write_new
from system_campaign_p10_ahl2_wire import object_bytes
from system_campaign_p10_ahl2_post_plan_observe import Observer


def prefix_axis_valid(old_days, full_wanted, *, resume):
    expected = ['2019-02-01','2019-02-04','2019-02-05','2019-02-06','2019-02-07','2019-02-08',
                '2019-02-11','2019-02-12','2019-02-13','2019-02-14'] if resume else [CURSOR]
    need(old_days == expected and full_wanted[:len(old_days)] == old_days
         and full_wanted[len(old_days)] == (AFFECTED if resume else '2019-02-04'),
         'P10_POST_PLAN_EXACT_COMMITTED_AXIS_AND_FIRST_NEW_ADJACENCY')


def seed_bound_book(book, previous, saved, binding, resume):
    from system_campaign_discovery_suffix_replay import seed_book
    if resume:
        root = Path(book).parent/'lineage/original-own1'
        root.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(binding.original_previous,root)
        # seed_book itself excludes nested lineage; the original OWN1 is kept
        # exactly once above, independently of the cached branch's flat files.
    seed_book(book,previous,saved)


def resume_pre_event_valid(binding):
    need((binding.out/'diagnostic-book/pre-event/2019-02-15.json.gz').read_bytes()
         == (binding.previous/'diagnostic-book/pre-event/2019-02-15.json.gz').read_bytes(),
         'P10_POST_PLAN_NEW_COPY_PRE_EVENT_BYTES_EQUAL_COMMITTED_CACHED_CP')


def replay_namespace(resume=False):
    raw,nodes,scope = frozen_namespace('system_campaign_p10_ahl2_replay.py',('replay',))
    fn, = nodes
    guards = [n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func) == 'need'
              and len(n.args) == 2 and isinstance(n.args[1],ast.Constant)
              and n.args[1].value == 'P10_ONLY_COMMITTED_FEB1_SEED_FIRST_FRESH_SESSION_FEB4']
    need(len(guards) == 1,'P10_POST_PLAN_ONE_FROZEN_ORIGIN_AXIS_GUARD_SITE')
    guards[0].func = ast.Name(id='prefix_axis_valid',ctx=ast.Load())
    guards[0].args = [ast.Name(id='old_days',ctx=ast.Load()),ast.Name(id='full_wanted',ctx=ast.Load())]
    guards[0].keywords = [ast.keyword(arg='resume',value=ast.Constant(resume))]
    seeds = [n for n in ast.walk(fn) if isinstance(n,ast.Call)
             and ast.unparse(n) == 'common.seed_book(book, previous, saved)']
    need(len(seeds) == 1,'P10_POST_PLAN_ONE_DISJOINT_SEED_BOOK_SITE')
    seeds[0].func = ast.Name(id='seed_bound_book',ctx=ast.Load())
    seeds[0].args += [ast.Name(id='binding',ctx=ast.Load()),ast.Constant(resume)]
    first, = [n for n in ast.walk(fn) if isinstance(n,ast.ClassDef) and n.name == 'First']
    prepare, = [n for n in first.body if isinstance(n,ast.FunctionDef) and n.name == 'prepare']
    if resume:
        # Exact pre-event CP is already durably written by the frozen loop
        # before its first prepare call. The full next packet is checked below.
        prepare.body.insert(0,ast.parse('resume_pre_event_valid(binding)').body[0])
        returns = [n for n in ast.walk(prepare) if isinstance(n,ast.Call)
                   and ast.unparse(n.func) == 'observer.begin']
        need(len(returns) == 1,'P10_POST_PLAN_ONE_ACTUAL_BEGIN_FULL_PUBLICATION_SITE')
        at, = [i for i,n in enumerate(prepare.body) if isinstance(n,ast.Expr) and n.value is returns[0]]
        prepare.body.insert(at,ast.parse("need(observer.material(publication)==binding.retained_failed_record['publication'], 'P10_POST_PLAN_FIRST_NEW_ENTIRE_PUBLICATION_EQUALS_RETAINED_FAILED_ATTEMPT')").body[0])
    scope.update(Observer=Observer, prefix_axis_valid=prefix_axis_valid,
                 seed_bound_book=seed_bound_book,resume_pre_event_valid=resume_pre_event_valid,
                 NEXT=AFFECTED if resume else '2019-02-04')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<p10-post-plan-exact-canonical-loop>','exec'),scope)
    return scope


def resume_binding(binding, retained):
    """Called hosted only, after a fresh OWN1 input-zero proof, never for suffix."""
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import runtime
    root = Path(retained)/'fast'
    cp_raw = (root/'diagnostic-book/discovery-checkpoint.json.gz').read_bytes()
    need(sha(cp_raw) == '5b9140bb9f438d8eb423b7f606aab081128f3aee870b7deab38e559b7d1c0b65',
         'P10_POST_PLAN_ONLY_ROOT_ADMITTED_FAST_PREFIX')
    saved = object_bytes(cp_raw,gzip_declared=True)
    need((binding.out/'zero-input-epoch.json').read_bytes() == (root/'zero-input-epoch.json').read_bytes()
         and (binding.out/'diagnostic-input-epochs.jsonl').read_bytes() == (root/'diagnostic-input-epochs.jsonl').read_bytes()
         and saved['input_descriptors'] == binding.descriptors and saved['diagnostic_input_epoch'] == binding.epoch,
         'P10_POST_PLAN_EXACT_ORIGINAL_INPUT_ZERO_AND_FOUR_DOC_EPOCH_NO_REEMIT')
    restored = runtime.restore(saved['runtime_checkpoint'],policy=binding.parent['base']['policy'],
                               input_sha256=binding.run.input_sha256)
    need(runtime.checkpoint(restored) == saved['runtime_checkpoint'], 'P10_POST_PLAN_EXACT_CACHED_FULL_RUNTIME_RESTORE')
    failed = object_bytes((root/'actual-runtime-path/2019-02-15.json.gz').read_bytes(),gzip_declared=True,
                          expanded_limit=256*1024**2)
    need(failed['prior'] == saved['runtime_checkpoint'] and failed['refused_prior_after_checkpoint'] == failed['prior'],
         'P10_POST_PLAN_FAILED_TENTH_STATE_NEVER_ADOPTED')
    binding.original_previous = binding.previous
    binding.previous = root
    binding.saved = deepcopy(saved)
    binding.active = deepcopy(saved)
    binding.run = restored
    binding.retained_failed_record = failed
    for path in sorted((root/'actual-runtime-path').glob('*.json.gz')):
        if path.name < '2019-02-15.json.gz':
            write_new(binding.out/'actual-runtime-path'/path.name,path.read_bytes())
    write_new(binding.out/'actual-native-guard-trace.jsonl',(root/'actual-native-guard-trace.jsonl').read_bytes())
    return binding


def replay(binding, *, mode='FAST', processing_end=None, observer=None, resume=False):
    need(not resume or (mode == 'FAST' and processing_end == AFFECTED
         and binding.active['source_cursor'] == '2019-02-14'
         and binding.active['discovery_transitions'] == 10),
         'P10_POST_PLAN_RESUME_IS_Q_FAST_ONE_DAY_ONLY')
    if not resume:
        need(binding.active['source_cursor'] == CURSOR and binding.active['discovery_transitions'] == 1,
             'P10_POST_PLAN_REFERENCE_AND_FRESH_SUFFIX_ALWAYS_ORIGINAL_OWN1')
    return replay_namespace(resume)['replay'](binding,mode=mode,processing_end=processing_end,observer=observer)
