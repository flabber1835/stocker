"""Signed review events preserve bounded causes without retaining display prose."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import hashlib
import inspect
import json
import pytest
from sentinel.panel import model,review

NOW=datetime(2031,4,21,22,tzinfo=timezone.utc)


def page(row):return model.Panel(rows=[row],now=NOW)


@pytest.mark.parametrize('row,code',[
 (model.feed_row(frontier=None,sessions_behind=None,ready=None,checks_passed=0,checks_total=0,as_of=NOW,error='frontier timed out'),'FEED_FRONTIER_READ_TIMEOUT'),
 (model.feed_row(frontier=None,sessions_behind=None,ready=None,checks_passed=0,checks_total=0,as_of=NOW,error='frontier CorpusLockUnavailable: synthetic pin refusal'),'FEED_PUBLICATION_PIN_REFUSED'),
 (model.feed_row(frontier='2031-04-21',sessions_behind=0,ready=None,checks_passed=0,checks_total=0,as_of=NOW,publication_version=7),'FEED_BOUND_VERDICT_PENDING'),
 (model.feed_row(frontier='2031-04-21',sessions_behind=0,ready=False,checks_passed=1,checks_total=2,as_of=NOW),'FEED_CONTRACT_FAILED'),
])
def test_feed_origin_codes_do_not_change_or_rewrite_the_fact(row,code):
    p=page(row);before=replace(row)
    result=review.condition_evidence(p,['feed'])['feed']
    assert result['code']==code and row==before
    assert result['raw_status']==row.status and result['effective_status']==row.effective_status(NOW)


def test_diagnostics_never_contain_raw_display_strings():
    row=model.Row('feed','Feed','UNREADABLE',model.UNKNOWN,'synthetic nonpublic diagnostic prose',NOW)
    result=review.condition_evidence(page(row),['feed'])
    assert row.detail not in json.dumps(result) and row.value not in json.dumps(result)
    assert result['feed']['detail_sha256']==hashlib.sha256(row.detail.encode()).hexdigest()
    assert set(result['feed'])=={'code','raw_status','effective_status','sampled_at','as_of','original_valid_until','recovery_phase','value_sha256','detail_sha256'}


@pytest.mark.parametrize('delta,code',[(timedelta(minutes=-2),'ROW_PROOF_EXPIRED'),(timedelta(seconds=6),'ROW_CLOCK_FUTURE')])
def test_original_failure_clock_is_retained(delta,code):
    at=NOW+delta;row=model.Row('feed','Feed','old',model.OK,as_of=at,freshness=timedelta(minutes=1),required_current=True)
    result=review.condition_evidence(page(row),['feed'])['feed']
    assert result['code']==code and result['as_of']==at.isoformat()
    assert result['original_valid_until']==(at+timedelta(minutes=1)).isoformat()


def test_missing_and_excess_conditions_are_explicitly_bounded():
    p=page(model.Row('feed','Feed','READY'))
    assert review.condition_evidence(p,['backend_sources'])['backend_sources']['code']=='BACKEND_SOURCE_UNAVAILABLE'
    result=review.condition_evidence(p,['missing:'+str(n) for n in range(40)])
    assert len(result)==33 and result['_limit']['condition_count']==40


def test_removed_hashing_has_an_executed_privacy_falsifier(monkeypatch):
    text=inspect.getsource(review.condition_evidence);guard="hashlib.sha256(row.detail.encode('utf-8')).hexdigest()"
    assert text.count(guard)==1
    namespace=dict(vars(review));exec(compile(text.replace(guard,'row.detail'),'<removed review privacy boundary>','exec'),namespace)
    monkeypatch.setattr(review,'condition_evidence',namespace['condition_evidence'])
    with pytest.raises(AssertionError):test_diagnostics_never_contain_raw_display_strings()
