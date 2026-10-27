import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
spec=importlib.util.spec_from_file_location("risk_stage",Path(__file__).parents[1]/"stage.py")
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)


class StageGuards(unittest.TestCase):
    def test_exact_stage_request_and_refusals(self):
        request=dict(schema="research.capital-risk-stage-request/1",request_id="stage-001",stage="stage",
                     protocol_sha256=stage.PROTOCOL,expected_image=stage.IMAGE,release=stage.RELEASE,
                     manifest_sha256="a"*64,assets={n:dict(sha256="b"*64,bytes=1024)
                     for n in ["data.tar.crseal","runtime.tar.crseal"]})
        stage.validate_request(request)
        for change in [dict(stage="replay"),dict(expected_image="latest"),dict(release="production"),
                       dict(protocol_sha256="b"*64),dict(extra="secret"),dict(assets={})]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                stage.validate_request({**request,**change})


if __name__=="__main__": unittest.main()
