"""E2: real issuer ratio, synthetic neutral prices, pristine source path."""
from decimal import Decimal
import json
from sentinel.feed.domains import NormalisationReport, normalise_sep_rows
from sentinel.feed.actions_map import split_disagreements, splits_only_derived
from stock_strategy_shared.split_reconciliation import SplitAuthority
from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode

DEN = Decimal('10.89958')
SOURCE = 'https://www.sec.gov/Archives/edgar/data/1940674/000149315225018742/ex99-1.htm'

def run_case(stated):
    authority = SplitAuthority({('SMX', '2025-10-23'): float(stated)})
    rows = [dict(ticker='SMX', date=day, open=str(DEN), close=str(DEN),
        closeunadj=raw, volume='1000000', closeadj=str(DEN))
        for day, raw in [('2025-10-22', '1'), ('2025-10-23', str(DEN))]]
    report = NormalisationReport()
    nb = list(normalise_sep_rows(rows,
        resolve_identity=lambda _t, _d: 'SMX_SID',
        authoritative_splits=authority, report=report))[-1]
    st = PortfolioState.fresh(10000.0)
    st.initialized = True
    old_shares = 1089958
    st.slots[0].occupied_by = 'SMX_SID'
    st.episodes[0] = HoldingEpisode('SMX_SID', 'SMX', 'SID:SMX_SID', 0,
        '2025-10-01', '2025-10-02', 1., float(DEN), old_shares,
        old_shares, float(DEN))
    bar = DailyBar(security_id='SMX_SID', ticker='SMX', issuer_id='SID:SMX_SID',
        session='2025-10-23', signal_close_split_adj_div_unadj=nb.close_signal,
        raw_open=nb.vendor.raw_open, raw_mark_close=nb.vendor.raw_close,
        split_ratio=nb.vendor.split_ratio, tradeable=True)
    out = step_session(session='2025-10-23', state=st, bars=[bar], pending=[],
        ledger=Ledger(), last_known={'SMX_SID': 1.}, cfg=WealthCoreConfig(),
        strategy_id='audit', strategy_version=1, security_bars=[])
    oracle_new_shares = Decimal(old_shares)/DEN
    oracle_nav = Decimal('10000')+oracle_new_shares*DEN
    return dict(issuer_source=SOURCE, issuer_old_per_new=str(DEN),
        supplied_authority=str(stated), applied_ratio=nb.vendor.split_ratio,
        disposition=report.split_dispositions[('SMX', '2025-10-23')],
        disagreements=split_disagreements(report, authority),
        derived_only=splits_only_derived(report, authority),
        old_shares=old_shares, actual_shares=st.episodes[0].current_shares,
        issuer_oracle_shares=str(oracle_new_shares),
        actual_open_nav=out.resolved_open_equity, issuer_oracle_nav=str(oracle_nav),
        false_loss=float(oracle_nav)-out.resolved_open_equity)

if __name__ == '__main__':
    cases = [run_case(Decimal(1)/DEN), run_case(Decimal('0.09175'))]
    print(json.dumps({'finding': 'E2', 'status': 'DEFECT_REPRODUCED',
                      'cases': cases}, indent=2, sort_keys=True))
    for c in cases:
        assert c['applied_ratio'] == 1/11
        assert c['disposition']['disposition'] == 'corroborated_direct'
        assert c['disagreements'] == c['derived_only'] == []
        assert c['issuer_oracle_shares'] == '1E+5'
        assert c['false_loss'] > 9900
