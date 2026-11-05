"""Hosted C/V qualification preserves missing-risk-input refusals."""
from copy import deepcopy
from dataclasses import replace
import hashlib,json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_discovery_context import (TAINT,DiscoveryContext,discovery_checkpoint,
    digest,require_strict_checkpoint)


def expected_refusal(root,parent,out,source_iterator,code):
    """Repeat the observed synthetic failure without committing a transition."""
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core.terminal import TerminalTerms,TerminalKind
    from system_campaign_acceleration import Execution
    out=Path(out);out.mkdir()
    run,buffer,packets,repaired,wanted=source_iterator(parent,root)
    held={v['security_id'] for v in run.state.wealth_core['episodes'].values()}
    leaders=set(run.state.median5['selected']);need(held and leaders,'RISK_GATE_ACTUAL_HELD_AND_LEADERS')
    affected={sorted(held)[0],sorted(leaders)[0]};day=wanted[0]
    packet=repaired(next(packets));need(packet.day==day,'RISK_GATE_EXACT_REFUSAL_DATE')
    packet=replace(packet,bars=tuple(b for b in packet.bars if b.security_id not in affected),
        terminal=tuple(t for t in packet.terminal if t.security_id not in affected)+tuple(
            TerminalTerms(session=day,security_id=sid,kind=TerminalKind.CASH_MERGER,cash_per_share=None,
                reference='research:risk-discovery-synthetic-missing-held-input/'+sid) for sid in sorted(affected)))
    buffer.append(packet);buffer.current=packet
    prior=deepcopy(runtime.checkpoint(run))
    original=runtime.advance
    with Execution('FAST',signal_closes=1),DiscoveryContext(out,source_sha256=digest(parent['base']['sources'])) as context:
        published=replace(buffer.prepare(run.state,run.state.data_version+1,formation=False),
            cash_distributions=None,spinoff_distributions=())
        publication=digest(published)
        try:runtime.advance(run,published)
        except ValueError as error:need(str(error)==code,'RISK_GATE_EXACT_EXISTING_MISSING_INPUT_REFUSAL')
        else:raise ValueError('RISK_GATE_EXPECTED_ORIGINAL_INPUT_GUARD_DID_NOT_REFUSE')
        need(runtime.checkpoint(run)==prior and digest(published)==publication and context.transitions==0,
             'RISK_GATE_REFUSAL_NEVER_COMMITS_OR_MUTATES_PRIOR_OR_PUBLICATION')
        events=[json.loads(line)['event'] for line in (out/'discovery-events.jsonl').read_bytes().splitlines()]
        need(not any(e['kind']=='CORE_TRANSITION_COMMITTED' for e in events)
             and events[-1]['kind']=='DISCOVERY_TRANSITION_REFUSED','RISK_GATE_ACTUAL_REFUSAL_NOT_SUCCESS')
        commitment=context.commitment()
    need(runtime.advance is original,'RISK_GATE_REFUSAL_ORIGINAL_HOOK_RESTORED')
    result=dict(status='EXPECTED_ORIGINAL_RISK_INPUT_REFUSAL_QUALIFIED',session=day,expected_refusal=code,
        strict_parent_outer_sha256=parent['sha256'],prior_checkpoint_sha256=prior['checkpoint_sha256'],
        prior_and_publication_unchanged=True,committed_transitions=0,original_hook_restored=True,
        events=commitment,financial_authority=False,account_performance_computed=False)
    save(out/'proof.json',result);return result


def qualify(root,parent,out,*,selected_file,source_iterator,code):
    hosted()
    from research.pooled_vacancy_funding import runtime,journal,backtest
    from stock_strategy_shared.wealth_core.terminal import TerminalTerms,TerminalKind
    from stock_strategy_shared.wealth_core import v5
    from stock_strategy_shared.wealth_core.state import PortfolioState,HoldingEpisode
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from system_campaign_acceleration import Execution
    root,out=Path(root),Path(out);before=(root/selected_file).read_bytes()
    refusal=expected_refusal(root,parent,out/'expected-held-input-refusal',source_iterator,code)
    run,buffer,packets,repaired,wanted=source_iterator(parent,root)
    held={v['security_id'] for v in run.state.wealth_core['episodes'].values()}
    pending={v['security_id'] for v in run.state.pending}
    leaders=set(run.state.median5['selected'])
    need(leaders and held and len(wanted)>=3,'RISK_GATE_ACTUAL_PARENT_AND_THREE_SOURCE_DATES')
    chosen=sorted(leaders)[0];original=runtime.advance;observed=[];states=[]
    book=out/'qualification-book';book.mkdir()
    with journal.Journal(book) as stream,Execution('FAST',signal_closes=1), \
            DiscoveryContext(out,source_sha256=digest(parent['base']['sources'])) as context:
        for i,day in enumerate(wanted[:3]):
            packet=repaired(next(packets));need(packet.day==day,'RISK_GATE_EXACT_NORMAL_SESSION_AXIS')
            packet_hash=digest(packet)
            buffer.append(packet);buffer.current=packet
            publication=buffer.prepare(run.state,run.state.data_version+1,formation=False)
            run=runtime.advance(run,publication)
            need(digest(packet)==packet_hash,'RISK_GATE_ALL_ACTUAL_SOURCE_PACKET_BYTES_UNCHANGED')
            need(run.state.last_processed_session==day,'RISK_GATE_ACTUAL_CANONICAL_SESSION_ADVANCED')
            stream.append('daily',dict(schema='research.disposable-core-trading-row/1',authority=TAINT,
                session=day,state_sha256=run.state.state_hash,input_sha256=run.input_sha256,account_performance_computed=False))
            observed.append(day);states.append(run.state.state_hash)
        wrapped=discovery_checkpoint(runtime.checkpoint(run),parent_outer_sha256=parent['sha256'],
            cursor=observed[-1],transitions=3,event_chain_sha256=context.chain)
        for checker in (require_strict_checkpoint,lambda value:backtest.validate_checkpoint(value,parent['base'],[])):
            try:checker(wrapped)
            except ValueError:pass
            else:raise ValueError('RISK_GATE_DIAGNOSTIC_CHECKPOINT_ENTERED_FINANCIAL_REPLAY')
        cfg=runtime.config(parent['base']['policy'])
        core=PortfolioState.fresh(9000,n_slots=cfg.n_slots,entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
        sid='SYNTHETIC_RISK_GATE_CASH';core.episodes[0]=HoldingEpisode(sid,sid,'SYNTHETIC',0,observed[0],observed[0],100.,100.,10,10)
        core.slots[0].occupied_by=sid;ledger=Ledger();context.current=(run,publication)
        term=TerminalTerms(session=observed[-1],security_id=sid,kind=TerminalKind.CASH_MERGER,
            cash_per_share=None,reference='research:risk-discovery-toy-incomplete-cash')
        initial=deepcopy((core.to_dict(),ledger.to_dict()))
        result=context.m.terminal.apply_terminal(core,term,ledger=ledger,session=observed[-1],cfg=cfg)
        need(not result['applied'] and result['reason']=='DISCOVERY_UNSETTLED_TERMINAL'
             and (core.to_dict(),ledger.to_dict())==initial,'RISK_GATE_INCOMPLETE_TOY_CASH_SHARES_SLOT_UNCHANGED')
        term=replace(term,cash_per_share=12.5,reference='research:risk-discovery-toy-complete-cash')
        applied=context.m.terminal.apply_terminal(core,term,ledger=ledger,session=observed[-1],cfg=cfg)
        need(applied['applied'] and core.cash==9125. and not core.episodes and len(ledger.events)==1,
             'RISK_GATE_SUPPORTED_CASH_UNCHANGED')
        once=deepcopy((core.to_dict(),ledger.to_dict()))
        result=context.m.terminal.apply_terminal(core,term,ledger=ledger,session=observed[-1],cfg=cfg)
        need(result['reason']=='NOT_HELD' and (core.to_dict(),ledger.to_dict())==once,'RISK_GATE_SUPPORTED_CASH_ONCE_ONLY')
        context.current=None;commit=context.commitment()
    need(runtime.advance is original and (root/selected_file).read_bytes()==before,'RISK_GATE_ORIGINAL_HOOK_AND_STRICT_GZIP_RESTORED')
    save(out/'discovery-canonical-qualification.json',dict(schema='research.risk-discovery-qualification/1',status='QUALIFIED',
        qualification_kind='ORIGINAL_RISK_GUARDS_PRESERVED_HELD_MISSING_INPUT_REFUSED',authority=TAINT,
        strict_parent_outer_sha256=parent['sha256'],strict_parent_gzip_sha256=hashlib.sha256(before).hexdigest(),
        synthetic_canonical_transitions=3,sessions=observed,actual_core_and_controller_state_hashes=states,
        held_security_id=sorted(held)[0],leadership_security_id=chosen,expected_held_input_refusal=refusal,
        held_missing_quote_continuation=False,all_actual_held_quotes_unchanged=True,normal_source_packets_unchanged=True,
        no_invented_cash_shares_or_execution_prices=True,supported_cash_unchanged_and_once_only=True,
        incomplete_toy_position_cash_shares_and_slot_unchanged=True,actual_strict_checkpoint_rejection=True,
        strict_parent_bytes_unchanged=True,original_runtime_hook_restored=True,events=commit,
        actual_discovery_started=False,account_performance_computed=False,production_contacted=False))
