"""Pure quote-admission falsifier; actual canonical packets remain hosted."""
import ast
from pathlib import Path

import pytest

import system_campaign_h2_2023_gate as gate


def test_unexpected_recognition_quote_cannot_be_ignored():
    gate.require_absent({}, {'same_day_quote_claims': []})
    with pytest.raises(ValueError, match='NO_UNDECLARED_RECOGNITION_DAY_QUOTES'):
        gate.require_absent({('2023-08-09', 'DICE'): {'raw_close': '48'}},
                            {'same_day_quote_claims': []})
    with pytest.raises(ValueError, match='NO_UNDECLARED_RECOGNITION_DAY_QUOTES'):
        gate.require_absent({}, {'same_day_quote_claims': [{'security_id': 'DICE'}]})


def test_actual_quote_absence_guard_removal_is_detected():
    tree = ast.parse(Path(gate.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_absent']
    fn.body = [ast.Pass()]
    ns = dict(vars(gate))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-h2-quote-guard-removed>', 'exec'), ns)
    unexpected = {('2023-08-09', 'DICE'): {'raw_close': '48'}}
    with pytest.raises(ValueError):
        gate.require_absent(unexpected, {'same_day_quote_claims': []})
    ns['require_absent'](unexpected, {'same_day_quote_claims': []})
