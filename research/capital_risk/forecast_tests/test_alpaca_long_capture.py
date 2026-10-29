"""Pure boundary checks, never invoke providers or financial transitions."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_fit_collect import Client,CAPTURE_BOUNDS,canonical,digest
from alpaca_long_collect import validate


class LongCaptureTests(unittest.TestCase):
    def test_anonymous_mapping_never_reads_provider_keys(self):
        with patch('alpaca_fit_collect.provider_keys',side_effect=AssertionError('key loader invoked')):
            client=Client(Path('.'),keys={})
        self.assertEqual(client.keys,{})
        self.assertEqual(client.bounds,(3300,2400,2*1024**3,512*1024**2))

    def test_expanded_bounds_require_named_scope(self):
        with self.assertRaisesRegex(ValueError,'REFUSED_CAPTURE_SCOPE'):Client(Path('.'),keys={},scope='large')
        self.assertEqual(Client(Path('.'),keys={},scope='LONG_HISTORY').bounds,(5400,8000,8*1024**3,2*1024**3))

    def values(self):
        protocol={'schema':'research.bounded-alpaca-policy-fit/2','study_id':'alpaca-owned55-long-fit-001',
            'source_capture_scope':'LONG_HISTORY'}
        for key,value in zip(('capture_max_seconds','capture_max_requests','capture_max_raw_bytes','capture_max_gzip_bytes'),
            CAPTURE_BOUNDS['LONG_HISTORY']):protocol[key]=value
        selected=[{'asset_id':str(i),'ticker':'S'+str(i)} for i in range(200)]
        classification={'selected':selected};pr=canonical(protocol);cr=canonical(classification)
        roster={'protocol_sha256':digest(pr),'parent_classification_sha256':digest(cr),'roster':selected}
        return protocol,roster,classification,pr,cr

    def test_changed_classification_refuses(self):
        values=self.values();self.assertEqual(len(validate(*values)),200)
        values[1]['parent_classification_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'INPUT_BINDINGS'):validate(*values)

    def test_swapped_ticker_identity_refuses(self):
        values=self.values();values[2]['selected']=[dict(r) for r in values[2]['selected']]
        values[2]['selected'][0]['ticker']='IMPOSTOR'
        with self.assertRaisesRegex(ValueError,'CLASSIFICATION_MEMBERSHIP'):validate(*values)


if __name__=='__main__':unittest.main()
