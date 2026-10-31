"""Hosted positive canonical consideration/removal case; never a financial origin."""
from copy import deepcopy
import json

from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest


def require_positive(core,ledger,sid):
    paid=[v for v in ledger.events if v.security_id==sid and v.event_type.value=='CASH_MERGER']
    need(core.cash==9600. and not core.episodes and len(paid)==1
         and paid[0].price==60. and paid[0].cash_delta==600. and paid[0].shares_delta==-10.,
         'LBPH_CANONICAL_POSITIVE_60_CASH_REMOVAL')


def qualify_held(out,cp,facts):
    hosted()
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core import v5
    from stock_strategy_shared.wealth_core.state import PortfolioState,HoldingEpisode
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict,apply_terminal
    term,=facts.catalog['terms'];sid=term['security_id'];day=term['added']['session']
    payload=json.loads((out/facts.catalog['commitment_group']['private_file']).read_bytes())
    witness,=payload['source_witnesses']
    need(witness['session']=='2024-11-29' and witness['security_id']==sid
         and payload['recognition_quote_qualification']['actual_recognition_quotes']==[],
         'LBPH_ACTUAL_LAST_TRADE_AND_FULL_RECOGNITION_QUOTE_ABSENCE')
    restored=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored)==cp['run'],'LBPH_CANONICAL_ACTUAL_PARENT_ROUNDTRIP')
    cfg=runtime.config(cp['base']['policy'])
    core=PortfolioState.fresh(9000,n_slots=cfg.n_slots,entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
    ep=HoldingEpisode(sid,'LBPH','SEC_CIK:1832168',0,'2024-11-26','2024-11-29',
        float(witness['raw_close']),float(witness['signal_close']),10,10,
        episode_peak_split_adjusted_close=float(witness['signal_close']),market_sessions_held=17,
        review_completed=True,source_lots=[dict(kind='EXPLICIT_DISPOSABLE_LBPH_COMPONENT_FIXTURE')])
    core.episodes[0]=ep;core.slots[0].occupied_by=sid;ledger=Ledger()
    result=apply_terminal(core,terminal_terms_from_dict(term['added']),ledger=ledger,session=day,cfg=cfg)
    need(result['applied'] is True,'LBPH_POSITIVE_CANONICAL_CASE_ACTUALLY_APPLIED')
    require_positive(core,ledger,sid)
    once=deepcopy((core.to_dict(),ledger.to_dict()))
    repeat=apply_terminal(core,terminal_terms_from_dict(term['added']),ledger=ledger,session=day,cfg=cfg)
    need(repeat==dict(applied=False,reason='NOT_HELD',security_id=sid)
         and (core.to_dict(),ledger.to_dict())==once,'LBPH_REPEAT_CANONICAL_CASH_UNCHANGED')
    # Mutate only the disposable result, never the actual predecessor or source.
    core.cash-=1
    try:require_positive(core,ledger,sid)
    except ValueError as error:need(str(error)=='REFUSED_FULL_SYSTEM_LBPH_CANONICAL_POSITIVE_60_CASH_REMOVAL',
                                   'LBPH_POSITIVE_CASE_MUTATION_EXACT_REASON')
    else:raise ValueError('REFUSED_LBPH_POSITIVE_CASE_MUTATION_WAS_NOT_REJECTED')
    core.cash+=1;require_positive(core,ledger,sid)
    need(runtime.checkpoint(restored)==cp['run'],'LBPH_DISPOSABLE_CASE_LEAVES_ACTUAL_PARENT_UNCHANGED')
    save(out/'lbph-positive-cash-canonical-qualification.json',dict(
        status='LBPH_POSITIVE_CANONICAL_CASH_REMOVAL_AND_ONCE_ONLY_QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'],last_trading_source_sha256=digest(witness),
        fixture_shares=10,fixture_cash=600.,actual_positive_cash_and_position_removal=True,
        actual_once_only_payment=True,actual_changed_cash_falsifier_passed=True,
        actual_parent_roundtrip=True,actual_parent_unchanged=True,
        qualification_copy_only=True,financial_sessions_advanced=0,production_contacted=False))
