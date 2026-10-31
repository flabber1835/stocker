"""Raw quote-binding guard only; canonical gate is hosted, never mocked green."""
import ast
from pathlib import Path

import pytest

import system_campaign_spring2023_gate as gate


def test_quote_is_the_entire_frozen_source_row_not_only_its_price():
    row = {'session': '2023-04-27', 'security_id': 'PRVB', 'raw_close': '24.98',
           'issuer_id': 'frozen-issuer', 'tradeable': '1'}
    claim = dict(session=row['session'], security_id=row['security_id'],
                 source_observation_sha256=gate.digest(row))
    gate.require_quote(row, claim)
    for field, replacement in [('session', '2023-04-28'), ('security_id', 'OTHER'),
                                ('raw_close', '25'), ('issuer_id', 'UPGRADED'),
                                ('tradeable', '0')]:
        with pytest.raises(ValueError, match='ORIGINAL_SAME_DAY_QUOTE_BYTES'):
            gate.require_quote({**row, field: replacement}, claim)


def test_actual_quote_guard_removal_falsifier():
    row = dict(session='2023-04-27', security_id='PRVB', raw_close='24.98')
    claim = dict(session=row['session'], security_id=row['security_id'],
                 source_observation_sha256=gate.digest(row))
    changed = {**row, 'raw_close': '25'}
    tree = ast.parse(Path(gate.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_quote']
    fn.body = [ast.Pass()]
    namespace = dict(vars(gate))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-quote-binding-guard-removed>', 'exec'), namespace)
    with pytest.raises(ValueError):
        gate.require_quote(changed, claim)
    namespace['require_quote'](changed, claim)
