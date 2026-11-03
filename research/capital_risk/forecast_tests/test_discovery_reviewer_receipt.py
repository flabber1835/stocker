import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_discovery_suffix_job as job
from system_campaign_discovery_context import TAINT


def receipt():
    stop=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
    return dict(schema='research.exact-diagnostic-suffix-receipt/1',arm='P09',authority=TAINT,
        stage='campaign-disposable-discovery',financial_authority=False,account_performance_computed=False,
        production_contacted=False,status='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW',
        worker=dict(stop),reviewer=dict(stop))


def test_reviewer_receipt_has_actual_encrypted_export_not_only_marker(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    root=tmp_path/'stopped';root.mkdir();(root/'synthetic.txt').write_bytes(b'SYNTHETIC ONLY\n')
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='a'*64)))
    value=receipt();target=tmp_path/'discovery.json'
    job.finish_export(value,root,target,b'x'*32,request,known=True)
    assert value['encrypted_output_exported'] is True
    assert (tmp_path/'discovery.tar.crseal').stat().st_size==value['encrypted_output']['bytes']
    assert json.loads(target.read_bytes())['reviewer']==receipt()['reviewer']


@pytest.mark.parametrize('bad',[dict(cash=123),dict(stopped=True,exit_code=True,oom_killed=False,wait_error=None)])
def test_reviewer_nested_payload_or_bad_scalar_is_refused(tmp_path,bad):
    value=receipt();value['reviewer']=bad
    with pytest.raises(ValueError):job.write_public_receipt(tmp_path/'public.json',value)
