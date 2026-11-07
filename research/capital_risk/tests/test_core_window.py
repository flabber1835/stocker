"""Independent accounting/comparator falsifiers; no local market replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from core_window_review import reconcile,compare_disabled
from core_window_job import window_command,WINDOWS,validate_request
from baseline_prefix import worker_arm,worker_stage
from seal import sha256_file


class WindowGuards(unittest.TestCase):
    def snap(self):
        event=dict(session='2021-01-04',event_type='BUY',security_id='S',shares_delta=10,
            price=100,fees=1,cash_before=50000,cash_delta=-1001,cash_after=48999,detail={})
        return dict(wealth_core=dict(cash=48999,episodes={'0':dict(security_id='S',current_shares=10)}),
            ledger=dict(events=[event],receivables=[]),prices={'S':dict(raw_price=110,status='CURRENT')},resolved_equity=50099)

    def test_ledger_fee_cash_quantity_and_raw_valuation_are_independent(self):
        reconcile(self.snap())
        for change in ('cash','quantity','fee','mark','equity'):
            s=self.snap()
            if change=='cash':s['wealth_core']['cash']-=1
            if change=='quantity':s['wealth_core']['episodes']['0']['current_shares']+=1
            if change=='fee':s['ledger']['events'][0]['fees']=0
            if change=='mark':s['prices']['S']['raw_price']=100
            if change=='equity':s['resolved_equity']+=1
            with self.subTest(change=change),self.assertRaises(ValueError):reconcile(s)

    def test_unpaid_entitlement_is_an_asset_not_spendable_cash(self):
        s=self.snap();s['ledger']['events'].append(dict(session='2021-01-04',event_type='DIVIDEND_ACCRUED',
            security_id='S',shares_delta=0,price=.5,fees=0,cash_before=48999,cash_delta=0,cash_after=48999,
            detail=dict(shares=10,amount=5)))
        s['ledger']['receivables']=[dict(security_id='S',accrued_session='2021-01-04',amount=5)]
        s['resolved_equity']+=5;reconcile(s)
        s['ledger']['receivables']=[]
        with self.assertRaisesRegex(ValueError,'RECEIVABLE'):reconcile(s)

    def test_control_comparison_excludes_only_declared_top_level_identities(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(ROOT.resolve()))
            a,b=Path(tmp)/'a',Path(tmp)/'b';a.mkdir();b.mkdir()
            row=dict(session='2021-01-04',state_sha256='1'*64,input_sha256='2'*64,chain_sha256='3'*64,
                economics=dict(strategy_nav='50000'),evidence=dict(meaningful='keep'))
            for name in ('formation','daily'):
                (a/(name+'.jsonl')).write_text(json.dumps(row)+'\n')
                other={**row,'state_sha256':'4'*64};(b/(name+'.jsonl')).write_text(json.dumps(other)+'\n')
            self.assertEqual(compare_disabled(a,b)['records'],2)
            other=deepcopy(row);other['economics']['strategy_nav']='49999'
            (b/'daily.jsonl').write_text(json.dumps(other)+'\n')
            with self.assertRaisesRegex(ValueError,'FINANCIAL_PATH'):compare_disabled(a,b)

    def test_window_workers_are_disjoint_bounded_and_explicitly_dated(self):
        name='capital-risk-core-window-stress2021-v-123-1'
        self.assertEqual(worker_arm(name),'V');self.assertEqual(worker_stage(name),'short-core-window')
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=window_command(name,Path('/frozen'),Path('/out-v'),ROOT,Path('/risk'),
                'stress2021',['-m','research.pooled_vacancy_funding.backtest'])
        self.assertIn('CAPITAL_RISK_WINDOW=stress-2021',args)
        self.assertIn(f'type=bind,source={Path("/risk")},target=/variant,readonly',args)
        self.assertEqual(args[args.index('--network')+1],'none')
        for bad in ('capital-risk-core-window-stress2021-x-123-1',name+'-retry'):
            with self.assertRaises(ValueError):worker_stage(bad)


if __name__=='__main__':unittest.main()
