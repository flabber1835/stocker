import math

import pytest

from tools.median5_equivalence import Comparison


def test_split_roundoff_tolerance_cannot_hide_integer_or_material_quantity_changes(tmp_path):
    gate = Comparison.__new__(Comparison)
    gate.session, gate.output, gate.count = "2006-12-29", tmp_path, 250
    gate.fractional_share_roundoffs = 0
    gate.shares("split", 216058.7007, 216058.70070000002)
    assert gate.fractional_share_roundoffs == 1
    for actual, expected in ((216058.7007, 216059.7007),
                             (216058., math.nextafter(216058., math.inf)),
                             (216058., 216059.)):
        with pytest.raises(AssertionError):
            gate.shares("must_fail", actual, expected)
