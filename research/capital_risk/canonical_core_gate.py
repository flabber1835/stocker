"""Hosted synthetic tests through the actual frozen/patched canonical adapter."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
import unittest

from stock_strategy_shared.wealth_core import v5,median5
from stock_strategy_shared.wealth_core.adapter import PendingOrder,step_session
from stock_strategy_shared.wealth_core.engine import Operation,SecurityBar,Reason,Decision
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState,HoldingEpisode
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.marks import Mark,MarkStatus
from stock_strategy_shared.wealth_core.terminal import TerminalKind,TerminalTerms,apply_terminal
from sentinel.feed.calendar import previous_sessions

ORIGINAL='wealth-core-v5-zero-share-fixed-2008-v1'
C='wealth-core-capital-risk-c-v1';V='wealth-core-capital-risk-v-v1'
DAY='2026-01-05';NEXT='2026-01-06'


def fixture(profile=ORIGINAL,quantity=10,cash=9000):
    cfg=v5.research_config(profile)
    state=PortfolioState.fresh(cash,n_slots=20,entry_sizing_profile=profile)
    state.median5=median5.fresh();state.median5['formation_started']=True
    state.initialized=True
    ep=HoldingEpisode('S','S','SID:S',0,'2025-12-01','2025-12-02',100,100,
        quantity,quantity,episode_peak_split_adjusted_close=100,
        market_sessions_held=17,review_completed=True,source_lots=[dict(kind='SYNTHETIC')])
    state.episodes[0]=ep;state.slots[0].occupied_by='S'
    if profile==V:ep.research_stop_floor=90;ep.research_stop_cursor='2026-01-02'
    return state,[],Ledger(),{'S':100},cfg


def security(day,signal,raw=None,values=None):
    kwargs={}
    if 'signal_sessions' in SecurityBar.__dataclass_fields__:
        kwargs['signal_sessions']=previous_sessions(day,21)
    return SecurityBar('S','S','SID:S',values or [signal]*127,
        raw_close=signal if raw is None else raw,eligible=False,**kwargs)


def step(parts,day,*,signal=100,raw=None,opening=None,split=1,tradeable=True,terminal=(),values=None):
    state,pending,ledger,last,cfg=parts
    raw=signal if raw is None else raw
    b=DailyBar('S','S','SID:S',day,signal,raw if opening is None else opening,raw,
        tradeable=tradeable,split_ratio=split)
    return step_session(session=day,state=state,pending=pending,ledger=ledger,
        last_known=last,cfg=cfg,strategy_id='RESEARCH_SYNTHETIC',strategy_version=1,
        bars=[b],security_bars=[security(day,signal,raw,values)],terminal_terms=terminal)


def snapshot(parts,result):
    state,pending,ledger,_,_=parts
    return dict(state=state.to_dict(),pending=[p.to_dict() for p in pending],ledger=ledger.to_dict(),
        decision=result.decision.to_dict(),fills=result.fills,equity=result.resolved_equity,
        open_equity=result.resolved_open_equity,cancelled=result.cancelled,
        opening_accounting=result.research_open_audit,closing_accounting=result.research_close_audit)


def baseline_path():
    parts=fixture();records=[]
    for args in ((DAY,101,101,101,1),(NEXT,100,50,50,2),
                 ('2026-01-07',70,35,35,1),('2026-01-08',80,40,40,1)):
        day,signal,raw,opening,split=args
        result=step(parts,day,signal=signal,raw=raw,opening=opening,split=split)
        records.append(snapshot(parts,result))
    return records


class CanonicalCases(unittest.TestCase):
    def test_accounting_tap_observes_actions_before_fills_and_decisions_after(self):
        p=fixture(C,20,8000);step(p,DAY);result=step(p,NEXT,signal=200,opening=200)
        opened,closed=result.research_open_audit,result.research_close_audit
        self.assertEqual(opened['wealth_core']['episodes']['0']['current_shares'],20)
        self.assertEqual(opened['wealth_core']['cash'],8000)
        self.assertEqual(opened['prices']['S']['raw_price'],200)
        self.assertEqual(closed['wealth_core']['episodes']['0']['current_shares'],8)
        self.assertAlmostEqual(closed['wealth_core']['cash'],10397.6)
        self.assertEqual(closed['wealth_core'],p[0].to_dict())
        opened['wealth_core']['cash']=0
        self.assertAlmostEqual(p[0].cash,10397.6)  # no writable alias into the book
        opened['pending'][0]['risk_detail']['holder_target']=0
        self.assertEqual(p[2].events[-1].detail['signal_detail']['holder_target'],8)

    def test_dated_volatility_history_survives_compact_material_and_basis_transform(self):
        from sentinel.core.window_material import Signal,WindowFeatures
        bar=security(DAY,100,values=[80+float(n) for n in range(21)])
        wire=Signal.from_feature(bar)
        restored=Signal.model_validate_json(wire.model_dump_json()).bar(multiplier=2)
        self.assertEqual(list(restored.closes),[2*v for v in bar.closes])
        self.assertEqual(list(restored.signal_sessions),previous_sessions(DAY,21))
        self.assertEqual(WindowFeatures.model_fields['schema_id'].default,
            'sentinel.current-window-features-capital-risk/1')

    def test_profiles_preserve_unpooled_admission_and_both_cooldowns(self):
        for profile in (C,V):
            cfg=v5.research_config(profile)
            self.assertEqual((cfg.n_slots,cfg.entry_weight),(20,.05))
            self.assertNotIn(profile,v5.POOLED_PROFILES)
            self.assertEqual(v5.research_admission(equity=50000,cash=50000,price=100,profile=profile),
                v5.admission(equity=50000,cash=50000,price=100))
            self.assertEqual(v5.research_admission(equity=50000,cash=50000,price=3000,profile=profile)[0],None)

    def test_canonical_trim_queue_next_open_gap_cost_and_episode_continuity(self):
        p=fixture(C,20,8000);entry=deepcopy(p[0].episodes[0])
        first=step(p,DAY)
        self.assertEqual(p[0].cash,8000);self.assertEqual(p[0].episodes[0].current_shares,20)
        self.assertEqual(len(p[1]),1);self.assertEqual(p[1][0].operation,Operation.REDUCE_POSITION)
        self.assertEqual(p[1][0].shares,12)
        self.assertEqual(first.fills,[])
        second=step(p,NEXT,signal=200,opening=200)
        ep=p[0].episodes[0]
        self.assertEqual(ep.current_shares,8)  # original close target, not 4 at the gapped open
        self.assertAlmostEqual(p[0].cash,10397.6)
        self.assertEqual(ep.entry_date,entry.entry_date);self.assertTrue(ep.review_completed)
        self.assertEqual(ep.market_sessions_held,entry.market_sessions_held+2)
        self.assertEqual(ep.source_lots,entry.source_lots)
        self.assertFalse(p[0].slots[0].in_cooldown);self.assertNotIn('S',p[0].security_cooldowns)
        event=[e for e in p[2].events if e.event_type.value=='SELL'][0]
        self.assertEqual(event.shares_delta,-12);self.assertAlmostEqual(event.fees,2.4)
        self.assertEqual(second.fills[0]['operation'],'REDUCE_POSITION')

    def test_strict_ten_percent_boundary_and_zero_target_full_exit(self):
        p=fixture(C,10,9000);step(p,DAY);self.assertEqual(p[1],[])
        p=fixture(C,1,0);step(p,DAY)
        self.assertEqual(p[1][0].operation,Operation.CLOSE_POSITION)
        step(p,NEXT)
        self.assertEqual(p[0].episodes,{})
        self.assertEqual(p[0].slots[0].cooldown_sessions_elapsed,0)
        self.assertEqual(p[0].security_cooldowns['S'],0)

    def test_fractional_episodes_keep_exact_pro_rata_entitlements(self):
        p=fixture(C,1.5,3350);state=p[0]
        second=deepcopy(state.episodes[0]);second.slot_id=1;second.current_shares=2.5;second.initial_shares=2.5
        state.episodes[1]=second;state.slots[1].occupied_by='S'
        step(p,DAY);self.assertEqual([o.shares for o in p[1]],[.375,.625])
        # Reconstruct the actual pending/state before next-open processing.
        state=PortfolioState.from_dict(state.to_dict());pending=[PendingOrder.from_dict(o.to_dict()) for o in p[1]]
        p=(state,pending,p[2],p[3],p[4]);step(p,NEXT)
        self.assertEqual([e.current_shares for e in state.episodes.values()],[1.125,1.875])
        self.assertEqual(sum(Fraction(str(e.current_shares)) for e in state.episodes.values()),3)

    def test_unrepresentable_pro_rata_refuses_before_quantities_or_intents_change(self):
        from stock_strategy_shared.wealth_core import capital_risk as risk
        p=fixture(C,1,2200);state=p[0]
        second=deepcopy(state.episodes[0]);second.slot_id=1;second.current_shares=2;second.initial_shares=2
        state.episodes[1]=second;state.slots[1].occupied_by='S'
        decision=Decision('SYNTHETIC',1,DAY,0,state.state_hash(),p[4].config_hash())
        before=state.to_dict()
        with self.assertRaisesRegex(ValueError,'REPRESENTATION'):
            risk.trim_decisions(state=state,bars=[security(DAY,100)],marks={'S':Mark('S',MarkStatus.CURRENT,raw_mark_close=100)},cfg=p[4],pending=[],decision=decision,noncash_assets=0)
        self.assertEqual(state.to_dict(),before);self.assertEqual(decision.operations,[])

    def test_split_transforms_pending_trim_and_full_stop_supersedes_waiting_trim(self):
        p=fixture(C,20,8000);step(p,DAY)
        step(p,NEXT,signal=100,raw=50,opening=50,split=2)
        self.assertEqual(p[0].episodes[0].current_shares,16)
        self.assertEqual(p[2].events[-1].shares_delta,-24)
        p=fixture(C,20,8000);step(p,DAY)
        result=step(p,NEXT,signal=65,opening=65,tradeable=False)
        self.assertTrue(any(r['reason']=='FULL_CLOSE_SUPERSEDES_TRIM' for r in result.cancelled))
        self.assertEqual(len(p[1]),1);self.assertEqual(p[1][0].operation,Operation.CLOSE_POSITION)
        step(p,'2026-01-07',signal=65,opening=65);self.assertEqual(p[0].episodes,{})

    def test_pending_trim_conversion_refuses_and_cash_terminal_extinguishes(self):
        p=fixture(C,20,8000);step(p,DAY);before=p[0].to_dict()
        conversion=TerminalTerms(NEXT,'S',TerminalKind.CONVERSION,delivered_security_id='D',
            delivered_ticker='D',delivered_issuer_id='SID:D',exchange_ratio=2,reference='SYNTHETIC')
        with self.assertRaisesRegex(ValueError,'PENDING_TRIM_CONVERSION'):step(p,NEXT,terminal=[conversion])
        self.assertEqual(p[0].to_dict(),before)
        cash=TerminalTerms(NEXT,'S',TerminalKind.CASH_MERGER,cash_per_share=120,reference='SYNTHETIC')
        step(p,NEXT,terminal=[cash]);self.assertEqual(p[0].episodes,{})
        self.assertAlmostEqual(p[0].cash,10400)
        self.assertFalse(p[1]);self.assertEqual(sum(e.event_type.value=='CASH_MERGER' for e in p[2].events),1)

    def test_v_inclusive_old_floor_crossing_precedes_volatility_update(self):
        p=fixture(V);step(p,DAY,signal=90,values=[100 if n%2 else 200 for n in range(126)]+[90])
        self.assertEqual(p[1][0].reason,'EXIT_TRAILING_STOP')
        self.assertEqual(p[0].episodes[0].research_stop_floor,90)
        step(p,NEXT,signal=80,opening=80);self.assertEqual(p[0].episodes,{})

    def test_v_first_owned_close_ratchet_no_loosening_missing_and_restore(self):
        cfg=v5.research_config(V);state=PortfolioState.fresh(50000,20,entry_sizing_profile=V)
        state.median5=median5.fresh();state.median5['formation_started']=True;state.initialized=True
        state.reserve_slot(0,'S','S','SID:S')
        order=PendingOrder(Operation.OPEN_SLOT_POSITION,'S','S',0,0,'2026-01-02','ENTRY_DURABLE_RANK',intended_dollars=2500)
        p=(state,[order],Ledger(),{},cfg);step(p,DAY)
        ep=state.episodes[0];self.assertEqual((ep.market_sessions_held,ep.research_stop_floor),(0,85))
        restored=PortfolioState.from_dict(state.to_dict());self.assertEqual(restored.to_dict(),state.to_dict())
        step(p,NEXT,signal=100,values=[100 if n%2 else 200 for n in range(126)]+[100])
        self.assertEqual(ep.research_stop_floor,85)
        bad=state.to_dict();bad['episodes']['0'].pop('research_stop_floor')
        with self.assertRaises(ValueError):PortfolioState.from_dict(bad)
        bad=state.to_dict();bad['entry_sizing_profile']=C
        with self.assertRaises(ValueError):PortfolioState.from_dict(bad)
        with self.assertRaisesRegex(ValueError,'VOLATILITY_CLOSE'):step(p,'2026-01-07',values=[None]+[100]*20)

    def test_v_forward_split_does_not_rescale_and_conversion_does(self):
        p=fixture(V);step(p,DAY,signal=100,raw=50,split=2)
        self.assertEqual(p[0].episodes[0].research_stop_floor,90)
        self.assertEqual(p[0].episodes[0].current_shares,20)
        p=fixture(V)
        terms=TerminalTerms(DAY,'S',TerminalKind.CONVERSION,delivered_security_id='D',
            delivered_ticker='D',delivered_issuer_id='SID:D',exchange_ratio=2,reference='SYNTHETIC')
        result=apply_terminal(p[0],terms,ledger=p[2],session=DAY,cfg=p[4],
            delivered_raw_open=50,source_signal_to_raw_scale=1,delivered_signal_to_raw_scale=1)
        self.assertTrue(result['applied']);ep=p[0].episodes[0]
        self.assertEqual((ep.research_stop_floor,ep.episode_peak_split_adjusted_close),(45,50))
        self.assertEqual(ep.current_shares,20)

    def test_v_spinoff_floor_uses_same_reference_multiplier(self):
        from sentinel.core.spinoffs import SpinoffDistribution,LIQUIDATE_CHILD_AT_OPEN,apply_supported_entitlements
        p=fixture(V)
        event=SpinoffDistribution(DAY,'S','S','D','D','SYNTHETIC','SYNTHETIC',
            child_shares_per_parent='.1',policy=LIQUIDATE_CHILD_AT_OPEN)
        bars=[DailyBar('S','S','SID:S',DAY,80,80,80),DailyBar('D','D','SID:D',DAY,20,20,20)]
        apply_supported_entitlements(p[0],[event],bars=bars,ledger=p[2],config=p[4])
        ep=p[0].episodes[0];scale=80/(80+.1*20)
        self.assertAlmostEqual(ep.research_stop_floor,90*scale)
        self.assertAlmostEqual(ep.episode_peak_split_adjusted_close,100*scale)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['basis','risk'],required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--basis-output',type=Path)
    args=parser.parse_args()
    assert str(Path(v5.__file__).resolve()).startswith('/variant/shared/')
    if args.phase=='basis':
        args.output.write_text(json.dumps(baseline_path(),sort_keys=True)+'\n');print('BASIS_SYNTHETIC_PATH_RETAINED');return
    assert args.basis_output is not None
    assert baseline_path()==json.loads(args.basis_output.read_bytes()),'B0_NOT_EQUIVALENT_TO_ORIGINAL_B'
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CanonicalCases)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(2)
    # Execute intentional guard removals against the same actual canonical cases.
    import stock_strategy_shared.wealth_core.capital_risk as risk
    original=risk.exact_float;risk.exact_float=lambda value:float(value)
    detected=unittest.TestResult();CanonicalCases('test_unrepresentable_pro_rata_refuses_before_quantities_or_intents_change').run(detected)
    risk.exact_float=original
    assert not detected.wasSuccessful(),'MISSING_REPRESENTABILITY_GUARD_NOT_DETECTED'
    text=Path(risk.__file__).read_text();namespace=dict(risk.__dict__)
    exec(compile(text.replace('if old is not None and Fraction(str(price))<=Fraction(str(old)):','if False:'),risk.__file__,'exec'),namespace)
    original=risk.volatility_stop;risk.volatility_stop=namespace['volatility_stop']
    detected=unittest.TestResult();CanonicalCases('test_v_inclusive_old_floor_crossing_precedes_volatility_update').run(detected)
    risk.volatility_stop=original
    assert not detected.wasSuccessful(),'MISSING_OLD_FLOOR_GUARD_NOT_DETECTED'
    args.output.write_text(json.dumps(dict(status='CANONICAL_CORE_GATE_PASSED',cases=result.testsRun,
        B0_synthetic_path_matched=True,removal_falsifiers=['representability','old_floor'],
        economic_results=False,production_contacted=False),indent=2)+'\n')
    print('CANONICAL_CORE_GATE_PASSED')


if __name__=='__main__':main()
