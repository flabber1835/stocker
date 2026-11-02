"""Exact component scope and parser-stop boundary only, no network/canonical run."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import system_campaign_pxd_review_admit as subject


def spec():
    return json.loads((Path(subject.__file__).parent/'system-campaign-pxd-corrected-review.json').read_bytes())


def test_exact_review_component_spec_is_not_financial_admission():
    s=spec();subject.scope(s)
    assert s['review_only'] and s['financial_admission'] is False and s['financial_resume_authorized'] is False
    subject.stopped_function()  # Compile the new-role classifier; do not invoke a runtime.


@pytest.mark.parametrize('field,value',[('financial_admission',True),('financial_resume_authorized',True),
    ('run_id',41214327942),('zip_sha256','0'*64),('inventory_members',20)])
def test_foreign_partial_or_financial_role_refuses(field,value):
    changed=deepcopy(spec());changed[field]=value
    with pytest.raises(ValueError,match='EXACT_NONFINANCIAL_CORRECTED_ARTIFACT'):subject.scope(changed)
