"""User action and dated history, with the actual browser control executed."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sentinel.panel import review_controls
from sentinel.panel.review_model import OperatorReview


@pytest.mark.parametrize('case',['absent','success','refused','network','timeout'])
def test_acknowledgement_requires_click_and_a_current_successful_server_response(case):
    node=shutil.which('node')
    if not node:
        pytest.fail('Node is required for dashboard acknowledgement qualification')
    script=review_controls.SCRIPT.removeprefix('<script>').removesuffix('</script>')
    result=subprocess.run([node,str(Path(__file__).with_name('panel_review_harness.cjs'))],
        input=json.dumps(dict(script=script,case=case)),text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert result.stdout=='PASS\n'


def test_recovered_cause_is_visible_and_escaped_and_retained_page_cannot_ack():
    now=datetime.now(timezone.utc)
    review=OperatorReview(scope='a'*64,head=2,reviewed_head=1,status='REVIEW',
        observed_at=now,reviewed_at=now,token='unique-private-view',events=[
            dict(at=now.isoformat(),kind='RECOVERED',details={'previous':['<broker failure>']})])
    html=review_controls.render(review)
    assert '&lt;broker failure&gt;' in html and '<broker failure>' not in html
    assert 'unique-private-view' in html
    retained=review_controls.render(review,current=False)
    assert 'unique-private-view' not in retained


def test_active_failure_cannot_render_a_green_baseline_action():
    now=datetime.now(timezone.utc)
    review=OperatorReview(scope='a'*64,head=2,reviewed_head=1,status='FAILED',
        active=['broker'],observed_at=now)
    assert '<button' not in review_controls.render(review)
    assert 'active failure' in review_controls.render(review)


def test_unavailable_review_explains_the_specific_controlled_refusal():
    now=datetime.now(timezone.utc)
    review=OperatorReview(scope='a'*64,head=0,reviewed_head=0,status='UNAVAILABLE',
        observed_at=now,detail='Review signing key unavailable')
    assert 'Review signing key unavailable' in review_controls.render(review)


def test_driver_details_cannot_leak_into_review_error_copy():
    import psycopg
    from sentinel.panel.review import failure_detail
    from sentinel.operational_catalog import OperationalCatalogRefused
    from sentinel.panel.review_store import ReviewRefused
    private='synthetic-private-connection-detail'
    assert private not in failure_detail(psycopg.OperationalError(private))
    assert private not in failure_detail(ValueError(private))
    assert 'schema is missing or changed' in failure_detail(OperationalCatalogRefused(private))
    assert 'authentication failed' in failure_detail(ReviewRefused('operator review authentication failed'))
