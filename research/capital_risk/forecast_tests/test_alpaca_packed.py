"""Storage equivalence only; synthetic arrays, no book transition."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_fit_inputs import Inputs


class PackedRowsTests(unittest.TestCase):
    def test_paired_missing_and_float_values_are_identical(self):
        data=Inputs.__new__(Inputs);data.sid_index={'SYN':0};days=['2025-01-02','2025-01-03','2025-01-06','2025-01-07']
        data.index={d:i for i,d in enumerate(days)};data.assets={'SYN':{'ticker':'SYN'}}
        data.present=np.array([[[True,True],[True,False],[False,False],[True,True]]])
        data.values=np.array([[[1.2,1.3,100.,.65],[2.,3.,400.,0.],[0.,0.,0.,0.],[7.2,8.1,300.,4.05]]])
        old=[data.row('SYN',d) for d in days if data.paired('SYN',d)]
        absent={('SYN',d) for d in days if data.present[0,data.index[d]].any() and not data.paired('SYN',d)}
        rows,missing=data.paired_rows('SYN',days)
        self.assertEqual(rows,old);self.assertEqual(missing,absent)
        self.assertEqual(rows[-1]['adjusted_close'].hex(),float(data.values[0,3,3]).hex())


if __name__=='__main__':unittest.main()
