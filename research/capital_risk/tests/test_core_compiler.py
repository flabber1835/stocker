"""Static/pure guards. Canonical financial operations execute only hosted."""
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
import build_core_variants as b
import core_policy as p
from core_gate_job import gate_command,validate_request
from seal import sha256_file
from stage import PROTOCOL
from baseline_prefix import worker_arm,worker_stage


class CoreCompilerGuards(unittest.TestCase):
    def test_patch_count_and_original_source_digest_are_mandatory(self):
        self.assertEqual(b.replace('one','one','two'),'two')
        for value in ('missing','one one'):
            with self.assertRaises(ValueError):b.replace(value,'one','two')
        basis=json.loads((ROOT/'core-source-basis.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'FROZEN_PATCH_SOURCE'):
            b.render({name:b'wrong' for name in basis},risk=True)

    def test_exact_storage_rejects_rounding_fractional_entitlements(self):
        self.assertEqual(p.exact_float(Fraction(9,8)),1.125)
        with self.assertRaisesRegex(ValueError,'REPRESENTATION'):p.exact_float(Fraction(2,3))

    def test_gate_context_mount_identity_and_no_economic_backtest_cli(self):
        name='capital-risk-core-gate-123-1-risk'
        self.assertEqual(worker_arm(name),'CORE_GATE');self.assertEqual(worker_stage(name),'core-integration')
        with patch('os.getuid',return_value=1001,create=True),patch('os.getgid',return_value=1001,create=True):
            args=gate_command(name,Path('/frozen-host'),Path('/private-host'),ROOT,Path('/source-host'),'risk')
        self.assertIn(f'type=bind,source={Path("/source-host")},target=/variant,readonly',args)
        self.assertIn('PYTHONPATH=/variant:/variant/shared:/driver',args)
        self.assertIn('/driver/canonical_core_gate.py',args)
        self.assertNotIn('--max-transitions',args);self.assertNotIn('--policy',args)
        self.assertEqual(args[args.index('--network')+1],'none')
        for bad in ('capital-risk-core-gate-123-1','paper-core-gate','capital-risk-core-gate-123-1-c'):
            with self.assertRaises(ValueError):worker_stage(bad)

    def test_gate_request_and_selected_periods_are_exact(self):
        protocol=ROOT/'core-screen-protocol.json'
        r=dict(schema='research.capital-risk-core-gate-request/1',request_id='canonical-core-gate-001',
            stage='core-integration',original_protocol_sha256=PROTOCOL,core_protocol_sha256=sha256_file(protocol))
        validate_request(r,protocol)
        for change in (dict(extra=True),dict(stage='replay'),dict(core_protocol_sha256='0'*64)):
            with self.assertRaises(ValueError):validate_request({**r,**change},protocol)
        plan=json.loads(protocol.read_bytes());self.assertFalse(plan['combinations'])
        self.assertEqual(plan['windows'],[['2021-01-04','2022-12-30'],['2025-01-02','2026-07-31']])


if __name__=='__main__':unittest.main()
