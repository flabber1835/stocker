"""Exact first suffix admission; no strategy, financial state or credentials."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

PROTOCOL="a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52"
EXPECTED=dict(schema="research.capital-risk-baseline-suffix-request/1",request_id="baseline-suffix-001",
    stage="baseline-suffix",arm="B",protocol_sha256=PROTOCOL,transitions=21,
    target_session="2007-11-05",target_formation_records=53,
    predecessor=dict(run_id=40532524116,attempt=1,source_commit="8d0e3508bee9e56a681bdf39557641543520176e",
        workflow_path=".github/workflows/capital-risk-baseline.yml",artifact_id=12746663588,
        artifact_name="capital-risk-baseline-prefix-8d0e3508bee9e56a681bdf39557641543520176e",
        artifact_digest="sha256:850135704551e01a6167201816e7d052a85656241ae3a6afbd578fca3e9f8cdc",
        artifact_bytes=3217792,cipher_name="baseline-prefix.tar.crseal",cipher_bytes=3215396,
        cipher_sha256="ef7d1bed74e387b236d6e8e054d3241f65362833cc50ab959351ff6508bf607d",
        session="2007-10-05",formation_records=32,
        outer_sha256="91062022d1190d660e225f69dd3627972029a107736257223d5226facaa4312c",
        inner_sha256="a7d44d8dd20e9a95ddf749aebbc79bd913bbf744091fc41624ad2db3012868a4",
        state_sha256="84f8c9a43e2148d0e59a6c1d1918670bf9569144695b316422b763c1d59c4533",
        input_sha256="f80ce65f6d2f83ee1bc27f2611addaf9ca2fbf9220d68d129363b16df29f55f1",
        base_sha256="5697e3e464e10f3a8ef91ea8fc38437e91ec0b2d0d36bcb942c9bb563ffb75f5"))


DADE=dict(schema=EXPECTED['schema'],request_id='baseline-suffix-002',stage='baseline-suffix',arm='B',
    protocol_sha256=PROTOCOL,transitions=77,target_session='2008-02-27',target_formation_records=126,
    target_measured_closes=4,expected_repair_count=1,
    expected_input_sha256='352f8c73766f564c83deead63fa5eaa6a9e7421e9c9badafbf343c73b621dc14',
    repair=dict(case='dade-20071106',earliest_session='2007-11-06',security_id='262420210501636253',
        cash_per_share=77,template_sha256='eec368273c89a80249483609e3b8da1957fd95f2e810cdc9d5804d67a85c91e8',
        overlay_sha256='eec368273c89a80249483609e3b8da1957fd95f2e810cdc9d5804d67a85c91e8'),
    predecessor=dict(run_id=40540062773,attempt=1,source_commit='4ca6b009ab8034c503295097658f73f623382fa3',
        workflow_path='.github/workflows/capital-risk-baseline-suffix.yml',artifact_id=12749399053,
        artifact_name='capital-risk-baseline-suffix-4ca6b009ab8034c503295097658f73f623382fa3',
        artifact_digest='sha256:9d4c242d89242d19a0b954b9ea1ce3e02b8618620f1bd68b0559ce1f61d31e4a',
        artifact_bytes=4469202,cipher_name='baseline-suffix.tar.crseal',cipher_bytes=4464676,
        cipher_sha256='0681c4810858f57ebe3a6aba3c42c5565de91ce53ab299eb5516565a1219a248',
        receipt_name='baseline-suffix.json',receipt_status='SUFFIX_PASSED',stage='baseline-suffix',
        session='2007-11-05',formation_records=53,measured_closes=0,repair_count=0,
        outer_sha256='57c7bb463205d76fbe3e7b2646a4e54c6c0465e7f6e30162d275013b61cd00db',
        inner_sha256='d8dee522b5491c0cbda3c31ee1e51d28bf4c8211d1458bfc210642d2530c9528',
        state_sha256='0af357c89e3431788fff3c9ac6fc5cacac63149d5ab3e4802b13a683233b09fd',
        input_sha256='f80ce65f6d2f83ee1bc27f2611addaf9ca2fbf9220d68d129363b16df29f55f1',
        base_sha256='5697e3e464e10f3a8ef91ea8fc38437e91ec0b2d0d36bcb942c9bb563ffb75f5'))
REQUESTS={v['request_id']:v for v in (EXPECTED,DADE)}


def request_template(request_id='baseline-suffix-001'): return deepcopy(REQUESTS[request_id])


def strict_equal(left,right):
    if type(left) is not type(right):return False
    if isinstance(right,dict):return set(left)==set(right) and all(strict_equal(left[k],v) for k,v in right.items())
    if isinstance(right,list):return len(left)==len(right) and all(strict_equal(a,b) for a,b in zip(left,right))
    return left==right


def validate_request(value):
    expected=REQUESTS.get(value.get('request_id')) if isinstance(value,dict) else None
    if expected is None or not strict_equal(value,expected):
        raise ValueError("REFUSED_SUFFIX_REQUEST")
    for field in ('run_id','attempt','artifact_id','artifact_bytes','cipher_bytes','formation_records'):
        if type(value['predecessor'][field]) is not int: raise ValueError("REFUSED_PREDECESSOR_TYPE")


def verify_remote(run, artifacts, request):
    validate_request(request);p=request['predecessor']
    if (run['id']!=p['run_id'] or run['run_attempt']!=p['attempt'] or run['head_sha']!=p['source_commit']
            or run['path']!=p['workflow_path'] or run['head_branch']!='codex/capital-risk-research'
            or run['event']!='push' or run['status']!='completed' or run['conclusion']!='success'
            or run['actor']['login']!='flabber1835' or run['repository']['id']!=1233957439
            or run['repository']['full_name']!='flabber1835/stocker'):
        raise ValueError("REFUSED_PREDECESSOR_SOURCE_RUN")
    selected=[v for v in artifacts['artifacts'] if v['id']==p['artifact_id']]
    if (len(selected)!=1 or selected[0]['name']!=p['artifact_name'] or selected[0]['expired']
            or selected[0]['digest']!=p['artifact_digest'] or selected[0]['size_in_bytes']!=p['artifact_bytes']):
        raise ValueError("REFUSED_PREDECESSOR_ARTIFACT")


def bootstrap(request_path: Path, output: Path):
    from probe import check_context, admitted_output
    check_context(os.environ)
    request=json.loads(request_path.read_bytes());validate_request(request)
    token=os.environ.pop('GH_TOKEN','')
    if not token: raise ValueError("REFUSED_BOOTSTRAP_TOKEN")
    child=dict(os.environ,GH_TOKEN=token)
    def get(path):
        result=subprocess.run(['gh','api',path],env=child,capture_output=True,check=True,timeout=30)
        return json.loads(result.stdout)
    run=request['predecessor']['run_id']
    verify_remote(get(f'repos/flabber1835/stocker/actions/runs/{run}'),
                  get(f'repos/flabber1835/stocker/actions/runs/{run}/artifacts'),request)
    child.pop('GH_TOKEN');token=None
    target=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(dict(status='PREDECESSOR_ADMITTED',predecessor=request['predecessor']),indent=2)+'\n')
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write(f"run_id={run}\nartifact_name={request['predecessor']['artifact_name']}\n")
    print('PREDECESSOR_ADMITTED')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    bootstrap(args.request,args.output)
