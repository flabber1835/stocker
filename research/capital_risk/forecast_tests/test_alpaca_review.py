from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_fit_review import raw_nav


class AccountingOracleTests(unittest.TestCase):
    def test_receivable_is_asset_not_spendable_cash(self):
        cash=1000.;claims={('SYN','2025-01-02'):100.}
        self.assertEqual(raw_nav(cash,{'SYN':2.},{'SYN':50.},claims),1200.)
        self.assertEqual(cash,1000.)
        self.assertEqual(raw_nav(1100.,{'SYN':2.},{'SYN':50.},{}),1200.)


if __name__=='__main__':unittest.main()
