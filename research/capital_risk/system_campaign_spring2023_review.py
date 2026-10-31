"""Continue the exact admitted three-sensor proof without replaying old events."""
import ast
import json
from pathlib import Path
import shutil

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
import system_campaign_abiomed_review as original
from system_campaign_abiomed_basis import validate
from system_campaign_abiomed_facts import PRIVATE

REVIEW_REFERENCE = 'research:system-optimization-002/abiomed-sensor/prefix-reviewer/1'


def compile_review(raw, expected_sha256):
    need(sha(raw) == expected_sha256, 'SPRING2023_EXACT_ADOPTED_ORIGINAL_CERTIFICATE_REVIEWER')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'review']
    parents = [n for n in ast.walk(fn) if isinstance(n, ast.Compare)
               and ast.unparse(n) == "parent['source_cursor'] < NATIVE"]
    resolutions = [n for n in fn.body if isinstance(n, ast.Assign)
                   and len(n.targets) == 1 and ast.unparse(n.targets[0]) == 'resolution'
                   and isinstance(n.value, ast.Constant) and n.value.value is None]
    need(len(parents) == len(resolutions) == 1, 'SPRING2023_EXACT_TWO_REVIEW_CONTINUATION_SITES')
    parents[0].ops = [ast.GtE()]
    parents[0].comparators = [ast.Name(id='DAY', ctx=ast.Load())]
    resolutions[0].value = ast.parse("prior['abiomed_event_resolution']", mode='eval').body
    namespace = dict(vars(original))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<authenticated-original-three-sensor-continuation-review>', 'exec'), namespace)
    return namespace['review']


def preserve_parent(old, out, cp, spec):
    hosted()
    from research.pooled_vacancy_funding import journal
    proof = original.preserve_parent(old, out, cp, spec)
    event = proof['abiomed_event_resolution']
    need(cp['source_cursor'] >= original.DAY and event is not None,
         'SPRING2023_ALREADY_RESOLVED_ABIOMED_PARENT_REQUIRED')
    name = Path(event['path'])
    need(not name.is_absolute() and '..' not in name.parts and name.parts[:2] == ('book', 'pre-event'),
         'SPRING2023_SAFE_ACTUAL_ABIOMED_EVENT_ARCHIVE_PATH')
    source = old / name
    raw = source.read_bytes()
    value = journal.read_checkpoint(source)
    need(sha(raw) == event['file_sha256'] and value['sha256'] == event['outer_sha256']
         and value['source_cursor'] == original.NATIVE,
         'SPRING2023_EXACT_RETAINED_ABIOMED_EVENT_CHECKPOINT')
    target = out / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        need(target.read_bytes() == raw, 'SPRING2023_EXISTING_ABIOMED_EVENT_BYTES')
    else:
        shutil.copyfile(source, target)
    save(out / 'spring2023-parent-certificate-admission.json', dict(
        schema='research.spring2023-parent-certificate-admission/1',
        checkpoint_sha256=cp['sha256'], through=cp['source_cursor'],
        rows=proof['rows'], comparisons=proof['comparisons'],
        exact_parent_interval_proof_sha256=sha((old / 'uncertainty-certificate-review.json').read_bytes()),
        abiomed_event_resolution=event, no_old_event_replayed=True, production_contacted=False))
    return proof


def retained_abiomed(root, cp, out=None):
    """Revalidate its committed payload and actual native; no duplicate scan."""
    hosted()
    from dataclasses import asdict
    from research.pooled_input_support import inputs
    obj, = validate(root, cp)
    raw = (root / PRIVATE).read_bytes()
    source = json.loads(raw)
    native, = [t for t in inputs.load_actions(Path('/frozen/bundle')).terminal.get(original.NATIVE, ())
               if t.security_id == original.SID]
    need(asdict(native) == source['actual_native'], 'SPRING2023_EXACT_RETAINED_ABIOMED_NATIVE')
    if out is not None:
        target = out / PRIVATE
        if target.exists():
            need(target.read_bytes() == raw, 'SPRING2023_RETAINED_ABIOMED_EXISTING_PRIVATE_BYTES')
        else:
            target.write_bytes(raw)
    return native, obj


def review(root, old, spec, output):
    hosted()
    from research.pooled_vacancy_funding import journal
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    parent = journal.read_checkpoint(old / spec['selected_checkpoint'])
    need(parent['source_cursor'] >= original.DAY and parent['sha256'] == spec['outer_sha256'],
         'SPRING2023_EXACT_RESOLVED_OWN_PARENT')
    model, = validate(root, cp)
    reference, = [v for v in model.source_evidence if v.reference == REVIEW_REFERENCE]
    raw = Path(original.__file__).read_bytes()
    inherited = json.loads((old / 'uncertainty-certificate-review.json').read_bytes())
    need(inherited['abiomed_event_resolution'] is not None and inherited['through'] == parent['source_cursor']
         and sha((old / 'uncertainty-certificate-review.json').read_bytes()) == spec['interval_review_sha256'],
         'SPRING2023_EXACT_ADMITTED_OLD_EVENT_RESOLUTION_PROOF')
    compile_review(raw, reference.sha256)(root, old, spec, output)
    actual = json.loads(output.read_bytes())
    need(actual['inherited_rows'] == inherited['rows']
         and actual['abiomed_event_resolution'] == inherited['abiomed_event_resolution']
         and actual['event_resolution'] == inherited['event_resolution']
         and actual['guarded_completion_events'] == inherited['guarded_completion_events'],
         'SPRING2023_ALL_OLD_EVENT_RESOLUTIONS_REUSED_EXACTLY')
    save(output.parent / 'spring2023-certificate-continuation-review.json', dict(
        status='EXACT_ADMITTED_THREE_SENSOR_CERTIFICATE_CONTINUED',
        original_reviewer_sha256=sha(raw), actual_typed_input_sha256=model.sha256,
        original_source_not_modified=True, transformed_syntax_sites=2,
        every_old_event_proof_reused=True, no_old_event_replayed=True,
        inherited_rows=actual['inherited_rows'], rows=actual['rows'],
        checkpoint_sha256=cp['sha256'], production_contacted=False))
