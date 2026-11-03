import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
spec=importlib.util.spec_from_file_location('risk_runtime',Path(__file__).parents[1]/'runtime_identity.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class RuntimeIdentityTests(unittest.TestCase):
    def fixture(self,root):
        blobs={}
        def add(value):
            raw=value if isinstance(value,bytes) else json.dumps(value,sort_keys=True).encode()
            digest='sha256:'+hashlib.sha256(raw).hexdigest()
            blobs['blobs/sha256/'+digest[7:]]=raw
            return dict(digest=digest,size=len(raw))
        layer=add(b'synthetic layer')
        diff_ids=[layer['digest']]
        config=add(dict(os='linux',architecture='amd64',rootfs=dict(diff_ids=diff_ids)))
        manifest=add(dict(config=config,layers=[layer]))
        index=add(dict(manifests=[dict(**manifest,platform=dict(os='linux',architecture='amd64'))]))
        blobs['index.json']=json.dumps(dict(manifests=[index])).encode()
        blobs['manifest.json']=json.dumps([dict(Config='blobs/sha256/'+config['digest'][7:],
            Layers=['blobs/sha256/'+layer['digest'][7:]])]).encode()
        path=root/'runtime.tar'
        with tarfile.open(path,'w') as tar:
            for name,raw in blobs.items():
                info=tarfile.TarInfo(name);info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
        expected=dict(original_index=index['digest'],platform_manifest=manifest['digest'],config=config['digest'],
            diff_ids=diff_ids,layer_blobs=[layer['digest']],archive_bytes=path.stat().st_size,archive_sha256=r.sha256_file(path))
        return path,expected,layer

    def test_complete_index_config_layer_chain_and_loaded_rootfs(self):
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            path,expected,_=self.fixture(Path(folder))
            self.assertEqual(r.verify_archive(path,expected),expected)
            image=dict(Id=expected['config'],Os='linux',Architecture='amd64',RootFS=dict(Type='layers',Layers=expected['diff_ids']))
            r.verify_loaded(image,expected)
            for change in [dict(Id='sha256:'+'0'*64),dict(Architecture='arm64'),
                           dict(RootFS=dict(Type='layers',Layers=['changed']))]:
                with self.assertRaises(ValueError): r.verify_loaded({**image,**change},expected)

    def test_wrong_link_or_even_one_layer_byte_refuses(self):
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            path,expected,layer=self.fixture(Path(folder))
            for change in [dict(config='sha256:'+'0'*64),dict(diff_ids=['changed']),dict(layer_blobs=['changed'])]:
                with self.subTest(change=change),self.assertRaises(ValueError):
                    r.verify_archive(path,{**expected,**change})
            with tarfile.open(path) as tar: offset=tar.getmember('blobs/sha256/'+layer['digest'][7:]).offset_data
            raw=bytearray(path.read_bytes());raw[offset]^=1;path.write_bytes(raw)
            changed={**expected,'archive_sha256':r.sha256_file(path)}
            with self.assertRaisesRegex(ValueError,'REFUSED_RUNTIME_BLOB_HASH'): r.verify_archive(path,changed)


if __name__=='__main__': unittest.main()
