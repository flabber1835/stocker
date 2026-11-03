"""Hosted zero-session fourth-input boundary on the exact OWN P10 runtime."""
from copy import deepcopy
from dataclasses import replace
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace

from system_campaign_p10_ahl2_contract import (TAINT, CHECKPOINT, EPOCH, CURSOR, SID, NATIVE,
    encoded, digest, sha, need, physical_tree)
from system_campaign_p10_ahl2_input import document_bytes, load, descriptor, source_witness


def write_new(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(path, value):
    write_new(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())


def zero_invariants(before, after, *, spec, old_descriptors, descriptors, input_hash):
    need(old_descriptors == spec['old_descriptors'] and len(descriptors) == len(old_descriptors) + 1
         and descriptors[:-1] == old_descriptors, 'P10_OLD_THREE_INPUT_DESCRIPTORS_BYTES_AND_ORDER')
    need(before['checkpoint_sha256'] == spec['runtime_checkpoint_sha256']
         and before['state_sha256'] == after['state_sha256'] == spec['state_sha256']
         and before['state'] == after['state'] and before['state']['last_processed_session'] == CURSOR,
         'P10_CANONICAL_ZERO_ENTIRE_SESSION_STATE_UNCHANGED')
    a, b = deepcopy(before), deepcopy(after)
    for value in (a, b):
        value.pop('checkpoint_sha256')
        value.pop('input_sha256')
    need(a == b and before['input_sha256'] == spec['input_sha256']
         and after['input_sha256'] == input_hash(spec['base'], descriptors)
         and after['input_sha256'] != before['input_sha256'],
         'P10_ZERO_ONLY_CANONICAL_INPUT_AND_CP_IDENTITY_CHANGE')
    need(all(cp['checkpoint_sha256'] == digest({k:v for k,v in cp.items() if k != 'checkpoint_sha256'})
             for cp in (before, after)), 'P10_BOTH_ZERO_CANONICAL_RUNTIME_CHECKPOINT_DIGESTS')


def prepare_epoch(root, previous, out, spec, *, new_input=True, source_root=Path('/variant')):
    from full_system_core import hosted
    hosted()  # Before source/private files or any canonical import.
    root, previous, out = Path(root), Path(previous), Path(out)
    source_binding = json.loads((previous / 'source-bindings.json').read_bytes())
    source_proof = physical_tree(source_root, source_binding, spec)
    actual_source = source_witness(spec)
    write_json(out / 'actual-source-subset.json', actual_source)
    from research.pooled_vacancy_funding import runtime, backtest, journal
    from system_campaign_p10_ahl2_parent import validate_contents
    saved = validate_contents(previous, spec)
    parent = journal.read_checkpoint(root / spec['financial_strict_predecessor']['selected_checkpoint'])
    need(parent['base'] == spec['base'] and parent['sha256'] == spec['strict_parent_outer_sha256']
         and parent['repairs'] == spec['old_descriptors'] and backtest.source_files() == parent['base']['sources'],
         'P10_OWN_DISTINCT_FINANCIAL_PARENT_SOURCE_AND_THREE_INPUTS')
    objects = []
    old_raw = {}
    for d in spec['old_descriptors']:
        path = root / 'book/repairs' / d['filename']
        raw = path.read_bytes()
        need(sha(raw) == d['sha256'] and raw == (previous / 'book/repairs' / d['filename']).read_bytes(),
             'P10_ALL_THREE_ARCHIVED_INPUT_BYTES_IDENTICAL')
        obj = backtest.load_repair(path, resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
        need(obj.sha256 == d['sha256'], 'P10_ACTUAL_OLD_ORDINARY_CANONICAL_PARSER')
        objects.append(obj)
        old_raw[d['filename']] = raw
    run = runtime.restore(saved['runtime_checkpoint'], policy=parent['base']['policy'],
                          input_sha256=backtest.input_hash(parent['base'], parent['repairs']))
    before = runtime.checkpoint(run)
    need(before == saved['runtime_checkpoint'], 'P10_EXACT_OWN_CP1_CANONICAL_RESTORE_ROUNDTRIP')
    descriptors = deepcopy(spec['old_descriptors'])
    for name, raw in old_raw.items():
        path = out / 'book/repairs' / name
        if path.exists():
            need(path.read_bytes() == raw, 'P10_RETAINED_OLD_DOCUMENT_COLLISION_REFUSES')
        else:
            write_new(path, raw)
    epoch = None
    if new_input:
        raw = document_bytes(spec)
        path = out / 'book/repairs' / (sha(raw) + '.json')
        write_new(path, raw)
        obj = load(path, spec, backtest.load_repair)
        d = descriptor(obj, spec)
        descriptors.append(d)
        objects.append(obj)
        # Exactly the source-bound canonical backtest overlay operation.
        run = replace(run, input_sha256=backtest.input_hash(parent['base'], descriptors))
        after = runtime.checkpoint(run)
        zero_invariants(before, after, spec=spec, old_descriptors=parent['repairs'],
                        descriptors=descriptors, input_hash=backtest.input_hash)
        need(runtime.checkpoint(runtime.restore(after, policy=parent['base']['policy'],
             input_sha256=run.input_sha256)) == after, 'P10_NEW_INPUT_ZERO_FULL_CANONICAL_ROUNDTRIP')
        body = dict(schema=EPOCH, authority=TAINT, financial_authority=False, sequence=0,
            previous_epoch_chain_sha256=digest(dict(authority=TAINT, stream='diagnostic-input-epochs.jsonl')),
            original_checkpoint_file_sha256=spec['diagnostic_checkpoint_sha256'],
            original_runtime_checkpoint_sha256=before['checkpoint_sha256'],
            original_state_sha256=before['state_sha256'], source_binding_sha256=spec['source_binding_sha256'],
            source_canonical_sha256=digest(parent['base']['sources']), source_physical_sha256=digest(source_binding['all_sources']),
            predecessor_input_sha256=before['input_sha256'], successor_input_sha256=after['input_sha256'],
            predecessor_descriptors=deepcopy(parent['repairs']), successor_descriptors=deepcopy(descriptors),
            zero_runtime_checkpoint_sha256=after['checkpoint_sha256'], cursor=CURSOR, transitions=1,
            earliest_affected_session=NATIVE, affected_security_id=SID, entire_state_unchanged=True)
        raw = encoded(dict(record=body, chain_sha256=digest(body))) + b'\n'
        write_new(out / 'diagnostic-input-epochs.jsonl', raw)
        epoch = dict(rows=1, bytes=len(raw), prefix_sha256=sha(raw), chain_sha256=digest(body))
        write_json(out / 'zero-input-epoch.json', dict(schema='research.p10-zero-session-input-proof/1',
            original=before, candidate=after, descriptors=descriptors, epoch=epoch,
            input_document_raw_sha256=d['sha256'],
            input_document_model_sha256=digest(obj.model_dump(mode='json', by_alias=True)),
            full_state_equal=True, policy_strategy_cursor_preserved=True, financial_authority=False,
            qualifier_or_unsent_state_adopted=False))
    active = deepcopy(saved)
    active['runtime_checkpoint'] = runtime.checkpoint(run)
    write_json(out / 'source-contract.json', source_proof)
    return SimpleNamespace(root=root, previous=previous, out=out, parent=parent, saved=saved,
        active=active, run=run, descriptors=descriptors, objects=objects, epoch=epoch,
        source_binding=source_binding, source_contract=source_proof, spec=spec, new_input=new_input)


def bind_checkpoint(value, binding):
    body = deepcopy(value)
    if binding.new_input:
        body.update(schema=CHECKPOINT, diagnostic_input_epoch=deepcopy(binding.epoch),
            input_descriptors=deepcopy(binding.descriptors), original_diagnostic_checkpoint_sha256=
            binding.spec['diagnostic_checkpoint_sha256'], source_binding_sha256=binding.spec['source_binding_sha256'])
        need(body['runtime_checkpoint']['input_sha256'] == binding.run.input_sha256,
             'P10_EVERY_NEW_CP_USES_EXPLICIT_FOURTH_INPUT_EPOCH')
        body['sha256'] = digest(body)
    return body
