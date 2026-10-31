import importlib.util
import hashlib
import io
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).parents[1]))
spec=importlib.util.spec_from_file_location("risk_stage",Path(__file__).parents[1]/"stage.py")
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)


class StageGuards(unittest.TestCase):
    def request(self):
        return dict(schema="research.capital-risk-stage-request/1",request_id="stage-001",stage="stage",
                    protocol_sha256=stage.PROTOCOL,expected_image=stage.IMAGE,release=stage.RELEASE,
                    manifest_sha256="a"*64,assets={n:dict(sha256="b"*64,bytes=1024)
                    for n in ["data.tar.crseal","runtime.tar.crseal"]})

    def test_exact_stage_request_and_refusals(self):
        request=self.request()
        stage.validate_request(request)
        for change in [dict(stage="replay"),dict(expected_image="latest"),dict(release="production"),
                       dict(protocol_sha256="b"*64),dict(extra="secret"),dict(assets={})]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                stage.validate_request({**request,**change})

    def test_part_order_names_lengths_and_hashes_are_bound(self):
        request=self.request()
        spec=request['assets']['data.tar.crseal']
        spec['parts']=[dict(name=f'data.tar.crseal.part-{i:04d}',bytes=512,sha256='b'*64) for i in range(2)]
        stage.validate_request(request)
        for changed in [dict(name='../escape'),dict(name='data.tar.crseal.part-0001'),
                        dict(bytes=511),dict(sha256='invalid')]:
            bad=copy.deepcopy(request);bad['assets']['data.tar.crseal']['parts'][0].update(changed)
            with self.subTest(changed=changed),self.assertRaises(ValueError): stage.validate_request(bad)

    def test_acquire_checks_each_part_before_accepting_reassembled_ciphertext(self):
        values=[b'a'*512,b'b'*512]
        spec=dict(bytes=1024,sha256=hashlib.sha256(b''.join(values)).hexdigest(),parts=[
            dict(name=f'data.tar.crseal.part-{i:04d}',bytes=len(v),sha256=hashlib.sha256(v).hexdigest())
            for i,v in enumerate(values)])
        def responses(data):
            result=[]
            for value in data:
                response=io.BytesIO(value);response.headers={'Content-Length':str(len(value))};result.append(response)
            return result
        with tempfile.TemporaryDirectory(prefix='.capital-risk-test-',dir=Path.cwd()) as folder:
            root=Path(folder)
            with mock.patch.object(stage.urllib.request,'urlopen',side_effect=responses(values)):
                path=stage.acquire('data.tar.crseal',spec,root)
            self.assertEqual(path.read_bytes(),b''.join(values))
            path.unlink()
            with mock.patch.object(stage.urllib.request,'urlopen',side_effect=responses([values[0],b'x'*512])):
                with self.assertRaisesRegex(ValueError,'REFUSED_DOWNLOAD_PART_OR_LENGTH'):
                    stage.acquire('data.tar.crseal',spec,root)


if __name__=="__main__": unittest.main()
