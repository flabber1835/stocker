"""Pure failure-scope guards; no hosted download or financial runtime."""
from copy import deepcopy

import pytest

from forecast_tests.test_close_admission import without_guard
import system_campaign_close_review_admit as module


def fixture():
    return dict(arm='P02',stage='campaign-factual-suffix',review_only=True,
        financial_resume_authorized=False,review_refusal=module.REASON,
        run_id=41214327942,head='1d339cfd1426a90b6fd3c4cd8c8100829ad39c57',
        artifact_id=13048057396,zip_bytes=158619057,
        zip_sha256='028f0c7da0d7a21bdefeb4bebefb0976d313c8ad5b9676a10a79c89bd949ce3d',
        request_sha256='bf01f5d065c4a00b006f59f70138cc8ad3ea716a91c35b3cd5a75a3ad0bc91a0',
        receipt_schema='research.system-p02-close-suffix-receipt/1',
        outer_sha256=module.OUTER,selected_session='2024-04-30')


def test_only_exact_stopped_book_is_admitted_for_review_metadata():
    spec=fixture();before=deepcopy(spec)
    module.require_review_only(spec)
    assert spec==before


@pytest.mark.parametrize('field,value', [('review_only',1),('financial_resume_authorized',True),
    ('arm','P03'),('run_id',41214327943),('artifact_id',13048057397),
    ('outer_sha256','0'*64),('review_refusal','OTHER_FAILURE'),('selected_session','2024-05-01')])
def test_foreign_or_resume_scope_refused(field,value):
    spec=fixture();spec[field]=value
    with pytest.raises(ValueError):module.require_review_only(spec)


def test_actual_review_only_guard_removal_allows_forbidden_resume_flag():
    spec=fixture();spec['financial_resume_authorized']=True
    with pytest.raises(ValueError):module.require_review_only(spec)
    broken=without_guard(module,'require_review_only',
        'CLOSE_REVIEW_ONLY_EXACT_ACTUAL_FAILED_OUTPUT_NOT_FINANCIAL_ADMISSION')
    broken(spec)


def test_original_crypto_source_is_required_before_any_hosted_download(monkeypatch):
    monkeypatch.setattr(module,'SOURCE_SHA','0'*64)
    with pytest.raises(ValueError,match='UNCHANGED_ORIGINAL_CRYPTO_SOURCE'):
        module.admit(fixture(),None,None)
