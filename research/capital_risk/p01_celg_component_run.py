"""Hosted synthetic canonical component qualifier; no actual book or replay."""
import argparse
from copy import deepcopy
from dataclasses import asdict,replace
from fractions import Fraction
import json
import os
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need,save
from p01_celg_multileg_facts import PRIMARY_SHA
from p01_celg_accounting import reconcile
from p01_celg_source import PHYSICAL_SHA,FINANCIAL_SHA,SOURCE_BINDING_SHA,EXPECTED,PAYLOAD,sha,digest,verify_rendered_modules

HERE=Path(__file__).parent

def main(args):
    hosted()
    need(args.manifest==Path('/out/source-manifest.json'),'CELG_QUALIFIER_EXACT_SOURCE_ONLY_MANIFEST')
    manifest=json.loads(args.manifest.read_bytes())
    need(manifest['schema']=='research.p01-celg-component-source-successor/1'
         and not manifest['financial_predecessor_selected'] and not manifest['financial_input_admitted']
         and not manifest['financial_clock_admitted'] and not manifest['original_native_nov20_action_removed'],
         'CELG_SYNTHETIC_SOURCE_ONLY_NO_FINANCIAL_OR_CLOCK_ADOPTION')
    need(sha((HERE/'p01_celg_multileg_primary.json').read_bytes())==PRIMARY_SHA,
         'CELG_RETAINED_PUBLIC_PRIMARY_LEGAL_EXTRACTION_ONLY')
    physical={p.relative_to('/variant').as_posix():p.read_bytes() for p in Path('/variant').rglob('*') if p.is_file()}
    need(digest(manifest['predecessor_all_sources'])==PHYSICAL_SHA
         and digest(manifest['predecessor_financial_sources'])==FINANCIAL_SHA
         and manifest['original_source_binding_sha256']==SOURCE_BINDING_SHA
         and len(manifest['successor_all_sources'])==516
         and len(manifest['successor_financial_sources'])==224
         and {n:sha(raw) for n,raw in physical.items()}==manifest['successor_all_sources']
         and set(manifest['changed'])==set(EXPECTED)|{PAYLOAD}
         and manifest['successor_all_sources'][PAYLOAD]==sha((HERE/'p01_celg_component.py').read_bytes()),
         'CELG_ALL516_PHYSICAL_AND224_CANONICAL_FINANCIAL_SOURCE_BYTES')
    verify_rendered_modules(physical)
    from research.pooled_vacancy_funding import backtest
    need(backtest.source_files()==manifest['successor_financial_sources'], 'CELG_ACTUAL_CANONICAL_FINANCIAL_IDENTITY_SUBSET')
    os.environ['CELG_SYNTHETIC_COMPONENT_QUALIFICATION']='1'
    from stock_strategy_shared.wealth_core import terminal,ledger,state,engine,merger_rights
    from sentinel.controller import terminal_returns
    cfg=engine.WealthCoreConfig()
    term=terminal.MergerRightTerms(session='2019-11-21',security_id=merger_rights.SOURCE,
        kind=terminal.TerminalKind.CASH_PLUS_STOCK,cash_per_share=50.0,
        delivered_security_id=merger_rights.DELIVERED,delivered_ticker='BMY',delivered_issuer_id='SEC_CIK:14272',
        exchange_ratio='1',reference=merger_rights.REFERENCE)
    need(asdict(terminal.terminal_terms_from_dict(asdict(term)))==asdict(term),
         'CELG_ACTUAL_COMPLETE_EXTERNAL_TYPED_TERMS_ROUNDTRIP')
    book=state.PortfolioState.fresh(50000.,n_slots=cfg.n_slots)
    journal=ledger.Ledger()
    for slot,q in enumerate((7,13)):
        cash=engine.entry_cost(q,100.,cfg);before=book.cash
        journal.post(session='2019-07-01',event_type=ledger.EventType.BUY,cash_before=before,cash_delta=-cash,
            security_id=merger_rights.SOURCE,ticker='CELG',shares_delta=q,price=100.,fees=cash-q*100.,reason='SYNTHETIC_COMPONENT_SETUP')
        book.cash-=cash
        book.episodes[slot]=state.HoldingEpisode(security_id=merger_rights.SOURCE,ticker='CELG',issuer_id='SEC_CIK:816284',
            slot_id=slot,signal_date='2019-06-28',entry_date='2019-07-01',entry_raw_open=100.,
            entry_split_adjusted_price=200.,initial_shares=q,current_shares=q,
            episode_peak_split_adjusted_close=240.,market_sessions_held=80,review_completed=True,exit_pending=True,
            exit_reason='SYNTHETIC_PENDING_EXIT')
        book.slots[slot].occupied_by=merger_rights.SOURCE
    before=deepcopy(book.to_dict());old_events=deepcopy(journal.to_dict()['events'])
    result=terminal.apply_terminal(book,term,ledger=journal,session=term.session,cfg=cfg,
        source_signal_to_raw_scale=2.,delivered_signal_to_raw_scale=3.,delivered_raw_open=60.)
    need(result['converted'] and journal.to_dict()['events'][:len(old_events)]==old_events,
         'CELG_CANONICAL_CONVERSION_AND_OLD_LEDGER_PREFIX')
    multiplier=float(Fraction(60)/Fraction('112.30'))
    for slot,ep in book.episodes.items():
        old=before['episodes'][str(slot)]
        need(ep.security_id==merger_rights.DELIVERED and ep.current_shares==old['current_shares']
             and ep.entry_raw_open==old['entry_raw_open']*multiplier
             and ep.entry_split_adjusted_price==old['entry_split_adjusted_price']*(1.5*multiplier)
             and ep.episode_peak_split_adjusted_close==old['episode_peak_split_adjusted_close']*(1.5*multiplier)
             and ep.market_sessions_held==80 and ep.review_completed and ep.exit_pending,
             'CELG_ACTUAL_CANONICAL_QUANTITY_REFERENCE_AGE_REVIEW_AND_PENDING_CONTINUATION')
    serialized=journal.to_dict()
    need(ledger.Ledger.from_dict(serialized).to_dict()==serialized
         and state.PortfolioState.from_dict(book.to_dict()).to_dict()==book.to_dict(),
         'CELG_FULL_ACTUAL_CANONICAL_LEDGER_AND_STATE_ROUNDTRIP')
    prior=SimpleNamespace(median5={'selected':[merger_rights.SOURCE]},last_processed_session='2019-11-20',
        feed={'series':{merger_rights.SOURCE:{'signal_basis_anchor':['2019-11-20',100.,200.]}}})
    # This qualifier uses an explicit publication-shaped synthetic component.
    # It never fabricates a source publication, historical run or predecessor.
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class ComponentPublication:
        session:str
        terminal_events:tuple
        bars:tuple
    publication=ComponentPublication('2019-11-21',(term,),
        (SimpleNamespace(security_id=merger_rights.DELIVERED,session='2019-11-21',raw_close=65.,raw_open=60.),))
    witness=terminal_returns.values(prior=prior,published=publication)
    need(witness[merger_rights.SOURCE]==234.5,'CELG_INDEPENDENT_CANONICAL_CLOSING_CONSIDERATION')
    journal_before=deepcopy(serialized)
    repeated=terminal.apply_terminal(book,term,ledger=journal,session=term.session,cfg=cfg,
        source_signal_to_raw_scale=2.,delivered_signal_to_raw_scale=3.,delivered_raw_open=60.)
    need(repeated.get('reason')=='NOT_HELD' and journal.to_dict()==journal_before,'CELG_ONCE_ONLY_TERMINAL_APPLICATION')
    prices={merger_rights.DELIVERED:dict(raw_price=65.,status='CURRENT')}
    snapshot=dict(wealth_core=book.to_dict(),ledger=journal.to_dict(),prices=prices,
        resolved_equity=book.cash+20*65.)
    accounting=reconcile(snapshot)
    mark=SimpleNamespace(resolves_equity=True,value_per_share=65.,is_tradeable_mark=True,raw_mark_close=65.,
                         status=SimpleNamespace(value='CURRENT'))
    report=terminal.final_report(session=term.session,state=book,marks={merger_rights.DELIVERED:mark},ledger=journal,cfg=cfg).to_dict()
    need(len(report['merger_rights_received_and_liquidated'])==1,'CELG_DISTINCT_REPORT_RIGHT_FLOW_NO_NULL_STOCK_SORT')
    save(Path('/out/celg-positive-component-case.json'),dict(
        status='ACTUAL_CANONICAL_SYNTHETIC_COMPONENT_POSITIVE_PASSED',terms=asdict(term),actual_result=result,
        actual_ledger=serialized,actual_state=book.to_dict(),independent_accounting=accounting,
        leadership_close_value=witness[merger_rights.SOURCE],report=report,
        external_typed_terms_roundtrip=True,all_positions_and_prices_explicitly_synthetic=True,
        actual_provider_response_transferred=False,financial_input_admitted=False,actual_predecessor_used=False))
    refusals=[]
    def action(candidate,records,**changes):
        values=dict(ledger=records,session=term.session,cfg=cfg,source_signal_to_raw_scale=2.,
                    delivered_signal_to_raw_scale=3.,delivered_raw_open=60.)
        values.update(changes)
        return terminal.apply_terminal(candidate,term,**values)
    def refused(label,call,prefix,setup=None):
        candidate=state.PortfolioState.from_dict(deepcopy(before))
        records=ledger.Ledger.from_dict(dict(events=deepcopy(old_events),receivables=[]))
        if setup is not None:setup(candidate,records)
        original_state=deepcopy(candidate.to_dict());original_records=deepcopy(records.to_dict())
        try:call(candidate,records)
        except (ValueError,RuntimeError) as error:
            need(str(error).startswith(prefix),'CELG_QUALIFICATION_EXPECTED_EXACT_REFUSAL:'+label)
            error_type=type(error).__name__
        else:raise ValueError('CELG_QUALIFICATION_FALSIFIER_ACCEPTED:'+label)
        need(candidate.to_dict()==original_state and records.to_dict()==original_records,
             'CELG_ACTUAL_NEGATIVE_CASE_NO_CALLER_STATE_OR_LEDGER_MUTATION:'+label)
        refusals.append(dict(case=label,expected_error_prefix=prefix,error_class=error_type,caller_unchanged=True))
        save(Path('/out')/('celg-negative-'+label+'.json'),refusals[-1])
    for missing in ('right_identity','right_quote'):
        def missing_field(candidate,records,name=missing):
            raw=asdict(term);raw.pop(name);terminal.terminal_terms_from_dict(raw)
        refused('MISSING_'+missing.upper(),missing_field,'REFUSED_CELG_COMPONENT_EXACT_TYPED')
    def wrong_quote(candidate,records):
        raw=asdict(term);raw['right_quote']['session']='2019-11-20';terminal.terminal_terms_from_dict(raw)
    refused('WRONG_QUOTE_DATE',wrong_quote,'REFUSED_CELG_COMPONENT_EXACT_TYPED')
    def wrong_open(candidate,records):
        raw=asdict(term);raw['right_quote']['raw_open']='2.25';terminal.terminal_terms_from_dict(raw)
    refused('CLOSE_CANNOT_BECOME_OPEN',wrong_open,'REFUSED_CELG_COMPONENT_EXACT_TYPED')
    def combined_cash(candidate,records):
        raw=asdict(term);raw['cash_per_share']=52.30;terminal.terminal_terms_from_dict(raw)
    refused('RIGHT_VALUE_CANNOT_BECOME_LEGAL_CASH',combined_cash,'REFUSED_CELG_COMPONENT_EXACT_TYPED')
    refused('NOV20_CANNOT_USE_NOV21_QUOTE',lambda candidate,records:action(candidate,records,session='2019-11-20'),
            'REFUSED_CELG_COMPONENT_ONLY_NOV21')
    def fractional_setup(candidate,records):candidate.episodes[0].current_shares+=.5
    refused('UNSUPPORTED_FRACTIONAL_RIGHT',action,'REFUSED_CELG_COMPONENT_FRACTIONAL_RIGHT',setup=fractional_setup)
    def bad_allocation(candidate,records):
        original=terminal._conversion_allocations
        def altered(*args,**kwargs):
            values=original(*args,**kwargs);values[0]=replace(values[0],delivered=values[0].delivered+.1);return values
        terminal._conversion_allocations=altered
        try:action(candidate,records)
        finally:terminal._conversion_allocations=original
    refused('ACTUAL_CANONICAL_NONCONSERVING_ALLOCATION',bad_allocation,'REFUSED_CELG_COMPONENT_CANONICAL_BMY_ALLOCATION')
    def late_failure(candidate,records):
        original=ledger.Ledger.post
        def fail(owner,**kwargs):
            if kwargs['event_type'] is ledger.EventType.MERGER_RIGHT_LIQUIDATION:
                raise RuntimeError('SYNTHETIC_LATE_RIGHT_SALE_FAILURE')
            return original(owner,**kwargs)
        ledger.Ledger.post=fail
        try:action(candidate,records)
        finally:ledger.Ledger.post=original
    refused('ACTUAL_LATE_SALE_FAILURE_ATOMIC',late_failure,'SYNTHETIC_LATE_RIGHT_SALE_FAILURE')
    def financial_admission(candidate,records):
        os.environ.pop('CELG_SYNTHETIC_COMPONENT_QUALIFICATION',None)
        try:action(candidate,records)
        finally:os.environ['CELG_SYNTHETIC_COMPONENT_QUALIFICATION']='1'
    refused('NO_FINANCIAL_MODE_OR_PREDECESSOR_ADMISSION',financial_admission,'REFUSED_CELG_COMPONENT_HOSTED_SYNTHETIC_ONLY')
    # Changing the separately evaluated canonical sale cost cannot affect the
    # independent closing-sensor value; it has no account/order/cost input.
    alternative=SimpleNamespace(transaction_cost_bps=20.)
    need(engine.exit_proceeds(20,2.30,alternative)!=engine.exit_proceeds(20,2.30,cfg)
         and terminal_returns.values(prior=prior,published=publication)==witness,
         'CELG_ACTUAL_CANONICAL_COST_CHANGE_CANNOT_CHANGE_CLOSING_SENSOR')
    save(Path('/out/celg-synthetic-component-qualification.json'),dict(
        schema='research.celg-synthetic-canonical-component-qualification/1',
        status='SYNTHETIC_COMPONENT_CASE_PASSED_NOT_FINANCIAL_ADMISSION',source_manifest=manifest,
        terms=asdict(term),actual_result=result,actual_ledger=serialized,actual_state=book.to_dict(),
        independent_accounting=accounting,leadership_close_value=witness[merger_rights.SOURCE],report=report,
        actual_canonical_negative_cases=refusals,actual_cost_change_leadership_invariance=True,
        all_prices_and_parent_positions_explicitly_synthetic=True,retained_right_quote_authenticated=False,
        actual_provider_response_transferred=False,synthetic_right_quote=merger_rights.quote(),
        actual_predecessor_used=False,financial_input_admitted=False,recognition_clock_admitted=False,
        production_contacted=False,qualification_gaps=[
            'Actual next admitted own P01 pre-event boundary, input/roles and market-clock admission remain unselected.',
            'This synthetic component result is not a canonical whole-session or financial replay certificate.']))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);main(parser.parse_args())
