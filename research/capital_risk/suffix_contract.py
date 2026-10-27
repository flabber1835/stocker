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


def request_template(): return deepcopy(EXPECTED)


def validate_request(value):
    if value!=EXPECTED or type(value.get('transitions')) is not int:
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
