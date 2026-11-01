"""Actual hosted canonical fault-injection qualification, never performance."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import save
from system_campaign_discovery_context import (TAINT,DiscoveryContext,discovery_checkpoint,
    digest,need,require_strict_checkpoint)
from system_campaign_discovery_replay import source_iterator,require_axis


def qualify(root,parent,output,*,selected_file):
    hosted()
    from research.pooled_vacancy_funding import runtime,journal,backtest
    from stock_strategy_shared.wealth_core.terminal import TerminalTerms,TerminalKind
    from stock_strategy_shared.wealth_core import v5
    from stock_strategy_shared.wealth_core.state import PortfolioState,HoldingEpisode
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from system_campaign_acceleration import Execution
    root,output=Path(root),Path(output)
    before=(root/selected_file).read_bytes()
    run,buffer,packets,repaired,wanted=source_iterator(parent,root)
    need(len(wanted)>=3,'DISCOVERY_GATE_THREE_REMAINING_SESSIONS')
    held={v['security_id'] for v in run.state.wealth_core['episodes'].values()}
    leaders=set(run.state.median5['selected'])
    need(held and leaders,'DISCOVERY_GATE_ACTUAL_PARENT_HOLDING_AND_LEADERSHIP')
    chosen_hold=sorted(held)[0];chosen_leader=sorted(leaders)[0]
    affected={chosen_hold,chosen_leader}
    old_runtime_advance=runtime.advance
    book=output/'qualification-book';book.mkdir()
    observed=[];states=[]
    with journal.Journal(book) as stream,Execution('FAST',signal_closes=1), \
            DiscoveryContext(output,source_sha256=digest(parent['base']['sources'])) as context:
        for i,day in enumerate(wanted[:3]):
            packet=repaired(next(packets));need(packet.day==day,'DISCOVERY_GATE_SOURCE_AXIS')
            buffer.append(packet);buffer.current=packet
            publication=buffer.prepare(run.state,run.state.data_version+1,formation=False)
            # Explicit synthetic fault. Never a provider correction or overlay.
            extra=tuple(TerminalTerms(session=day,security_id=sid,kind=TerminalKind.CASH_MERGER,
                cash_per_share=None,reference='research:discovery-synthetic-missing-terms/'+sid)
                for sid in sorted(affected)) if i<2 else ()
            publication=replace(publication,
                bars=tuple(b for b in publication.bars if i>=2 or b.security_id not in affected),
                terminal_events=tuple(t for t in publication.terminal_events if t.security_id not in affected)+extra,
                cash_distributions=None,spinoff_distributions=())
            prior=run
            run=runtime.advance(run,publication)
            if i<2:
                old_shares={k:v['current_shares'] for k,v in prior.state.wealth_core['episodes'].items()
                            if v['security_id']==chosen_hold}
                actual_shares={k:v['current_shares'] for k,v in run.state.wealth_core['episodes'].items()
                               if v['security_id']==chosen_hold}
                need(old_shares==actual_shares and actual_shares,
                     'DISCOVERY_GATE_UNKNOWN_HELD_LOT_RETAINED')
                new_events=run.state.ledger['events'][len(prior.state.ledger['events']):]
                need(not any(v['security_id'] in affected for v in new_events),
                     'DISCOVERY_GATE_NO_INVENTED_CASH_SHARE_TRANSFORMATION_OR_FILL')
            stream.append('daily',dict(schema='research.disposable-core-trading-row/1',authority=TAINT,
                session=day,state_sha256=run.state.state_hash,input_sha256=run.input_sha256,
                account_performance_computed=False))
            need(run.state.last_processed_session==day,'DISCOVERY_GATE_ACTUAL_CANONICAL_SESSION_ADVANCED')
            observed.append(day);states.append(run.state.state_hash)
        require_axis(observed,wanted[:3])
        wrapped=discovery_checkpoint(runtime.checkpoint(run),parent_outer_sha256=parent['sha256'],
            cursor=observed[-1],transitions=3,event_chain_sha256=context.chain)
        for checker in (require_strict_checkpoint,
            lambda value:backtest.validate_checkpoint(value,parent['base'],[])):
            try:
                checker(wrapped)
            except ValueError:
                pass
            else:
                raise ValueError('DISCOVERY_GATE_DIAGNOSTIC_CHECKPOINT_ENTERED_STRICT_REPLAY')
        # The original canonical cash operation still settles and removes once.
        cfg=runtime.config(parent['base']['policy'])
        core=PortfolioState.fresh(9000,n_slots=cfg.n_slots,
                                 entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
        sid='SYNTHETIC_DISCOVERY_POSITIVE_CASH'
        core.episodes[0]=HoldingEpisode(sid,sid,'SYNTHETIC',0,observed[0],observed[0],100.,100.,10,10)
        core.slots[0].occupied_by=sid;ledger=Ledger()
        term=TerminalTerms(session=observed[-1],security_id=sid,kind=TerminalKind.CASH_MERGER,
                           cash_per_share=12.5,reference='research:discovery-synthetic-exact-cash')
        context.current=(run,publication)
        applied=context.m.terminal.apply_terminal(core,term,ledger=ledger,session=observed[-1],cfg=cfg)
        need(applied['applied'] and core.cash==9125. and not core.episodes
             and len(ledger.events)==1,'DISCOVERY_GATE_SUPPORTED_CASH_UNCHANGED')
        once=deepcopy((core.to_dict(),ledger.to_dict()))
        result=context.m.terminal.apply_terminal(core,term,ledger=ledger,session=observed[-1],cfg=cfg)
        need(result['reason']=='NOT_HELD' and (core.to_dict(),ledger.to_dict())==once,
             'DISCOVERY_GATE_SUPPORTED_CASH_ONCE_ONLY')
        context.current=None
        event_commitment=context.commitment()
    need(runtime.advance is old_runtime_advance,'DISCOVERY_GATE_ORIGINAL_ADVANCE_HOOK_RESTORED')
    need((root/selected_file).read_bytes()==before,'DISCOVERY_GATE_STRICT_PARENT_GZIP_IMMUTABLE')
    save(output/'discovery-canonical-qualification.json',dict(
        schema='research.disposable-core-discovery-qualification/1',status='QUALIFIED',authority=TAINT,
        strict_parent_outer_sha256=parent['sha256'],strict_parent_gzip_sha256=hashlib.sha256(before).hexdigest(),
        synthetic_fault_injection_only=True,synthetic_canonical_transitions=3,sessions=observed,
        actual_core_and_controller_state_hashes=states,held_security_id=chosen_hold,
        leadership_security_id=chosen_leader,missing_quote_and_incomplete_term_continuation=True,
        no_invented_cash_shares_or_execution_prices=True,supported_cash_unchanged_and_once_only=True,
        actual_strict_checkpoint_rejection=True,strict_parent_bytes_unchanged=True,
        original_runtime_hook_restored=True,events=event_commitment,
        actual_discovery_started=False,account_performance_computed=False,production_contacted=False))
