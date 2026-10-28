import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpaca_fit_stage import extract_streamed
from seal import EncryptWriter,decrypt,sha256_file


class StreamAdmissionTests(unittest.TestCase):
    def archive(self,folder,*,tamper=False,extra=False,failed=False):
        data=b'synthetic nonfinancial input';manifest={'schema':'research.alpaca-fit-stream-inputs/1',
            'status':'COMPLETE','market_capture_status':'COMPLETE','protocol_sha256':'0'*64,
            'manifest_position':'LAST','members':{'capture/synthetic':{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}}
        if failed:manifest.update(status='FAILED',market_capture_status='INCOMPLETE')
        payload=json.dumps(manifest).encode();path=folder/'archive.tar'
        with tarfile.open(path,'w') as tar:
            for name,body in [('capture/synthetic',b'wrong' if tamper else data),('manifest.json',payload)]+([('extra',b'extra')] if extra else []):
                item=tarfile.TarInfo(name);item.size=len(body);tar.addfile(item,io.BytesIO(body))
        return path,hashlib.sha256(payload).hexdigest()

    def test_final_inventory_before_publication(self):
        with tempfile.TemporaryDirectory() as f:
            root=Path(f);path,h=self.archive(root)
            extract_streamed(path,root/'out',h,'0'*64)
            self.assertTrue((root/'out/capture/synthetic').is_file())

    def test_tampered_or_post_manifest_payload_never_extracted(self):
        for kwargs in ({'tamper':True},{'extra':True}):
            with self.subTest(kwargs=kwargs),tempfile.TemporaryDirectory() as f:
                root=Path(f);path,h=self.archive(root,**kwargs)
                with self.assertRaises(ValueError):extract_streamed(path,root/'out',h,'0'*64)
                self.assertFalse((root/'out').exists())

    def test_valid_hash_does_not_substitute_for_gcm_authentication(self):
        with tempfile.TemporaryDirectory() as f:
            root=Path(f);cipher=root/'cipher';key=os.urandom(32)
            with cipher.open('wb') as out:
                writer=EncryptWriter(out,key);writer.write(b'synthetic transport test');writer.finish()
            value=bytearray(cipher.read_bytes());value[-1]^=1;cipher.write_bytes(value)
            with self.assertRaises(Exception):decrypt(cipher,root/'plain',key,sha256_file(cipher))
            self.assertFalse((root/'plain').exists());self.assertFalse((root/'plain.partial').exists())

    def test_failed_prefix_never_passes_ordinary_complete_extractor(self):
        with tempfile.TemporaryDirectory() as f:
            root=Path(f);path,h=self.archive(root,failed=True)
            with self.assertRaisesRegex(ValueError,'COMPLETE_STREAM_INVENTORY'):
                extract_streamed(path,root/'ordinary',h,'0'*64)
            value=extract_streamed(path,root/'prefix',h,'0'*64,failed_prefix_scope='TLS_FAILED_PREFIX')
            self.assertEqual(value['status'],'FAILED')


if __name__=='__main__':unittest.main()
