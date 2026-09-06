from __future__ import annotations

import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import backtester
_audit_package = str(Path(__file__).resolve().parents[1])
if _audit_package not in backtester.__path__:
    backtester.__path__.insert(0, _audit_package)
from backtester import champion_security_truth_audit_v2 as audit
from backtester import champion_security_truth_replay_v2 as replay
from backtester import champion_security_truth_overlay_v2 as overlay
from backtester import research_champion_corrected_classification as prior


class FactualBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = audit.unique(audit.read_csv(prior.base.DEFAULT_LEDGER), 'security_id')
        cls.document, cls.cases = audit.load_cases(audit.DEFAULT_FACTS, cls.base)

    def setUp(self):
        self.doc = copy.deepcopy(self.document)

    def test_pinned_batch_has_exact_seven_type_corrections(self):
        self.assertEqual({c['ticker'] for c in self.cases.values()}, {'GOLLQ', 'CIG', 'PBR.A', 'NTI', 'NGL', 'CVRR', 'UAN'})
        self.assertTrue(all(c['classification'] == 'non_common' for c in self.cases.values()))

    def test_tampered_file_hash_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'facts.json'
            path.write_bytes(audit.DEFAULT_FACTS.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                audit.load_cases(path, self.base)

    def test_duplicate_security_rejected(self):
        self.doc['corrections'].append(copy.deepcopy(self.doc['corrections'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            audit.validate_document(self.doc, self.base)

    def test_ticker_binding_rejected(self):
        self.doc['corrections'][0]['ticker'] = 'PBR'
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            audit.validate_document(self.doc, self.base)

    def test_cusip_mismatch_rejected(self):
        self.doc['corrections'][0]['cusips'] = ['71654V408']
        with self.assertRaisesRegex(ValueError, 'CUSIP'):
            audit.validate_document(self.doc, self.base)

    def test_unknown_security_rejected(self):
        self.doc['corrections'][0]['security_id'] = '9999999999999999999999'
        with self.assertRaisesRegex(ValueError, 'unknown canonical'):
            audit.validate_document(self.doc, self.base)

    def test_interval_extrapolation_rejected(self):
        self.doc['corrections'][0]['effective_first_session'] = '1900-01-01'
        with self.assertRaisesRegex(ValueError, 'admitted interval'):
            audit.validate_document(self.doc, self.base)

    def test_illegal_calendar_date_rejected(self):
        self.doc['corrections'][0]['effective_last_session'] = '2026-02-30'
        with self.assertRaises(ValueError):
            audit.validate_document(self.doc, self.base)

    def test_outcome_permission_rejected(self):
        self.doc['future_outcome_information_permitted'] = True
        with self.assertRaisesRegex(ValueError, 'future outcomes'):
            audit.validate_document(self.doc, self.base)

    def test_outcome_field_in_case_rejected(self):
        self.doc['corrections'][0]['cagr'] = 0.9
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            audit.validate_document(self.doc, self.base)

    def test_outcome_used_claim_rejected(self):
        self.doc['corrections'][0]['outcome_information_used'] = True
        with self.assertRaisesRegex(ValueError, 'outcome-based'):
            audit.validate_document(self.doc, self.base)

    def test_missing_source_rejected(self):
        self.doc['corrections'][0]['source_ids'] = ['invented']
        with self.assertRaisesRegex(ValueError, 'evidence reference'):
            audit.validate_document(self.doc, self.base)

    def test_nonprimary_url_rejected(self):
        self.doc['sources'][0]['url'] = 'https://example.com/claim'
        with self.assertRaisesRegex(ValueError, 'primary-source'):
            audit.validate_document(self.doc, self.base)

    def test_source_credentials_rejected(self):
        with self.assertRaises(ValueError):
            audit.validate_url('https://user:secret@www.sec.gov/Archives/edgar/data/1/a.htm')

    def test_legal_type_policy_drift_rejected(self):
        self.doc['corrections'][0]['classification'] = 'common'
        with self.assertRaisesRegex(ValueError, 'classification mismatch'):
            audit.validate_document(self.doc, self.base)

    def test_false_certified_label_rejected(self):
        self.doc['status'] = 'CERTIFIED'
        with self.assertRaisesRegex(ValueError, 'uncertified'):
            audit.validate_document(self.doc, self.base)

    def test_truth_replace_does_not_mutate_input_or_other_rows(self):
        truth = [dict(security_id=sid, ticker=c['ticker'], effective_first_session=c['effective_first_session'], effective_last_session=c['effective_last_session'], classification='common', other='retained') for sid, c in self.cases.items()]
        truth += [dict(security_id='594891209465982980', ticker='PDS', classification='non_common', effective_first_session='2006-07-05', effective_last_session='2010-06-01', other='retained'),
                  dict(security_id='594891209465982980', ticker='PDS', classification='common', effective_first_session='2010-06-02', effective_last_session='2015-06-04', other='retained')]
        before = copy.deepcopy(truth)
        out = audit.apply_to_truth(truth, self.cases, audit.unique(self.doc['sources'], 'source_id'))
        self.assertEqual(truth, before)
        self.assertEqual(out[-2:], truth[-2:])
        self.assertEqual(sum(a != b for a, b in zip(out, truth)), 7)

    def test_duplicate_truth_interval_rejected(self):
        truth = [dict(security_id=sid, ticker=c['ticker'], effective_first_session=c['effective_first_session'], effective_last_session=c['effective_last_session'], classification='common') for sid, c in self.cases.items()]
        truth.append(dict(truth[0]))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            audit.apply_to_truth(truth, self.cases, audit.unique(self.doc['sources'], 'source_id'))

    def test_full_coverage_includes_single_cusip_held_omission(self):
        work = {sid: dict(security_id=sid) for sid in self.base}
        cig = next(sid for sid, row in self.base.items() if row['ticker'] == 'CIG')
        work[cig]['held_sessions'] = '1'
        result = {r['security_id']: r for r in audit.coverage(self.base, {}, work, self.cases)}
        self.assertEqual(len(result), 1751)
        self.assertEqual(result[cig]['priority'], 'P0_HELD_OR_PENDING')
        self.assertEqual(result[cig]['original_queue_member'], 'false')
        self.assertIn('OMITTED', result[cig]['reason'])

    def test_path_priorities_do_not_change_classification(self):
        work = {sid: dict(security_id=sid) for sid in self.base}
        first = audit.coverage(self.base, {}, work, self.cases)
        for observed in work.values():
            observed.update(held_sessions='100', pending_sessions='100', durable_ranked_sessions='10000')
        second = audit.coverage(self.base, {}, work, self.cases)
        a = {r['security_id']: r['reviewed_classification'] for r in first}
        b = {r['security_id']: r['reviewed_classification'] for r in second}
        self.assertEqual(a, b)

    def test_incomplete_worklist_rejected(self):
        with self.assertRaisesRegex(ValueError, 'complete canonical'):
            audit.coverage(self.base, {}, {}, self.cases)

    def test_install_is_exactly_reversible(self):
        source = replay.OLD_IMPORT + '\ndef run():\n    for date in []:\n        if True:\n' + replay.OBSERVER_ANCHOR + '                pass\n'
        modified = replay.install(source)
        self.assertEqual(modified.replace(replay.NEW_IMPORT, replay.OLD_IMPORT, 1).replace(replay.OBSERVER, '', 1), source)

    def test_missing_or_duplicate_install_seam_rejected(self):
        for text in ('', replay.OLD_IMPORT + '\n' + replay.OLD_IMPORT):
            with self.assertRaisesRegex(ValueError, 'not unique'):
                replay.install(text)


class OverlayTests(unittest.TestCase):
    def setUp(self):
        overlay.ACTIVE_ESTIMATES.clear()
        overlay.PATH_COUNTS.clear()
        overlay.PATH_SESSIONS.clear()
        self.before = prior.SecurityTypeEstimate(prior.base.DEFAULT_LEDGER, 'reviewed_18')
        self.after = overlay.SecurityTypeEstimate(prior.base.DEFAULT_LEDGER, 'reviewed_18')

    def tearDown(self):
        overlay.ACTIVE_ESTIMATES.clear()
        overlay.PATH_COUNTS.clear()
        overlay.PATH_SESSIONS.clear()

    def test_all_1751_security_boundaries_change_only_the_seven_fixes(self):
        changed = set()
        for sid, row in self.after.rows.items():
            for session in (row['unknown_first_session'], row['unknown_last_session']):
                a, b = self.before.peek(sid, session), self.after.peek(sid, session)
                if a != b:
                    self.assertEqual((a, b), ('common', 'non_common'))
                    changed.add(sid)
        self.assertEqual(changed, set(self.after.factual_cases))

    def test_pds_historical_transition_and_eqm_preserved(self):
        pds = '594891209465982980'
        self.assertEqual(self.after.peek(pds, '2010-06-01'), 'non_common')
        self.assertEqual(self.after.peek(pds, '2010-06-02'), 'common')
        self.assertEqual(self.after.peek('192545371416014112', '2015-01-02'), 'non_common')

    def test_type_corrections_reject_extrapolation(self):
        for sid, case in self.after.factual_cases.items():
            before = (date.fromisoformat(case['effective_first_session']) - timedelta(days=1)).isoformat()
            after = (date.fromisoformat(case['effective_last_session']) + timedelta(days=1)).isoformat()
            for session in (before, after):
                with self.assertRaisesRegex(RuntimeError, 'outside admitted'):
                    self.after.peek(sid, session)

    def test_peek_has_no_counter_effect(self):
        sid, c = next(iter(self.after.factual_cases.items()))
        before = copy.deepcopy(self.after.summary())
        self.after.peek(sid, c['effective_first_session'])
        self.assertEqual(self.after.summary(), before)
        self.after.classify(sid, c['effective_first_session'])
        self.assertEqual(self.after.factual_calls[sid], 1)

    def test_common_petrobras_sibling_is_unchanged(self):
        sid = next(sid for sid, row in self.after.rows.items() if row['ticker'] == 'PBR')
        row = self.after.rows[sid]
        self.assertEqual(self.after.peek(sid, row['unknown_first_session']), self.before.peek(sid, row['unknown_first_session']))

    def test_observer_copies_and_counts_each_sid_once_per_stage(self):
        sid = next(iter(self.after.factual_cases))
        values = (sid, sid)
        expected = tuple(values)
        overlay.observe('2006-07-05', values, values, (), (), values)
        self.assertEqual(values, expected)
        self.assertEqual(overlay.PATH_COUNTS[sid]['held_sessions'], 1)
        self.assertEqual(overlay.PATH_COUNTS[sid]['durable_ranked_sessions'], 1)
        self.assertEqual(self.after.calls, self.before.calls)

    def test_observer_rejects_duplicate_session(self):
        overlay.observe('2006-07-05', (), (), (), (), ())
        with self.assertRaisesRegex(RuntimeError, 'strictly increasing'):
            overlay.observe('2006-07-05', (), (), (), (), ())

    def test_observer_rejects_mutable_inputs(self):
        with self.assertRaises(TypeError):
            overlay.observe('2006-07-05', [], (), (), (), ())


if __name__ == '__main__':
    unittest.main()
