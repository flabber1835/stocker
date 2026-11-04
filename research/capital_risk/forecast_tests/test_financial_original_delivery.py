"""Literal mixed-term reuse and exact delivered source identity; no replay."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard


def selected(cursor='2018-10-31'):
    return f.original_delivery_selection('P05', cursor)


def test_original_mixed_term_and_validator_are_exact_and_cash_stays_separate():
    codec, name, terms = selected()
    term, = terms
    original = json.loads((f.HERE / name).read_bytes())['terms'][1]
    assert term['added'] == original['added']
    assert term['proxy'] == original['proxy']
    assert term['ticker'] == 'COL' and term['added']['cash_per_share'] == 93.33
    assert term['added']['exchange_ratio'] == .37525
    assert codec.catalog_sha == 'f2467de7dd56d1b69bac24be9caeeedd6be946e1e898dce9a9afefe054437018'
    assert codec.compiler_sha == '025be4d9649f8f81f970757f74899044a576e7c1c4f0297e6ccfc7cdf32030ae'
    assert [t['ticker'] for t in f.original_ordinary_selection('P05','2018-10-31')[2]] == ['KS']
    assert selected('2018-11-27') is None
    assert f.original_delivery_selection('P07','2020-12-31') is None
    assert f.selected('P05',cursor='2018-11-05')[2][0]['ticker'] == 'COL'
    merged = f.merge_selected_terms(f.original_ordinary_selection('P05','2018-10-31')[2], terms)
    assert [t['ticker'] for t in merged] == ['KS','COL']
    assert f.suppressions(dict(source_cursor='2018-10-31'), merged)[1]['session'] == '2018-11-26'


def test_catalog_byte_guard_removal_accepts_changed_source_description(tmp_path, monkeypatch):
    _, name, _ = selected()
    document = json.loads((f.HERE / name).read_bytes())
    document['terms'][1]['description'] = 'changed source description'
    (tmp_path / name).write_text(json.dumps(document))
    monkeypatch.setattr(f,'HERE',tmp_path)
    with pytest.raises(ValueError,match='DELIVERY_CATALOG_BYTES'):
        selected()
    assert removed_guard('original_delivery_selection','FUTURE_ORIGINAL_DELIVERY_CATALOG_BYTES')('P05','2018-10-31')[2]


def test_consumed_pending_native_guard_removal_drops_unresolved_delivery():
    with pytest.raises(ValueError,match='DELIVERY_NO_CONSUMED_PENDING_NATIVE'):
        selected('2018-11-26')
    assert removed_guard('original_delivery_selection','FUTURE_ORIGINAL_DELIVERY_NO_CONSUMED_PENDING_NATIVE')('P05','2018-11-26') is None


def fixture():
    term = deepcopy(selected()[2][0])
    row = dict(session='2018-11-27', security_id=term['added']['delivered_security_id'],
               ticker=term['added']['delivered_ticker'], issuer_id=term['added']['delivered_issuer_id'],
               listing_first_session='1980-01-02', security_type_eligible='0', raw_open='100.0')
    term['proxy']['source_observation_sha256'] = f.digest(row)
    return term, row


def test_complete_delivered_identity_keeps_provider_eligibility_and_full_row_hash():
    term,row=fixture();before=deepcopy((term,row))
    witness=f.ordinary_delivery_identity(term,row)
    assert witness['security_type_eligible']=='0' and witness['source_observation_sha256']==f.digest(row)
    assert witness['ticker']=='RTX' and witness['issuer_id'].startswith('SEC_UNKNOWN:')
    assert (term,row)==before


@pytest.mark.parametrize('key,value',[('session','2018-11-26'),('security_id','wrong'),('ticker','UTX'),('issuer_id','upgraded'),('listing_first_session','2020-01-01'),('security_type_eligible','2'),('raw_open','101.0')])
def test_modified_delivered_row_is_refused(key,value):
    term,row=fixture();row[key]=value
    with pytest.raises(ValueError,match='EXACT_FROZEN_IDENTITY_AND_PROXY'):
        f.ordinary_delivery_identity(term,row)


def test_delivery_identity_guard_removal_falsifier():
    term,row=fixture();row['issuer_id']='WRONG'
    with pytest.raises(ValueError,match='EXACT_FROZEN_IDENTITY_AND_PROXY'):
        f.ordinary_delivery_identity(term,row)
    assert removed_guard('ordinary_delivery_identity','FUTURE_ORIGINAL_DELIVERY_EXACT_FROZEN_IDENTITY_AND_PROXY')(term,row)['issuer_id']=='WRONG'
