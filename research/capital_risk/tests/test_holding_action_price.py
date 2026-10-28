"""Pure source/price contracts. Actual funded operations run hosted only."""
from pathlib import Path
from unittest.mock import patch
import ast,json,sys,tempfile,unittest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import holding_action_job as job
import holding_prices as prices


class ActionPriceGuards(unittest.TestCase):
    def test_raw_prices_reject_bad_domains_and_nonfinite_values(self):
        for v in ('0','-1','NaN','Infinity','',None,'1/3'):self.assertFalse(prices.positive(v))
        self.assertTrue(prices.positive('12.34'))

    def test_request_pins_sources_and_no_historical_accounts(self):
        r=job.expected_request();job.validate_request(r)
        for k in ('sources','qualification_protocol_sha256','owner_scope'):
            with self.assertRaises(ValueError):job.validate_request({**r,k:{ } if k=='sources' else 'forged'})
        self.assertIn('holding_actions.py',r['sources']);self.assertIn('holding_prices.py',r['sources'])

    def test_worker_is_exact_offline_account_qualification(self):
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=job.command('capital-risk-holding-qual-123-1',Path('/frozen'),Path('/out'))
        self.assertEqual(args[args.index('--network')+1],'none');self.assertIn('/driver/holding_action_qualification.py',args)
        self.assertIn('HOLDING_QUAL_HOSTED=1',args);self.assertNotIn('--policy',args)

    def test_rational_schema_is_versioned_and_binary_floats_forbidden(self):
        text=(ROOT/'holding_account.py').read_text()
        self.assertIn('research.persistent-funded-account-prototype/2',text)
        self.assertIn('PlainSerializer',text);self.assertIn("type(value) in (str,D,int,Fraction)",text)
        self.assertNotIn('Fraction(float',text)

    def test_all_new_mutations_require_hosted_guard_first(self):
        tree=ast.parse((ROOT/'holding_actions.py').read_text());names={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        for n in ('convert','receive_spinoff','liquidate_children'):
            self.assertEqual(names[n].body[0].value.func.id,'hosted')
        source=(ROOT/'holding_actions.py').read_text()
        for forbidden in ('import requests','import socket','import subprocess','import sentinel','import stock_strategy_shared'):
            self.assertNotIn(forbidden,source)

    def test_exact_pro_rata_and_once_only_event_commit_are_retained(self):
        source=(ROOT/'holding_actions.py').read_text()
        self.assertIn('Q(whole)*p.shares/total',source);self.assertNotIn('float(',source)
        self.assertIn('REFUSED_ACTION_PREDECESSOR',source);self.assertIn('REFUSED_ACTION_MISSING_CIL',source)
        self.assertIn('terms_sha256=digest',source)

    def test_price_gate_uses_phase_and_permanent_identity_not_ticker_join(self):
        row=dict(session='2025-01-02',economics={})
        with patch.object(prices,'make_books',return_value={'2025-01-02':dict(shares={'SID':1})}):
            r=prices.requirements([row],[])
        self.assertEqual(r['2025-01-02']['uses'],{'SID':['CLOSE_MARK','OPEN_CURRENT']})
        source=(ROOT/'holding_prices.py').read_text()
        self.assertIn('REFUSED_DUPLICATE_REQUIRED_RAW_BAR',source)
        self.assertNotIn("prices[sid]['raw_close']=",source)
        self.assertNotIn('forward_fill',source)

    def test_actual_hosted_falsifier_and_canonical_operations_are_required(self):
        source=(ROOT/'holding_action_qualification.py').read_text()
        for text in ('mutant.convert','spinoffs.apply_supported_entitlements','terminal._split_entitlement',
                     'terminal._cash_in_lieu','shares.split_shares','canonical_source_bindings=bindings'):
            self.assertIn(text,source)
        self.assertIn('REFUSED_LOCAL_ACTION_QUALIFICATION',source)

    def test_bounded_workflow_exports_only_encrypted_financial_evidence(self):
        source=(ROOT.parents[1]/'.github/workflows/capital-holding-action-price.yml').read_text()
        for v in ('timeout-minutes: 20','timeout-minutes: 9','github.run_attempt == 1','retention-days: 7',
                  'holding-action-price.tar.crseal','holding-action-request.json'):
            self.assertIn(v,source)
        for v in ('workflow_dispatch:','actions: write','case-prefix.json','price-bindings.jsonl'):self.assertNotIn(v,source)
        driver=(ROOT/'holding_action_job.py').read_text();self.assertIn('deadline=420',driver)
        self.assertIn('private if known else diagnostic',driver)


if __name__=='__main__':unittest.main()
