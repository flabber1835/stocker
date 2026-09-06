"""Source, state-machine, frozen-path and summary-finalization regression tests."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from backtester import research_champion_index_comparison_v2 as comparison
from backtester import research_champion_market_risk_screen_v2 as screen


class IndexComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.source = comparison.corrected.install(comparison.closure.build_source(Path(cls.tmp.name)))
        cls.trees = {}
        for proxy in ('SPY', 'IWV'):
            for key, params in comparison.PARAMETERS.items():
                source = comparison.install(cls.source, proxy, params)
                cls.trees[proxy, key] = ast.parse(source)
                dest = Path(os.environ.get('INDEX_PREFLIGHT_OUTPUT', cls.tmp.name))
                dest.mkdir(parents=True, exist_ok=True)
                (dest/f'generated-{proxy}-{key}.py').write_text(source)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def candidate(self, key):
        tree = self.trees['SPY', key]
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CandidateA')
        ns = dict(finite=screen.finite, LDRC_REC=8, LDRC_V=0.11, LDRC_DD=-0.10, LDRC_CEIL=0.55,
                  MARKET_RISK_FAMILY='spy_vol', MARKET_RISK_PARAMS=comparison.PARAMETERS[key])
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<candidate>', 'exec'), ns)
        return ns['CandidateA']()

    def test_four_registered_cells_compile(self):
        self.assertEqual(len(self.trees), 4)
        with self.assertRaises(RuntimeError):
            comparison.install(self.source, 'QQQ', comparison.PARAMETERS['spy-center'])
        with self.assertRaises(RuntimeError):
            comparison.install(self.source, 'SPY', {'rv20_stress': .99})

    def test_frozen_classes_and_cash_functions_unchanged(self):
        old = ast.parse(self.source)
        names = ['Book', 'Native', 'ControlLDRC', 'CandidateB', 'bil_factors', 'apply_overlay']
        for name in names:
            ref = next(n for n in old.body if getattr(n, 'name', None) == name)
            for tree in self.trees.values():
                found = next(n for n in tree.body if getattr(n, 'name', None) == name)
                self.assertEqual(ast.dump(ref), ast.dump(found), name)

    def test_native_and_other_controller_call_inputs_unchanged(self):
        def calls(tree, obj):
            return [ast.dump(n) for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == obj]
        old = ast.parse(self.source)
        for obj in ['native', 'book', 'cb', 'ctl']:
            for tree in self.trees.values():
                self.assertEqual(calls(old, obj), calls(tree, obj), obj)

    def test_exact_matches_screen_for_5000_state_transitions(self):
        for key, params in comparison.PARAMETERS.items():
            exact = self.candidate(key)
            proxy = screen.ObservationOnlyCandidateA('spy_vol', params)
            rng = np.random.default_rng(1781)
            for i in range(2500):
                r = SimpleNamespace(native_close_target=float(rng.choice([0., .55, .65, 1., 1.])),
                    effective_native=float(rng.choice([0., .55, .65, 1., 1.])), wc_dd=-float(rng.uniform(0, .3)),
                    spy_r20=float(rng.uniform(-.2, .2)), spy_r40=float(rng.uniform(-.2, .2)), spy_dd=-float(rng.uniform(0, .4)),
                    spy_rv20=float(rng.uniform(.1, .4)), spy_vol_ratio=float(rng.uniform(.7, 1.4)),
                    vix=20., vix_chg5=-.03, vix_z252=0., vix_pct252=.5, wc_r20=float(rng.uniform(-.1, .12)))
                if i % 97 == 0:
                    r.spy_rv20 = float('nan')
                got = exact.step(r.native_close_target, r.effective_native, r.wc_dd, r.spy_r20,
                    r.spy_r40, r.spy_dd, r.spy_rv20, r.spy_vol_ratio, r.vix, r.vix_chg5,
                    r.vix_z252, r.vix_pct252, r.wc_r20)
                self.assertEqual(got, proxy.step(r))
                self.assertEqual(exact.recent_positive_streak, proxy.positive_streak)
                self.assertEqual(exact.concordance_releases, proxy.concordance_releases)
                self.assertEqual(exact.episode, proxy.episode)
                self.assertEqual(exact.latched, proxy.latched)

    def test_recovery_routes_and_concordance_counter(self):
        for route, vol, market_return, expected in [
            ('persistence', .10, .03, 'FULL_RISK_CERTIFIED_PERSISTENCE'),
            ('concordance', .21, .03, 'FULL_RISK_CERTIFIED_CROSS_SURFACE'),
            ('rebound', .30, .12, 'FULL_RISK_CERTIFIED_SPY_V_REBOUND'),
        ]:
            ca = self.candidate('iwv-center')
            for i in range(8):
                target, reason = ca.step(.55 if i < 7 else 1., .55, -.05, market_return, .04, -.03,
                                         vol, .90, 20., -.01, 0., .5, .02)
            self.assertEqual(target, 1., route)
            self.assertIn(expected, reason, route)
            self.assertEqual(ca.concordance_releases, 1 if route == 'concordance' else 0)

    def test_summary_attributes_exist_and_serialize(self):
        for key in comparison.PARAMETERS:
            ca = self.candidate(key)
            tree = self.trees['SPY', key]
            summaries = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == 'summary' for t in n.targets)]
            self.assertTrue(summaries)
            attrs = {n.attr for s in summaries for n in ast.walk(s.value)
                     if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'ca'}
            self.assertIn('concordance_releases', attrs)
            json.dumps({attr: getattr(ca, attr) for attr in attrs})
            json.dumps(ca.__dict__)

    def witnesses(self):
        keys = ['INDEX_BASELINE_DIR', 'INDEX_IWV_CSV', 'INDEX_VIX_CSV']
        if any(not os.environ.get(k) for k in keys):
            self.skipTest('retained witness integration test; set INDEX_BASELINE_DIR, INDEX_IWV_CSV, INDEX_VIX_CSV')
        return Path(os.environ[keys[0]]), Path(os.environ[keys[1]]), Path(os.environ[keys[2]])

    def test_pinned_inputs_and_complete_measurement_coverage(self):
        baseline, iwv, vix = self.witnesses()
        comparison.authenticate(baseline/'daily.csv.gz', comparison.BASELINE_SHA)
        comparison.authenticate(vix, comparison.VIX_SHA)
        features = comparison.load_iwv_features(iwv)
        dates = pd.to_datetime(pd.read_csv(baseline/'daily.csv.gz').date)
        self.assertFalse(features.reindex(dates).isna().any().any())

    def test_witness_tampering_rejected(self):
        _, iwv, _ = self.witnesses()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'changed.csv'
            target.write_bytes(iwv.read_bytes()+b'\n')
            with self.assertRaises(RuntimeError):
                comparison.load_iwv_features(target)

    def test_frozen_path_mutation_detected(self):
        baseline, _, _ = self.witnesses()
        daily = pd.read_csv(baseline/'daily.csv.gz')
        comparison.validate_frozen_path(daily, daily.copy())
        for col in ['native_close_target', 'research_ranking_sha256', 'research_wealth_core_equity', 'spy_nav']:
            changed = daily.copy()
            value = changed.loc[2, col]
            changed.loc[2, col] = 'mutation' if isinstance(value, str) else float(value)+1.
            with self.assertRaises(RuntimeError, msg=col):
                comparison.validate_frozen_path(changed, daily)

    def test_finalize_real_fixture_for_each_index(self):
        baseline, iwv, vix = self.witnesses()
        for market_proxy in ('SPY', 'IWV'):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                for name in ['daily.csv.gz', 'metrics.csv', 'summary.json', 'run-status.json', 'pit-closure-replay-identity.json']:
                    shutil.copy2(baseline/name, out/name)
                params = comparison.PARAMETERS['iwv-center']
                comparison.legacy._mark_outputs(out, 'spy_vol', params, vix)
                comparison.v2._mark_v2(out, 'spy_vol', params, vix)
                comparison.finalize(out, market_proxy, 'iwv-center', baseline/'daily.csv.gz', iwv)
                doc = json.loads((out/'index-comparison-v2-manifest.json').read_text())
                self.assertEqual(doc['frozen_path_validation']['status'], 'PASS')
                self.assertEqual(doc['market_proxy'], market_proxy)
                for line in (out/'SHA256SUMS.txt').read_text().splitlines():
                    digest, filename = line.split('  ', 1)
                    self.assertEqual(digest, comparison.sha256(out/filename))

    def test_next_session_execution_assignments_unchanged(self):
        def timing(tree):
            found = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    subs = [t.value.id for t in node.targets if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)]
                    if set(targets) & {'effective_native', 'pending_native', 'prev_perf_date', 'prev_close_eq'} or set(subs) & {'eff', 'pend'}:
                        found.append(ast.dump(node))
            return found
        original = timing(ast.parse(self.source))
        self.assertTrue(original)
        for tree in self.trees.values():
            self.assertEqual(original, timing(tree))

    def test_iwv_feature_prefix_is_causal(self):
        _, iwv, _ = self.witnesses()
        original = comparison.load_iwv_features(iwv)
        raw = pd.read_csv(iwv)
        cutoff = pd.Timestamp('2020-01-02')
        raw.loc[pd.to_datetime(raw.date) > cutoff, 'iwv_close'] *= 1.5
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp)/'future-perturbed.csv'
            raw.to_csv(changed, index=False)
            with patch.object(comparison, 'authenticate'):
                observed = comparison.load_iwv_features(changed)
            pd.testing.assert_frame_equal(original.loc[:cutoff], observed.loc[:cutoff], check_exact=False, rtol=1e-10, atol=1e-12)

    def test_wrapper_restores_on_early_error(self):
        original = comparison.v2.install
        with patch.object(comparison, 'authenticate'), patch.object(comparison.v2, 'run', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                comparison.run(Path('/unused'), 'SPY', 'spy-center', Path('/b'), Path('/i'), Path('/v'))
        self.assertIs(comparison.v2.install, original)

if __name__ == '__main__':
    unittest.main(verbosity=2)
