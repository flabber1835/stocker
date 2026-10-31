from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_fit_compare import compare
from alpaca_fit_resume import price_plan,without_token


class PreimageTests(unittest.TestCase):
    def test_only_object_order_can_differ(self):
        self.assertTrue(compare(b'{"bars":{"SYN":[{"o":1.5,"c":2.0}]},"next_page_token":"x"}',
                                b'{"next_page_token":"x","bars":{"SYN":[{"c":2.0,"o":1.5}]}}'))
        original=b'{"p":[1.0,2.0],"token":"x"}'
        for changed in (b'{"p":[1.1,2.0],"token":"x"}',b'{"p":[2.0,1.0],"token":"x"}',
                        b'{"p":[1,2.0],"token":"x"}',b'{"p":[1.0,2.0],"token":"y"}'):
            self.assertFalse(compare(original,changed))

    def test_plan_has_every_fixed_group_domain(self):
        p={'data_start':'2023-04-03','data_end':'2026-10-27'}
        plan=price_plan(p,[f'SYN{i:03d}' for i in range(401)])
        self.assertEqual(len(plan),6)
        self.assertEqual([q['adjustment'] for q in plan],['raw','raw','split','split','raw','all'])
        self.assertEqual(without_token({**plan[0],'page_token':'x'}),plan[0])


if __name__=='__main__':unittest.main()
