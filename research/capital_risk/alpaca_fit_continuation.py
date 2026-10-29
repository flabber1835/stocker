"""Exact saved-prefix admission and storage-only input equivalence."""
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time

from alpaca_fit_inputs import hosted,need


def copy_prefix(source,target,commit,lineage,journal_type):
    need(not target.exists() and source.name==commit['file'],'PREFIX_PATH')
    journal=journal_type(target);remaining=commit['bytes'];lines=0;last=None
    with source.open('rb') as old,target.open('xb') as new:
        while remaining:
            value=old.read(min(1024**2,remaining));need(value,'TRUNCATED_COMMITTED_PREFIX')
            new.write(value);journal.hash.update(value);journal.length+=len(value);remaining-=len(value);lines+=value.count(b'\n')
        new.flush();os.fsync(new.fileno())
        tail=lineage/'recovered-canonical-tail.bin';sha=hashlib.sha256();tail_length=0
        with tail.open('xb') as saved:
            while value:=old.read(1024**2):saved.write(value);sha.update(value);tail_length+=len(value)
            saved.flush();os.fsync(saved.fileno())
    need(journal.hash.hexdigest()==commit['sha256'] and lines==commit['records'],'COMMITTED_PREFIX_HASH_OR_RECORDS')
    with target.open('rb') as f:
        for line in f:last=line
    need(last is not None and last.endswith(b'\n') and hashlib.sha256(last).hexdigest()==commit['chain_sha256'],'PREFIX_FINAL_CHAIN')
    journal.count=lines;journal.chain=commit['chain_sha256']
    return journal,{'file':tail.name,'bytes':tail_length,'sha256':sha.hexdigest(),'replay_begins_after_checkpoint_only':True}


def resume(out,previous,spec,current_source,identity,journal_type,save):
    hosted()
    from sentinel.core.formation import Formation,FormationPlan
    from sentinel.core.session import SessionState
    previous=Path(previous);checkpoint=previous/spec['checkpoint']['file']
    need(checkpoint.stat().st_size==spec['checkpoint']['bytes']
        and hashlib.sha256(checkpoint.read_bytes()).hexdigest()==spec['checkpoint']['sha256'],'OWN_PREDECESSOR_FILE')
    value=json.loads(gzip.decompress(checkpoint.read_bytes()));old_plan=json.loads((previous/'plan.json').read_bytes())
    plan=FormationPlan.model_validate(old_plan['plan']);origin=plan.source_sha256
    need(value['dataset_sha256']==spec['dataset_sha256'] and value['protocol_sha256']==spec['protocol_sha256'],'PREDECESSOR_INPUT')
    need(value['journal']==spec['checkpoint']['journal'],'EXACT_PREDECESSOR_JOURNAL')
    old_binding=json.loads((previous/'source-bindings.json').read_bytes())
    protected=[p for p in old_binding if p.startswith(('sentinel/','shared/stock_strategy_shared/'))
               or p in ('research/capital_risk/alpaca_fit_policy.py','research/capital_risk/alpaca-fit-protocol.json')]
    need(all(current_source[p]==old_binding[p] for p in protected),'FINANCIAL_SOURCE_OR_RULE_CHANGED')
    if value['formation']:
        book=Formation.resume(value['canonical'],plan=plan);state=book.state;formation_count=book.count
    else:
        book=None;state=SessionState.from_dict(value['canonical']);formation_count=126
    need(state.state_hash==spec['checkpoint']['state_sha256'] and state.strategy_identity==identity
         and state.last_processed_session==spec['checkpoint']['session'],'CANONICAL_PREDECESSOR_RESTORE')
    lineage=out/'lineage';lineage.mkdir()
    if (previous/'lineage').is_dir():shutil.copytree(previous/'lineage',lineage/'inherited')
    shutil.copyfile(previous/'source-bindings.json',lineage/'previous-source-bindings.json')
    shutil.copyfile(previous/'baseline-status.json',lineage/'previous-status.json')
    shutil.copyfile(previous/'plan.json',lineage/'previous-plan.json')
    shutil.copyfile(previous/'retained-checkpoints.json',lineage/'previous-retained-checkpoints.json')
    shutil.copyfile(checkpoint,lineage/'exact-predecessor.json.gz')
    retained=json.loads((previous/'retained-checkpoints.json').read_bytes())
    for receipt in retained:
        source=previous/receipt['file'];need(hashlib.sha256(source.read_bytes()).hexdigest()==receipt['sha256'],'OLD_CHECKPOINT_FILE')
        shutil.copyfile(source,out/receipt['file'])
        proof=receipt['file'].removesuffix('.json.gz')+'-receipt.json'
        if (previous/proof).is_file():shutil.copyfile(previous/proof,out/proof)
    for name in ('feature-qualification.json','packed-input-equivalence.json','normalization.json','timing-gate.json','warmup-timing.json'):
        if (previous/name).is_file():shutil.copyfile(previous/name,lineage/('previous-'+name))
    journal,tail=copy_prefix(previous/'canonical.jsonl',out/'canonical.jsonl',value['journal'],lineage,journal_type)
    leaf_states=deepcopy(value['controller_states'])
    completed=journal.count-1
    need(completed>=formation_count and state.last_processed_session is not None,'PREDECESSOR_PROGRESS')
    sequence=plan.axis[299:]+old_plan['measured_axis']
    need(completed<len(sequence) and sequence[completed-1]==state.last_processed_session,'EXACT_SUFFIX_CURSOR')
    save(lineage/'admission.json',{'schema':'research.alpaca-exact-prefix-admission/1','original_source_sha256':origin,
        'prior_execution_source_sha256':value['source_sha256'],'state_sha256':state.state_hash,
        'checkpoint':spec['checkpoint'],'journal':value['journal'],'recovered_tail':tail,
        'canonical_financial_source_unchanged':True,'no_fresh_origin':True,'completed_transitions':completed})
    return plan,book,state,formation_count,leaf_states,journal,retained,old_plan,origin,completed


def equivalent_inputs(data,reference,prior,day,version,formation):
    """Reference module is an exact, SHA-bound original public Git blob."""
    spec=importlib.util.spec_from_file_location('_admitted_old_alpaca_input',reference)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old=module.Inputs.__new__(module.Inputs);old.__dict__=data.__dict__.copy()
    start=time.monotonic();before,_,_=old.published(prior,day,version,formation=formation,qualify=False)
    old_seconds=time.monotonic()-start
    data.packed=True;start=time.monotonic();after,_,_=data.published(prior,day,version,formation=formation,qualify=False)
    new_seconds=time.monotonic()-start
    a,b=asdict(before),asdict(after)
    need(a==b,'PACKED_PUBLICATION_PREIMAGE_MISMATCH')
    from sentinel.feed.rolling_contract import digest
    return {'schema':'research.alpaca-packed-input-equivalence/1','session':day,'prior_state_sha256':prior.state_hash,
        'complete_published_input_equal':True,'reference_input_sha256':digest(a),'packed_input_sha256':digest(b),
        'reference_seconds':old_seconds,'packed_seconds':new_seconds,'canonical_transition_advanced':False}
