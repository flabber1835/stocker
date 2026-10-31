import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import alpaca_fit_relay as relay


class RelayTests(unittest.TestCase):
    def test_exact_stream_and_truncation(self):
        self.assertEqual(relay.read_exact(io.BytesIO(b'abc'),3),b'abc')
        with self.assertRaisesRegex(ValueError,'TRUNCATED_PROVIDER_STREAM'):
            relay.read_exact(io.BytesIO(b'ab'),3)

    def test_spool_removal_requires_exact_remote_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);observed={}
            def fake_upload(command,**kwargs):
                local=Path(command[4]);raw=local.read_bytes()
                observed[local.name]={'state':'uploaded','size':len(raw),'digest':'sha256:'+relay.sha(raw)}
                return SimpleNamespace(returncode=0)
            with patch.object(relay,'remote',lambda:dict(observed)),patch.object(relay.subprocess,'run',fake_upload):
                parts=relay.Parts(root,'synthetic-only');parts.write(b'synthetic ciphertext');parts.flush_part()
            self.assertEqual(len(parts.parts),1)
            self.assertFalse((root/parts.parts[0]['name']).exists())
            self.assertTrue((root/'uploaded-parts.json').is_file())

    def test_bad_remote_does_not_remove_spool(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(relay,'remote',lambda:{}),patch.object(relay.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1)):
                parts=relay.Parts(root,'synthetic-only');parts.write(b'synthetic ciphertext')
                with self.assertRaisesRegex(ValueError,'EXACT_REMOTE_CIPHERTEXT'):parts.flush_part()
            self.assertTrue((root/'synthetic-only.part-0000.crseal').is_file())

    def test_remote_collision_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(relay,'remote',lambda:{'synthetic.part-0000.crseal':{}}):
                parts=relay.Parts(root,'synthetic');parts.write(b'synthetic')
                with self.assertRaisesRegex(ValueError,'REMOTE_COLLISION'):parts.flush_part()


if __name__=='__main__':unittest.main()
