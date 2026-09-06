"""Causal, state, accounting, and source-seam falsifiers for research observers."""
from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from backtester import research_champion_spy_iwm_observers as m


def row(healthy: bool = True) -> dict:
    values = {}
    for symbol in ('spy', 'iwm'):
        values.update({f'{symbol}_r20': .03 if healthy else -.06,
                       f'{symbol}_r40': .06 if healthy else -.08,
                       f'{symbol}_dd126': -.02 if healthy else -.15,
                       f'{symbol}_ratio': .8 if healthy else 1.5})
        values.update({f'{symbol}_trend{n}': .03 if healthy else -.05 for n in m.MA_GRID})
    values['vix_lag1'] = 18. if healthy else 30.
    return values


def cfg(family='spy_iwm') -> m.Config:
    return m.Config(family, 120, -.10, 1.2)


def prices() -> pd.Series:
    dates = pd.bdate_range('2000-01-03', periods=450)
    returns = np.random.default_rng(1701).normal(.0003, .012, len(dates))
    return pd.Series(100 * np.cumprod(1 + returns), index=dates)


class DataTests(unittest.TestCase):
    def test_preregistered_grid_is_bounded_unique(self):
        grid = m.configs()
        self.assertEqual(len(grid), 81)
        self.assertEqual(len({c.name for c in grid}), 81)
        self.assertEqual(sum(c.central for c in grid), 3)
        for bad in [('bad',120,-.10,1.2),('spy',100,-.10,1.2),('spy',120,-.11,1.2)]:
            with self.assertRaises(ValueError): m.Config(*bad)

    def test_features_are_prefix_causal(self):
        p = prices()
        expected = m.features(p.iloc[:301])
        altered = p.copy(); altered.iloc[301:] *= 17
        assert_frame_equal(expected, m.features(altered).iloc[:301], rtol=1e-12, atol=1e-12)

    def test_features_are_scale_invariant(self):
        p = prices()
        assert_frame_equal(m.features(p), m.features(p*8), rtol=1e-10, atol=1e-12)

    def test_features_enforce_lookback_and_ddof(self):
        p = prices(); f = m.features(p)
        self.assertTrue(f.trend160.iloc[:159].isna().all())
        self.assertTrue(f.dd126.iloc[:125].isna().all())
        r = p.pct_change(fill_method=None)
        self.assertAlmostEqual(f.rv20.iloc[-1], r.iloc[-20:].std(ddof=1)*math.sqrt(252))
        self.assertAlmostEqual(f.dd126.iloc[-1], p.iloc[-1]/p.iloc[-126:].max()-1)

    def test_constant_prices_have_finite_volatility_ratio(self):
        p = pd.Series(100., index=pd.bdate_range('2000-01-01', periods=200))
        self.assertEqual(m.features(p).ratio.iloc[-1], 1.)

    def test_duplicate_or_reversed_feature_calendar_refuses(self):
        p=prices()
        for bad in (p.iloc[::-1], pd.concat([p, p.iloc[[-1]]])):
            with self.assertRaises(RuntimeError): m.features(bad)

    def test_input_prices_refuse_missing_nonpositive_and_duplicates(self):
        with TemporaryDirectory() as td:
            p=Path(td)/'x.csv'
            for vals, dates in [([1.,0.],['2020-01-02','2020-01-03']),
                                ([1.,float('nan')],['2020-01-02','2020-01-03']),
                                ([1.,2.],['2020-01-02','2020-01-02']),
                                ([1.,2.],['2020-01-03','2020-01-02'])]:
                pd.DataFrame({'date':dates,'close':vals}).to_csv(p,index=False)
                with self.assertRaises(RuntimeError): m.read_prices(p,'close')

    def test_manifest_and_member_hashes_are_enforced(self):
        with TemporaryDirectory() as td:
            root=Path(td); member=root/'x.csv'; member.write_text('frozen')
            files={member.name:m.digest(member)}
            (root/'MANIFEST.json').write_text(json.dumps({'files':files}))
            pointer=root/'pointer.json'
            expected={'package':'ghcr.io/example/data@sha256:'+'a'*64,
                      'files':files,'manifest_sha256':m.digest(root/'MANIFEST.json')}
            pointer.write_text(json.dumps(expected))
            self.assertEqual(m.verify_inputs(root,pointer),expected)
            member.write_text('mutated')
            with self.assertRaisesRegex(RuntimeError,'input hash'): m.verify_inputs(root,pointer)
            expected['package']='mutable:latest'; pointer.write_text(json.dumps(expected))
            with self.assertRaisesRegex(RuntimeError,'content addressed'): m.verify_inputs(root,pointer)

    def test_vix_is_lagged_on_equity_sessions_and_missing_refuses(self):
        p=prices(); v=pd.Series(np.arange(len(p))+10., index=p.index)
        def read(path,col): return v if path.name.startswith('vix') else p
        required=[str(x.date()) for x in p.index[250:300]]
        with patch.object(m,'verify_inputs',return_value={}), patch.object(m,'read_prices',side_effect=read):
            market=m.MarketData(Path('.'),required,p.index[250],p.index[299])
            obs=market.at(p.index[250]); self.assertEqual(obs['vix_lag1'],v.iloc[249])
            self.assertEqual(obs['vix_source_session'],p.index[249])
        short_vix=v.drop(p.index[249])
        def missing(path,col): return short_vix if path.name.startswith('vix') else p
        with patch.object(m,'verify_inputs',return_value={}), patch.object(m,'read_prices',side_effect=missing):
            with self.assertRaisesRegex(RuntimeError,'Missing observer feature'):
                m.MarketData(Path('.'),required,p.index[250],p.index[299])


class ControllerTests(unittest.TestCase):
    def test_iwm_has_independent_stress_vote(self):
        r=row(); r.update({k:v for k,v in row(False).items() if k.startswith('iwm')})
        self.assertTrue(m.observe(cfg(),r).stress)
        self.assertFalse(m.observe(cfg('spy'),r).stress)
        self.assertFalse(m.observe(cfg(),r).full_healthy)

    def test_vix_confirmation_and_recovery_boundaries(self):
        r=row(False); r['vix_lag1']=24.99
        self.assertFalse(m.observe(cfg('spy_iwm_vix'),r).stress)
        r['vix_lag1']=25.
        self.assertTrue(m.observe(cfg('spy_iwm_vix'),r).stress)
        r=row(); r['vix_lag1']=20.
        self.assertTrue(m.observe(cfg('spy_iwm_vix'),r).full_healthy)
        r['vix_lag1']=20.01
        self.assertFalse(m.observe(cfg('spy_iwm_vix'),r).full_healthy)

    def test_all_three_stress_conditions_are_required(self):
        for key,value in [('spy_trend120',0.),('spy_dd126',-.09999),('spy_ratio',1.19999)]:
            r=row(False); r[key]=value
            self.assertFalse(m.observe(cfg('spy'),r).stress)
        self.assertTrue(m.observe(cfg('spy'),row(False)).stress)

    def test_direct_classification_and_leadership_independence(self):
        for c in m.configs():
            a,b=m.Controller(c),m.Controller(c)
            for i in range(60):
                r=row(i%15>4); altered=dict(r,classification='partnership',recent_r20=-9e9,
                     recent_r40=9e9,eligible_count=1,leadership_population=99999)
                oa,ob=m.observe(c,r),m.observe(c,altered)
                self.assertEqual(oa,ob)
                inputs=(1.,1.,-.15,.01,.02)
                self.assertEqual(a.step(*inputs,oa),b.step(*inputs,ob))
                self.assertEqual(a,b)

    def test_native_and_drawdown_gates(self):
        stress=m.observe(cfg(),row(False))
        for args in [(1.,1.,-.09999),(.75,1.,-.2),(1.,.75,-.2)]:
            ctl=m.Controller(cfg()); ctl.step(*args,.0,.0,stress)
            self.assertFalse(ctl.latched)
        ctl=m.Controller(cfg()); desired,_=ctl.step(1.,1.,-.10,0.,0.,stress)
        self.assertEqual(desired,.55); self.assertTrue(ctl.latched)

    def test_recovery_is_exactly_eight_consecutive_sessions(self):
        ctl=m.Controller(cfg()); stress=m.observe(cfg(),row(False)); healthy=m.observe(cfg(),row())
        ctl.step(1.,1.,-.15,0.,0.,stress)
        for _ in range(7): self.assertEqual(ctl.step(1.,1.,-.15,.03,.02,healthy)[0],.55)
        self.assertEqual(ctl.step(1.,1.,-.15,.03,.02,healthy)[0],1.)
        self.assertFalse(ctl.latched)

    def test_healthy_streak_resets(self):
        ctl=m.Controller(cfg()); stress=m.observe(cfg(),row(False)); good=m.observe(cfg(),row())
        ctl.step(1.,1.,-.15,0.,0.,stress)
        for _ in range(7): ctl.step(1.,1.,-.15,.03,.02,good)
        ctl.step(1.,1.,-.15,0.,0.,stress)
        self.assertEqual(ctl.full_streak,0)
        self.assertEqual(ctl.step(1.,1.,-.15,.03,.02,good)[0],.55)

    def test_v_rebound_strict_boundary_and_no_same_day_reentry(self):
        ctl=m.Controller(cfg()); stress=m.observe(cfg(),row(False))
        ctl.step(1.,1.,-.15,0.,0.,stress)
        self.assertEqual(ctl.step(1.,1.,-.15,.11,0.,stress)[0],.55)
        desired,reason=ctl.step(1.,1.,-.15,.110001,0.,stress)
        self.assertEqual(desired,1.); self.assertIn('CLEAR',reason); self.assertFalse(ctl.latched)

    def test_native_recovery_episode_holds_previous_target(self):
        ctl=m.Controller(cfg()); stress=m.observe(cfg(),row(False))
        self.assertEqual(ctl.step(0.,1.,-.2,0.,0.,stress)[0],0.)
        self.assertTrue(ctl.episode)
        self.assertEqual(ctl.step(1.,0.,-.2,0.,0.,stress)[0],0.)
        self.assertEqual(ctl.step(1.,1.,-.2,.12,.01,m.observe(cfg(),row()))[0],1.)
        self.assertFalse(ctl.episode)

    def test_state_isolation_and_envelope(self):
        a,b=m.Controller(cfg()),m.Controller(cfg())
        stress=m.observe(cfg(),row(False))
        a.step(1.,1.,-.15,0.,0.,stress)
        self.assertTrue(a.latched); self.assertFalse(b.latched)
        for native in [0.,.25,.55,.75,1.]:
            target,_=a.step(native,native,-.2,0.,0.,stress)
            self.assertLessEqual(target,native); self.assertGreaterEqual(target,0.)
        with self.assertRaises(RuntimeError): a.step(1.1,1.,-.2,0.,0.,stress)


class ExperimentTests(unittest.TestCase):
    def make_experiment(self,td,mode='full20'):
        sessions=[str(d.date()) for d in pd.bdate_range('2005-01-03','2026-07-31')]
        market=SimpleNamespace(pointer={},at=lambda date:row(False))
        with patch.object(m,'MarketData',return_value=market):
            return m.Experiment(Path('.'),Path(td),m.STARTS[mode],m.END,sessions,mode)

    def test_prior_close_decision_drives_following_session(self):
        with TemporaryDirectory() as td:
            ex=self.make_experiment(td); dates=pd.bdate_range(m.STARTS['full20'],periods=3)
            bil=pd.DataFrame({'gap_factor':1.,'intraday_factor':1.},index=dates)
            calls=[]
            def overlay(nav,old,new,prev,op,cl,bil,date,prevdate):
                calls.append((date,old,new))
                return nav*(1+new*(cl/prev-1)),0.
            for i,date in enumerate(dates):
                ex.advance(date,1.,1.,-.15,.0,.0,1.,100.,100.+i,bil,overlay)
            center=next(c.name for c in ex.grid if c.central and c.family=='spy_iwm')
            rows=[r for r in ex.rows if r['candidate']==center]
            self.assertEqual([r['allocation'] for r in rows],[1.,.55,.55])
            self.assertEqual([r['close_target'] for r in rows],[.55,.55,.55])
            self.assertEqual(len(calls),2*83)
            with self.assertRaisesRegex(RuntimeError,'chronologically'):
                ex.advance(dates[-1],1.,1.,-.15,.0,.0,1.,100.,100.,bil,overlay)

    def test_fresh_launch_refuses_inherited_holdings_cash_and_cooldowns(self):
        with TemporaryDirectory() as td:
            ex=self.make_experiment(td,'fresh5')
            book=SimpleNamespace(slots=[],cash=100_000_000.,receivables=[],sec_ready={},terminal_pending={})
            ex.launch(book); self.assertTrue(ex.initial_state_verified)
            book.slots=[SimpleNamespace(held=lambda:True,reserved=lambda:False)]
            with self.assertRaisesRegex(RuntimeError,'holdings'): ex.launch(book)
            book.slots=[]; book.sec_ready={1:9}
            with self.assertRaisesRegex(RuntimeError,'financial state'): ex.launch(book)
            book.sec_ready={}; book.cash=99.
            with self.assertRaisesRegex(RuntimeError,'financial state'): ex.launch(book)

    def test_fresh_warmup_does_not_evolve_controller_or_economics(self):
        with TemporaryDirectory() as td:
            ex=self.make_experiment(td,'fresh5')
            ex.advance(ex.start-pd.Timedelta(days=1),0.,1.,-.8,0.,0.,0.,100.,100.,None,None)
            self.assertFalse(ex.rows)
            self.assertTrue(all(c.episodes==0 and not c.latched for c in ex.controllers.values()))
            self.assertTrue(all(v==1. for v in ex.nav.values()))

    def test_missing_observer_refuses_before_target_mutation(self):
        with TemporaryDirectory() as td:
            ex=self.make_experiment(td); ex.market.at=lambda date:{}
            with self.assertRaisesRegex(RuntimeError,'unavailable'):
                ex.advance(ex.start,1.,1.,-.2,0.,0.,1.,100.,100.,None,None)
            self.assertFalse(ex.rows)
            self.assertTrue(all(c.episodes==0 for c in ex.controllers.values()))

    def test_negative_drawdown_is_worse(self):
        dates=pd.date_range('2020-01-01',periods=3)
        score=m.score(np.array([1.,.8,1.1]),dates)
        self.assertAlmostEqual(score['max_drawdown'],-.2)
        self.assertAlmostEqual(score['ending_multiple'],1.1)

    def test_source_seam_refuses_absent_or_ambiguous_anchor(self):
        for text in ['nothing','same same']:
            with self.assertRaises(RuntimeError): m.once(text,'same','new','test')
        self.assertEqual(m.once('only same','same','new','test'),'only new')

    def test_reference_check_requires_completed_fresh_run(self):
        with TemporaryDirectory() as td:
            p=Path(td); baseline=p/'prior.csv'; baseline.write_text('prior')
            m.write_json(p/'observer-completion.json',{'completion':'FAILED','mode':'full20'})
            with patch.object(m,'BASELINE_DAILY_SHA',m.digest(baseline)):
                with self.assertRaisesRegex(RuntimeError,'completed full20'): m.reference_check(p,baseline)


class FullAssemblyTests(unittest.TestCase):
    def test_frozen_assembly_and_cash_accounting(self):
        """Runs with pinned runtime on CI; retained source is a local seam-test witness."""
        witness=os.environ.get('OBSERVER_ASSEMBLY_WITNESS')
        if witness:
            original=Path(witness).read_text()
        else:
            from backtester import research_champion_corrected_classification as corrected
            original=corrected.build_source(Path('/tmp/observer-assembly-test'))
        for mode in ('full20','fresh5'):
            assembled=m.install(original,mode)
            self.assertEqual(m.class_hashes(original),m.class_hashes(assembled))
            self.assertEqual(assembled.count('_observers.advance('),1)
            self.assertEqual(assembled.count('_observers.finish('),1)
            self.assertEqual('if date>=START and ready' in assembled,mode=='fresh5')
            self.assertEqual('_observers.launch(book)' in assembled,mode=='fresh5')
        tree=ast.parse(original)
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['bil_factors','apply_overlay']]
        ns={'COST':.001}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<frozen-accounting-test>','exec'),ns)
        dates=pd.to_datetime(['2020-01-02','2020-01-03'])
        bil=pd.DataFrame({'gap_factor':[1.,1.001],'intraday_factor':[1.,1.002]},index=dates)
        nav,cost=ns['apply_overlay'](1.,1.,.55,100.,90.,99.,bil,dates[1],dates[0])
        self.assertAlmostEqual(nav,.9*(1-.00045)*(1+.55*.1+.45*.002))
        self.assertAlmostEqual(cost,.00045)
        nav,cost=ns['apply_overlay'](1.,0.,0.,100.,90.,99.,bil,dates[1],dates[0])
        self.assertAlmostEqual(nav,1.001*1.002); self.assertEqual(cost,0.)
        with self.assertRaises(RuntimeError): m.install(original.replace('    out=pd.DataFrame(rows)\n',''), 'full20')


if __name__=='__main__':
    unittest.main()
