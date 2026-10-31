"""Static manifest closure falsifiers; never runs a strategy or market replay."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from core_manifest import extend,resolver


class ManifestGuards(unittest.TestCase):
    def fixture(self):
        reader=(ROOT/'fixtures/economic_manifest_reader.py.txt').read_bytes()
        self.assertEqual(hashlib.sha256(reader).hexdigest(),
            json.loads((ROOT/'core-source-basis.json').read_bytes())['sentinel/economic_manifest.py'])
        normalized=re.sub(rb"^MANIFEST_SHA256 = '[0-9a-f]{64}'$",b"MANIFEST_SHA256 = '"+b'0'*64+b"'",reader,flags=re.M)
        files={'sentinel/__init__.py':b'', 'sentinel/example.py':b'from stock_strategy_shared import added\n',
            'shared/stock_strategy_shared/__init__.py':b'',
            'shared/stock_strategy_shared/added.py':b'from . import nested\n',
            'shared/stock_strategy_shared/nested.py':b'VALUE=1\n'}
        expected={'sentinel':'0'*64,'sentinel.example':'1'*64,'stock_strategy_shared':'2'*64}
        value=dict(pure_contracts=expected,input_compilers={},dependencies={},operational_ports={},
            implementation_sha256='',module_sha256=hashlib.sha256(normalized).hexdigest(),
            predecessor_revision='preserve-this-provenance')
        raw=(json.dumps(value)+'\n').encode()
        reader=re.sub(rb"^MANIFEST_SHA256 = '[0-9a-f]{64}'$",
            b"MANIFEST_SHA256 = '"+hashlib.sha256(raw).hexdigest().encode()+b"'",reader,flags=re.M)
        return {**files,'sentinel/economic_manifest.py':reader,'sentinel/economic-implementation-v2.json':raw}

    def test_new_transitive_modules_and_actual_edges_are_bound(self):
        files=self.fixture();before=dict(files);out=extend(files)
        self.assertEqual(files,before)
        value=json.loads(out['sentinel/economic-implementation-v2.json'])
        self.assertEqual(value['predecessor_revision'],'preserve-this-provenance')
        self.assertEqual(value['pure_contracts']['sentinel.example'],'1'*64)
        self.assertEqual(set(value['input_compilers']),{'stock_strategy_shared.added','stock_strategy_shared.nested'})
        self.assertIn('stock_strategy_shared.nested',value['dependencies']['stock_strategy_shared.added'])
        imports=resolver(out)
        for name in ('sentinel.example','stock_strategy_shared.added'):
            key='sentinel/example.py' if name.startswith('sentinel') else 'shared/stock_strategy_shared/added.py'
            self.assertEqual(value['dependencies'][name],imports(out[key],module_name=name))

    def test_unknown_sentinel_edge_and_original_manifest_tampering_refuse(self):
        files=self.fixture();files['sentinel/example.py']=b'import sentinel.unknown\n'
        with self.assertRaisesRegex(ValueError,'UNCLASSIFIED'):extend(files)
        files=self.fixture();files['sentinel/economic-implementation-v2.json']+=b' '
        with self.assertRaisesRegex(ValueError,'ORIGINAL_ECONOMIC_MANIFEST'):extend(files)


if __name__=='__main__':unittest.main()
