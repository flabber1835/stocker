"""Prepared reporting-contract correction; existing financial calculation reused."""
from trace_screen import advance_account
from weighted_policy import need

def account_step(prior,row,target,canonical):
    result=advance_account(prior,row,target,canonical)
    need(prior.get('research_entry_mode') in ('FORMED_BASKET','CANONICAL_COLD')
        and prior.get('measurement_anchor_session')=='2008-02-22','REFUSED_R_REPORTING_ORIGIN')
    # Same carry as frozen research/pooled_vacancy_funding/backtest.py:116-118.
    return {**result,'research_entry_mode':prior['research_entry_mode'],
        'measurement_anchor_session':prior['measurement_anchor_session']}
