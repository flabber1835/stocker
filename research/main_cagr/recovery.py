"""Prospective research continuation; the refused predecessor stays read-only."""
import json
from pathlib import Path

from sentinel.feed.rolling_contract import digest
from .storage import checkpoint, checkpoint_pointer, file_prefix, read_checkpoint, write_json

# Exact run-001 identity, independently retained before this recovery was written.
PREDECESSOR_BINDING = '3df3a1a5998e7bdad2332b34697aaaff5f75d7da2088d95237c6d78731b813d2'
TERMINAL_PREDECESSOR_BINDING = 'a93e4bc14a48d29a4c212092fb5c13b0d339e4bb3728288b869469dc291c9d14'
UNCHANGED_HARNESS = ('__init__.py', 'fractional.py', 'inputs.py', 'metrics.py',
                     'runtime.py', 'verify.py')


def validate(predecessor, binding, saved):
    predecessor_hash = digest(predecessor)
    unchanged = UNCHANGED_HARNESS
    if predecessor_hash == PREDECESSOR_BINDING:
        repair = binding.get('prospective_spinoff_repair')
        if not repair:
            raise ValueError('spin-off repair required')
        changed_sessions = [repair['document']['session']]
        expected_source = digest(dict(predecessor=predecessor['source_identity'], spinoff_repair=repair))
        old_ignored = {'harness'}
        new_ignored = {'harness', 'prospective_spinoff_repair', 'effective_source_identity'}
    elif predecessor_hash == TERMINAL_PREDECESSOR_BINDING:
        repairs = binding.get('prospective_terminal_repairs')
        if not repairs:
            raise ValueError('prospective terminal repairs required')
        changed_sessions = []
        for repair in repairs:
            doc = repair['document']
            if not doc.get('suppress') or not doc.get('add'):
                raise ValueError('terminal repair must replace an existing event')
            changed_sessions.extend(row['session'] for row in (*doc['suppress'], *doc['add']))
        expected_source = digest(dict(predecessor=predecessor['effective_source_identity'],
                                      terminal_repairs=repairs))
        old_ignored = {'harness', 'effective_source_identity'}
        new_ignored = old_ignored | {'prospective_terminal_repairs'}
        unchanged = (*unchanged, 'spinoff_repair.py')
    else:
        raise ValueError('unreviewed predecessor binding')
    if any(day <= saved['cursor'] for day in changed_sessions):
        raise ValueError('repair must be strictly after checkpoint')
    if binding.get('effective_source_identity') != expected_source:
        raise ValueError('prospective source identity changed')
    old = {k:v for k,v in predecessor.items() if k not in old_ignored}
    new = {k:v for k,v in binding.items() if k not in new_ignored}
    if new != old:
        raise ValueError('recovery changes original experiment')
    for name in unchanged:
        if binding['harness'].get(name) != predecessor['harness'].get(name):
            raise ValueError('recovery changes strategy or accounting harness: '+name)
    if saved.get('formation') is not None or saved.get('measured', 0) <= 0:
        raise ValueError('recovery requires completed formation')
    return min(changed_sessions)


def fork(previous, root, identity, checkpoint_file=None):
    previous, root = Path(previous).resolve(), Path(root).resolve()
    if previous == root or previous in root.parents or root in previous.parents:
        raise ValueError('recovery output must be separate from predecessor')
    old_identity = json.loads((previous/'identity.json').read_text())
    latest, latest_state = read_checkpoint(previous, old_identity['binding'])
    saved, state = (read_checkpoint(previous, old_identity['binding'], checkpoint_file)
                    if checkpoint_file else (latest, latest_state))
    repair_day = validate(old_identity['binding'], identity['binding'], saved)
    refusal = json.loads((previous/'refusal.json').read_text())
    if (refusal['last_completed_session'] != latest['cursor']
            or refusal['attempted_session'] <= latest['cursor']
            or repair_day > refusal['attempted_session']
            or refusal['measured_sessions'] != latest['measured']
            or saved['cursor'] > latest['cursor'] or saved['measured'] > latest['measured']):
        raise ValueError('recovery refusal does not match checkpoint and repair')
    if (root/'identity.json').exists() or (root/'latest-checkpoint.json').exists():
        raise ValueError('recovery output already initialized')
    for name, expected in saved['outputs'].items():
        with (previous/name).open('rb') as source, (root/name).open('xb') as target:
            remaining = expected['bytes']
            while remaining:
                block = source.read(min(1024*1024, remaining))
                if not block:
                    raise ValueError('predecessor output changed while copying')
                target.write(block)
                remaining -= len(block)
        if file_prefix(root/name) != expected:
            raise ValueError('copied predecessor output changed')
    write_json(root/'identity.json', identity)
    lineage = dict(schema='research-prospective-continuation/1',
        predecessor_identity=file_prefix(previous/'identity.json'),
        predecessor_checkpoint={**checkpoint_pointer(previous, checkpoint_file), 'session':saved['cursor']},
        latest_predecessor_checkpoint=checkpoint_pointer(previous),
        predecessor_binding=digest(old_identity['binding']), new_binding=digest(identity['binding']),
        cursor=saved['cursor'], measured_sessions=saved['measured'],
        state_sha256=state.state_hash, outputs=saved['outputs'], refusal=refusal,
        repair=identity['binding']['prospective_spinoff_repair'],
        terminal_repairs=identity['binding'].get('prospective_terminal_repairs', []))
    write_json(root/'recovery.json', lineage)
    checkpoint(root, {**saved, 'binding':digest(identity['binding'])})
    return lineage
