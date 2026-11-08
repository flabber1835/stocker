from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_identity_intervals import diagnose


class TemporalIdentityTests(unittest.TestCase):
    def roster(self):return [{'ticker':'OLD','asset_id':'new-issuer','share_class_figi':'Fnew'},
        {'ticker':'NEW','asset_id':'successor','share_class_figi':'Fsuccessor'}]

    def rename(self):return ('name_changes',{'old_symbol':'OLD','new_symbol':'NEW','old_cusip':'111111111',
        'new_cusip':'222222222','process_date':'2025-07-16'})

    def test_reused_symbol_cannot_borrow_departed_issuer_history(self):
        r=diagnose(self.roster(),[self.rename()],asof='2026-10-27')['identities']
        self.assertEqual(r['new-issuer']['status'],'QUARANTINE')
        self.assertEqual(r['successor']['not_before'],'2025-07-16')

    def test_later_common_separation_gives_conservative_boundary(self):
        action=('unit_splits',{'old_symbol':'OLD.U','new_symbol':'OLD','old_cusip':'333333333','new_cusip':'444444444',
            'effective_date':'2026-03-27','old_rate':1,'new_rate':1})
        r=diagnose(self.roster(),[self.rename(),action],asof='2026-10-27')['identities']['new-issuer']
        self.assertEqual(r['status'],'TEMPORAL_ADMISSION_CANDIDATE');self.assertEqual(r['not_before'],'2026-03-27')

    def test_same_day_old_unit_record_does_not_establish_new_issuer(self):
        action=('unit_splits',{'old_symbol':'OLD.U','new_symbol':'OLD','old_cusip':'333333333','new_cusip':'444444444',
            'effective_date':'2025-07-16','old_rate':1,'new_rate':1})
        r=diagnose(self.roster(),[self.rename(),action],asof='2026-10-27')['identities']['new-issuer']
        self.assertEqual(r['status'],'QUARANTINE')

    def test_primary_boundary_cannot_precede_departed_company(self):
        primary={'asset_id':'new-issuer','not_before':'2024-01-01','primary_url':'https://www.sec.gov/Archives/example',
            'extraction_sha256':'a'*64,'meaning':'FIRST_SEPARATE_COMMON_TRADING'}
        with self.assertRaisesRegex(ValueError,'PRIMARY_MUST_FOLLOW_DEPARTED_ISSUE'):
            diagnose(self.roster(),[self.rename()],asof='2026-10-27',primary_boundaries=[primary])

    def test_duplicate_current_share_class_is_not_two_universe_votes(self):
        rows=self.roster();rows[1]['share_class_figi']=rows[0]['share_class_figi']
        r=diagnose(rows,[],asof='2026-10-27')
        self.assertEqual(len(r['duplicate_current_share_class_groups']),1)
        self.assertTrue(all(v['status']=='QUARANTINE' for v in r['identities'].values()))

    def test_malformed_unit_record_cannot_establish_successor_boundary(self):
        action=('unit_splits',{'old_symbol':'OLD.U','new_symbol':'OLD','old_cusip':'333333333','new_cusip':'444444444',
            'effective_date':'2026-03-27','old_rate':1,'new_rate':0})
        r=diagnose(self.roster(),[self.rename(),action],asof='2026-10-27')['identities']['new-issuer']
        self.assertEqual(r['status'],'QUARANTINE');self.assertIsNone(r['not_before'])

    def test_missing_name_identity_is_quarantined_not_inferred(self):
        kind,record=self.rename();record.pop('new_cusip')
        r=diagnose(self.roster(),[(kind,record)],asof='2026-10-27')['identities']
        self.assertEqual(r['successor']['status'],'QUARANTINE');self.assertIsNone(r['successor']['not_before'])


if __name__=='__main__':unittest.main()
