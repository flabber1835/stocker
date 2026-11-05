"""Hosted chronological Core trading discovery; no account performance model."""
import hashlib
from pathlib import Path
import signal

from full_system_core import hosted
from full_system_benchmark import save
from system_campaign_discovery_context import (CHECKPOINT, TAINT, DiscoveryContext,
    digest, discovery_checkpoint, need, require_strict_checkpoint)


def require_axis(observed, expected):
    need(observed == expected and len(set(observed)) == len(observed),
         'DISCOVERY_COMPLETE_ORDERED_SESSION_AXIS_REQUIRED')


def source_iterator(parent, root):
    """Caller must have entered the exact retained input codecs first."""
    hosted()
    from research.pooled_input_support import bundle, inputs, adapter
    from research.pooled_vacancy_funding import backtest, runtime
    from system_campaign_readonly import reader
    from research.pooled_vacancy_funding import journal
    require_strict_checkpoint(parent)
    manifest = bundle.verify_bundle(Path('/frozen/bundle'), archive_override=Path('/frozen/archive/corpus.zip'))
    need(manifest['bundle_commitment_sha256'] == parent['base']['bundle_sha256']
         and manifest['base_archive']['sha256'] == parent['base']['archive_sha256'],
         'DISCOVERY_EXACT_STRICT_FROZEN_INPUTS')
    full = bundle.axis()
    axis = full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    need(axis[425] == backtest.START and axis[-1] == backtest.END
         and len(axis[425:]) == backtest.MEASURED_CLOSES == 2156,
         'DISCOVERY_FROZEN_FULL_MEASUREMENT_AXIS')
    backtest.validate_checkpoint(parent,parent['base'],axis)
    need(parent['base']['sources'] == backtest.source_files(), 'DISCOVERY_EXACT_STRICT_FINANCIAL_SOURCE_BYTES')
    old = reader(journal.Journal,Path(root)/'book',journal.STREAMS)
    try:
        old.verify(parent['journals'])
    finally:
        old.close()
    objects = []
    for descriptor in parent['repairs']:
        path = Path(root)/'book/repairs'/descriptor['filename']
        obj = backtest.load_repair(path,resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
        need(obj.sha256 == descriptor['sha256'] and descriptor['filename'] == obj.sha256+'.json',
             'DISCOVERY_ALL_ORIGINAL_INPUT_DESCRIPTORS_UNCHANGED')
        objects.append(obj)
    run = runtime.restore(parent['run'],policy=parent['base']['policy'],
                          input_sha256=backtest.input_hash(parent['base'],parent['repairs']))
    need(runtime.checkpoint(run) == parent['run'], 'DISCOVERY_STRICT_PARENT_CANONICAL_ROUNDTRIP')
    packets = iter(p for p in inputs.packets(Path('/frozen/bundle'),Path('/frozen/archive/corpus.zip')) if p.day >= axis[0])
    buffer = adapter.Buffer()

    def repaired(packet):
        for obj in objects:
            packet = backtest.apply_repair(packet,obj)
        return packet

    prefix = axis[:axis.index(parent['source_cursor'])+1]
    for expected in prefix:
        packet = repaired(next(packets))
        need(packet.day == expected,'DISCOVERY_EXACT_PARENT_PACKET_AXIS')
        buffer.append(packet)
    return run,buffer,packets,repaired,axis[axis.index(parent['source_cursor'])+1:]


def replay(root, parent, output, *, selected_file, strict_admission_sha256):
    """Advance the canonical shadow trades/controller on a disposable fork."""
    hosted()
    from research.pooled_vacancy_funding import journal,runtime
    from system_campaign_acceleration import Execution
    root,output = Path(root),Path(output)
    require_strict_checkpoint(parent)
    need(parent['completed'] > 0 and parent['source_cursor'] < parent['base']['end'],
         'DISCOVERY_ONLY_UNFINISHED_MEASURED_REMAINDER')
    original = (root/selected_file).read_bytes()
    need(journal.read_checkpoint(root/selected_file) == parent,
         'DISCOVERY_EXACT_SELECTED_STRICT_CHECKPOINT_BYTES')
    original_sha = hashlib.sha256(original).hexdigest()
    save(output/'discovery-authority.json',dict(authority=TAINT,financial_authority=False,
        strict_parent_outer_sha256=parent['sha256'],strict_parent_file_sha256=original_sha,
        strict_client_admission_sha256=strict_admission_sha256,
        account_performance_computed=False,new_origin=False,production_contacted=False))
    run,buffer,packets,repaired,wanted = source_iterator(parent,root)
    book = output/'diagnostic-book';book.mkdir()
    stop = []
    previous_signals = {sig:signal.signal(sig,lambda number,frame:stop.append(number))
                        for sig in (signal.SIGINT,signal.SIGTERM)}
    observed=[]
    chain=digest(dict(authority=TAINT,parent=parent['sha256']))
    try:
        with journal.Journal(book) as stream, Execution('FAST',signal_closes=1) as acceleration, \
                DiscoveryContext(output,source_sha256=digest(parent['base']['sources'])) as context:
            def checkpoint():
                value=discovery_checkpoint(runtime.checkpoint(run),parent_outer_sha256=parent['sha256'],
                    cursor=run.state.last_processed_session,transitions=len(observed),event_chain_sha256=context.chain)
                value.update(journals=stream.commitment(),events=context.commitment(),transition_chain_sha256=chain,
                    strict_client_admission_sha256=strict_admission_sha256)
                journal.write_checkpoint(book/'discovery-checkpoint.json.gz',value)
                return value
            checkpoint()
            for expected in wanted:
                if stop:
                    break
                packet=repaired(next(packets))
                need(packet.day == expected,'DISCOVERY_NO_SKIPPED_OR_DUPLICATE_SESSION')
                buffer.append(packet);buffer.current=packet
                published=buffer.prepare(run.state,run.state.data_version+1,formation=False)
                next_run=runtime.advance(run,published)
                chain=digest(dict(previous=chain,session=packet.day,
                    next_state_sha256=next_run.state.state_hash,event_chain_sha256=context.chain))
                row=dict(schema='research.disposable-core-trading-row/1',authority=TAINT,
                    session=packet.day,phase='DISCOVERY',state_sha256=next_run.state.state_hash,
                    input_sha256=run.input_sha256,chain_sha256=chain,event_chain_sha256=context.chain,
                    decision=next_run.state.last_decision,account_performance_computed=False)
                stream.append('daily',row)
                run=next_run;observed.append(packet.day);checkpoint()
            complete=observed == wanted
            if complete:
                require_axis(observed,wanted)
            save(output/'discovery-outcome.json',dict(schema='research.disposable-core-trading-outcome/1',
                authority=TAINT,status='COMPLETE_DISCOVERY_PENDING_REVIEW' if complete else 'PARTIAL_DISCOVERY_STOPPED',
                financial_authority=False,through=run.state.last_processed_session,
                transitions=len(observed),remaining_sessions=len(wanted)-len(observed),
                all_remaining_sessions_covered=complete,discovery_checkpoint_schema=CHECKPOINT,
                path_has_bypasses=context.tainted,events=context.commitment(),
                account_performance_computed=False,production_contacted=False))
            save(output/'discovery-acceleration-proof.json',acceleration.proof())
            need(complete,'DISCOVERY_REMAINDER_NOT_COMPLETE')
    finally:
        for sig,old in previous_signals.items():
            signal.signal(sig,old)
        need((root/selected_file).read_bytes() == original,
             'DISCOVERY_NEVER_CHANGES_ORIGINAL_STRICT_CHECKPOINT')
