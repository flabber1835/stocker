"""Review-only workflow/source/command boundaries without financial imports."""
import ast
import json
from pathlib import Path

import pytest

import system_campaign_close_review_job as job


def test_exact_review_request_retains_all258_sources_and_original_parent():
    value=job.expected_request();old=job.original_request()
    assert value==json.loads((job.HERE/'system-campaign-p02-close-review-request.json').read_bytes())
    assert len(value['sources'])==263
    assert {n:value['sources'][n] for n in old['sources']}==old['sources']
    assert value['original_predecessor_file']==old['predecessor_file']
    assert value['original_predecessor_sha256']==old['predecessor_sha256']
    assert value['financial_replay_authorized'] is False
    target=json.loads((job.HERE/value['review_target_file']).read_bytes())
    assert target['review_only'] is True and target['financial_resume_authorized'] is False
    assert target['selected_session']=='2024-04-30' and len(target['repairs'])==36


def test_entrypoint_refuses_an_economic_or_old_reviewer_command(monkeypatch):
    value=dict(Config=dict(Cmd=['-B','-u','/driver/system_campaign_close_review_run.py',
        '--request','/driver/system-campaign-p02-close-review-request.json']))
    monkeypatch.setattr(job,'prior_inspect',lambda *args:value)
    assert job.inspect('capital-system-factual-p02-review-1-1')==value
    value['Config']['Cmd'][2]='/driver/system_campaign_p02_close_run.py'
    with pytest.raises(ValueError):job.inspect('capital-system-factual-p02-review-1-1')


def test_single_stopped_review_worker_and_no_economic_dispatch():
    tree=ast.parse(Path(job.__file__).read_bytes())
    calls=[v for v in ast.walk(tree) if isinstance(v,ast.Call)]
    workers=[v for v in calls if ast.unparse(v.func)=='stopped_run']
    commands=[v for v in calls if ast.unparse(v.func)=='command']
    assert len(workers)==len(commands)==1 and ast.literal_eval(commands[0].args[-1])=='review'
    assert not any(ast.unparse(v.func) in {'economic','backtest.main','runtime.advance'} for v in calls)
    runner=ast.parse((job.HERE/'system_campaign_close_review_run.py').read_bytes())
    assert not any(isinstance(v,ast.Call) and ast.unparse(v.func) in
        {'economic','backtest.main','runtime.advance','write_checkpoint'} for v in ast.walk(runner))


def test_workflow_has_only_explicit_review_trigger_and_encrypted_outputs():
    raw=(Path(__file__).parents[3]/'.github/workflows/capital-system-p02-close-review.yml').read_text(encoding='utf8')
    assert "paths: ['research/capital_risk/system-campaign-p02-close-review-request.json']" in raw
    assert 'system-optimization-002-p02-only' in raw and 'retention-days: 7' in raw
    assert 'capital-system-p02-close.yml' not in raw
    assert 'p02-close-review.tar.crseal' in raw and 'contents: read' in raw
