"""Rebind a verified discovery checkpoint after future-effective source additions."""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path

from research.bounded_20y.inputs import sha256
from sentinel.core.session import SessionState
from sentinel.feed.rolling_contract import digest
from .inputs import START, END
from .run import checkpoint, restore, write


SCHEMA = 'owned55.formed-20y-discovery-migration/1'
ALLOWED_HARNESS_CHANGES = {
    'prepare_supplements.py',
    'test_supplements.py',
    'migrate_checkpoint.py',
    'test_checkpoint_migration.py',
}
MULTI_CHILD_COMPATIBLE_HARNESS_CHANGES = {
    'run.py', 'spinoff_inputs.py', 'test_spinoff_inputs.py',
}


def current_binding(supplements: Path, module_dir: Path | None = None):
    module_dir = module_dir or Path(__file__).parent
    certificate = module_dir/'scope-certificate.json'
    harness = {p.name: sha256(p) for p in sorted(module_dir.glob('*.py'))}
    return dict(source_certificate_sha256=sha256(certificate), harness=harness,
        capital='50000', start=START, end=END, supplements_sha256=sha256(supplements),
        source_status='FAIL', research_permission='CURRENT_CODE_SCOPE_PROVEN',
        identity_domain='RESEARCH_SEP_TAPE_SEC_ISSUER_FF12',
        metadata_policy='HISTORICAL_PIT_V1_WITH_RETAINED_RESEARCH_ASSUMPTIONS',
        limitations=['NOT_PROVIDER_PIT_CERTIFICATION','NO_GO_AUTHORITY','NO_BROKER_OR_NAS_QUALIFICATION'])


def validate_harness(old, new, *, multi_child_compatibility=False):
    removed = sorted(set(old)-set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    added = sorted(set(new)-set(old))
    allowed = set(ALLOWED_HARNESS_CHANGES)
    if multi_child_compatibility:
        allowed |= MULTI_CHILD_COMPATIBLE_HARNESS_CHANGES
    if removed or not set(changed + added) <= allowed:
        raise ValueError(f'economic harness changed: removed={removed}, changed={changed}, added={added}')
    return dict(removed=removed, changed=changed, added=added)


def validate_certificates(old, new, *, multi_child_compatibility=False):
    old, new = deepcopy(old), deepcopy(new)
    old.pop('evidence_files', None)
    new.pop('evidence_files', None)
    if multi_child_compatibility:
        if old.pop('proof_programs') != new.pop('proof_programs'):
            raise ValueError('proof-program commitments changed')
        old_runtime, new_runtime = old.pop('runtime_files'), new.pop('runtime_files')
        changed = sorted(k for k in set(old_runtime) | set(new_runtime)
                         if old_runtime.get(k) != new_runtime.get(k))
        if changed != ['sentinel/core/spinoffs.py']:
            raise ValueError(f'unscoped production commitments changed: {changed}')
        old.pop('reviewed_revision', None)
        new.pop('reviewed_revision', None)
    if old != new:
        raise ValueError('production or proof-program commitments changed')


def validate_pre_cursor_single_child(records, cursor):
    groups = {}
    for row in records:
        if row.get('kind') != 'SPINOFF' or row['effective_session'] > cursor:
            continue
        key = (row['effective_session'], row['security_id'])
        groups.setdefault(key, set()).add(row.get('child_security_id'))
    multiple = sorted(key for key, children in groups.items() if len(children) != 1)
    if multiple:
        raise ValueError(f'pre-checkpoint reviewed multi-child event exists: {multiple}')
    return len(groups)


def validate_supplement_extension(old, new, cursor):
    if not isinstance(old, list) or not isinstance(new, list):
        raise ValueError('supplements must be lists')
    old_by_id = {r['id']: r for r in old}
    new_by_id = {r['id']: r for r in new}
    if len(old_by_id) != len(old) or len(new_by_id) != len(new):
        raise ValueError('supplement ids must be unique')
    changed = sorted(k for k, value in old_by_id.items() if new_by_id.get(k) != value)
    if changed:
        raise ValueError(f'retained supplement changed or disappeared: {changed}')
    added = [r for r in new if r['id'] not in old_by_id]
    if not added:
        raise ValueError('migration adds no supplement')
    too_early = sorted(r['id'] for r in added if r['effective_session'] <= cursor)
    if too_early:
        raise ValueError(f'checkpoint is not before added economic input: {too_early}')
    return added


def read_verified_packet(pointer_path: Path):
    pointer = json.loads(pointer_path.read_text())
    if Path(pointer['path']).name != pointer['path']:
        raise ValueError('checkpoint pointer must name a local file')
    path = pointer_path.parent/pointer['path']
    if sha256(path) != pointer['sha256']:
        raise ValueError('checkpoint bytes changed')
    with gzip.open(path, 'rt', encoding='utf8') as f:
        packet = json.load(f)
    expected = packet.pop('packet_sha256')
    if digest(packet) != expected:
        raise ValueError('checkpoint packet digest changed')
    state = SessionState.from_dict(packet['state'])
    if state.state_hash != packet['state_sha256']:
        raise ValueError('checkpoint state changed')
    return pointer, path, packet, state


def migrate(old_pointer: Path, old_runtime: Path, old_supplements: Path,
            new_supplements: Path, output: Path, module_dir: Path | None = None,
            multi_child_compatibility: bool = False):
    pointer, checkpoint_path, packet, state = read_verified_packet(old_pointer)
    old_binding = packet['binding']
    module_dir = module_dir or Path(__file__).parent
    new_binding = current_binding(new_supplements, module_dir)
    stable = set(old_binding) - {'source_certificate_sha256', 'harness', 'supplements_sha256'}
    if {k: old_binding[k] for k in stable} != {k: new_binding.get(k) for k in stable}:
        raise ValueError('capital, dates, policy or limitations changed')

    old_module_dir = old_runtime/'research'/'formed_20y'
    for name, expected in old_binding['harness'].items():
        path = old_module_dir/name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f'old harness bytes changed: {name}')
    harness_changes = validate_harness(old_binding['harness'], new_binding['harness'],
        multi_child_compatibility=multi_child_compatibility)

    old_certificate_path = old_module_dir/'scope-certificate.json'
    new_certificate_path = module_dir/'scope-certificate.json'
    if sha256(old_certificate_path) != old_binding['source_certificate_sha256']:
        raise ValueError('old scope certificate bytes changed')
    validate_certificates(json.loads(old_certificate_path.read_text()),
        json.loads(new_certificate_path.read_text()),
        multi_child_compatibility=multi_child_compatibility)
    if sha256(old_supplements) != old_binding['supplements_sha256']:
        raise ValueError('old supplement bytes changed')
    old_records = json.loads(old_supplements.read_text())
    new_records = json.loads(new_supplements.read_text())
    added = validate_supplement_extension(old_records, new_records,
                                          state.last_processed_session)
    prior_single_child_events = None
    if multi_child_compatibility:
        prior_single_child_events = validate_pre_cursor_single_child(
            old_records, state.last_processed_session)

    output.mkdir(parents=True, exist_ok=False)
    previous_chain = packet['chain']
    migration_link = dict(schema=SCHEMA, checkpoint_session=state.last_processed_session,
        previous_chain=previous_chain, old_binding_sha256=digest(old_binding),
        new_binding_sha256=digest(new_binding),
        added_supplements=[dict(id=r['id'], effective_session=r['effective_session']) for r in added],
        multi_child_compatibility=multi_child_compatibility,
        prior_single_child_events=prior_single_child_events)
    migrated = deepcopy(packet)
    migrated['binding'] = new_binding
    migrated['chain'] = digest(migration_link)
    migrated_pointer = checkpoint(output, migrated)
    restored, restored_state = restore(output/'latest-checkpoint.json', new_binding)
    if restored_state.state_hash != state.state_hash:
        raise ValueError('migrated state differs')
    preserved = ('state','state_sha256','metadata','sectors','economics','count','measured',
                 'formation','formation_receipt')
    if any(restored[k] != packet[k] for k in preserved):
        raise ValueError('migrated economic packet differs')
    evidence = dict(schema=SCHEMA, status='PASS', checkpoint_session=state.last_processed_session,
        old_checkpoint=str(checkpoint_path), old_checkpoint_sha256=pointer['sha256'],
        old_supplements_sha256=sha256(old_supplements),
        new_supplements_sha256=sha256(new_supplements),
        old_binding_sha256=digest(old_binding), new_binding_sha256=digest(new_binding),
        state_sha256=state.state_hash, previous_chain=previous_chain,
        migrated_chain=migrated['chain'], harness_changes=harness_changes,
        added_supplements=migration_link['added_supplements'],
        migrated_checkpoint=migrated_pointer,
        multi_child_compatibility=multi_child_compatibility,
        prior_single_child_events=prior_single_child_events)
    write(output/'migration.json', evidence)
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-pointer', type=Path, required=True)
    parser.add_argument('--old-runtime', type=Path, required=True)
    parser.add_argument('--old-supplements', type=Path, required=True)
    parser.add_argument('--new-supplements', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--multi-child-compatibility', action='store_true')
    args = parser.parse_args()
    print(json.dumps(migrate(**vars(args)), sort_keys=True))
