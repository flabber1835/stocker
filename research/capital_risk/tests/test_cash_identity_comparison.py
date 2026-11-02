"""Stopped evidence only: exact empty cash identity, never a blanket hash mask."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from core_window_review import compare_disabled,identity_digest


class EmptyCashIdentityGuards(unittest.TestCase):
    def book(self,root,identity):
        root.mkdir();state=dict(data_version=2,identity=identity)
        base=dict(identity=identity);input_sha=identity_digest(dict(base=base,repairs=[]))
        formation=dict(session='2024-12-31',state_sha256=identity*64,
            input_sha256=input_sha,chain_sha256='3'*64,evidence={},economics=dict(nav='50000'))
        row=dict(session='2025-01-02',state_sha256=identity_digest(state),
            input_sha256=input_sha,chain_sha256='4'*64,evidence={},economics=dict(nav='50001'))
        inputs=dict(schema='sentinel.forward-cash-distributions/1',prior_state_sha256=formation['state_sha256'],
            publication_version=2,session=row['session'],observations=[],pending=[],source_observations=[],legacy_floors=[])
        row['evidence']['cash_distributions']=dict(policy='FORWARD_CASH_DISTRIBUTIONS_V2',
            input_sha256=identity_digest(inputs),observations=[],pending=[],source_observations=[],legacy_floors=[])
        run=dict(state=state,state_sha256=identity_digest(state),input_sha256=input_sha)
        run['checkpoint_sha256']=identity_digest(run)
        cp=dict(base=base,repairs=[],run=run,completed=1,source_cursor=row['session'])
        cp['sha256']=identity_digest(cp)
        (root/'checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
        self.write(root,'formation',formation);self.write(root,'daily',row)
        return row

    def write(self,root,name,row):
        (root/(name+'.jsonl')).write_text(json.dumps(row)+'\n')

    def pair(self,tmp):
        a,b=Path(tmp)/'a',Path(tmp)/'b';self.book(a,'1');row=self.book(b,'2')
        return a,b,row

    def test_explicit_mode_validates_own_preimages_and_strict_default_still_refuses(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            a,b,_=self.pair(tmp)
            with self.assertRaisesRegex(ValueError,'FINANCIAL_PATH'):compare_disabled(a,b)
            proof=compare_disabled(a,b,empty_cash_identity=True)
            self.assertEqual(proof['records'],2)
            self.assertEqual(proof['verified_empty_cash_records_per_arm'],1)

    def test_cash_digest_economics_and_unknown_fields_cannot_be_masked(self):
        for field in ('input_sha256','observations','pending','source_observations','legacy_floors','policy','extra'):
            with self.subTest(field=field),tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                a,b,row=self.pair(tmp);cash=row['evidence']['cash_distributions']
                cash[field]='forged' if field in ('input_sha256','policy','extra') else [dict(amount='1')]
                self.write(b,'daily',row)
                with self.assertRaisesRegex(ValueError,'CASH_INPUT_PREIMAGE'):
                    compare_disabled(a,b,empty_cash_identity=True)

    def test_actual_economics_and_unrelated_nested_identity_still_refuse(self):
        for field in ('nav','nested_hash'):
            with self.subTest(field=field),tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                a,b,row=self.pair(tmp)
                if field=='nav':row['economics']['nav']='49999'
                else:row['evidence']['unrelated']=dict(input_sha256='5'*64)
                self.write(b,'daily',row)
                with self.assertRaisesRegex(ValueError,'FINANCIAL_PATH'):
                    compare_disabled(a,b,empty_cash_identity=True)

    def test_previous_row_identity_must_actually_produce_digest(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            a,b,row=self.pair(tmp)
            prior=json.loads((b/'formation.jsonl').read_text());prior['state_sha256']='8'*64
            self.write(b,'formation',prior)
            with self.assertRaisesRegex(ValueError,'CASH_INPUT_PREIMAGE'):
                compare_disabled(a,b,empty_cash_identity=True)

    def test_checkpoint_hashes_and_final_row_binding_refuse(self):
        for field in ('checkpoint','final_state','final_input'):
            with self.subTest(field=field),tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                a,b,row=self.pair(tmp)
                if field=='checkpoint':
                    cp=json.loads(gzip.decompress((b/'checkpoint.json.gz').read_bytes()))
                    cp['run']['state']['data_version']=3
                    (b/'checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
                    code='CASH_OUTER'
                else:
                    row['state_sha256' if field=='final_state' else 'input_sha256']='6'*64
                    self.write(b,'daily',row);code='CASH_FINAL_BINDING'
                with self.assertRaisesRegex(ValueError,code):compare_disabled(a,b,empty_cash_identity=True)


if __name__=='__main__':unittest.main()
