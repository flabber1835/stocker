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
    assert [t['ticker'] for t in selected('2018-11-27')[2]]==['AET','OCLR']
    assert selected('2018-12-10') is None
    assert f.original_delivery_selection('P07','2020-12-31') is None
    assert f.original_delivery_selection('P05','2018-11-05')[2][0]['ticker'] == 'COL'
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
    assert [t['ticker'] for t in removed_guard('original_delivery_selection','FUTURE_ORIGINAL_DELIVERY_NO_CONSUMED_PENDING_NATIVE')('P05','2018-11-26')[2]]==['AET','OCLR']


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


def inherited_fixture(tmp_path,monkeypatch):
    term,row=fixture()
    added=dict(term['added'],cash_in_lieu_price_per_delivered_share=100.)
    suppression=dict(session=term['native_session'],security_id=term['security_id'],term_sha256=term['native_term_sha256'])
    doc=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='a'*64,suppress=[suppression],add=[added])
    raw=(json.dumps(doc,sort_keys=True,indent=2)+'\n').encode();h=f.sha(raw)
    root=tmp_path/'book/repairs';root.mkdir(parents=True);(root/(h+'.json')).write_bytes(raw)
    cp=dict(source_cursor='2018-08-31',repairs=[dict(filename=h+'.json',sha256=h,predecessor_checkpoint_sha256='a'*64)])
    monkeypatch.setattr(f,'inherited_delivery_row',lambda t:deepcopy(row))
    return cp,term,row,raw


def test_inherited_mixed_proxy_is_hydrated_from_the_exact_full_row_before_comparison(tmp_path,monkeypatch):
    cp,term,row,raw=inherited_fixture(tmp_path,monkeypatch);before=deepcopy((cp,term,row))
    remaining,proofs=f.remaining_ordinary_terms(cp,[term],tmp_path);proof,=proofs
    assert remaining==[] and proof['inherited_addition']['cash_in_lieu_price_per_delivered_share']==100.
    assert proof['selected_catalog_addition']['cash_in_lieu_price_per_delivered_share']is None
    assert proof['inherited_delivery_source_row']==row and proof['hydrated_catalog_addition']==proof['inherited_addition']
    assert (cp,term,row)==before and (tmp_path/'book/repairs'/cp['repairs'][0]['filename']).read_bytes()==raw


def test_inherited_proxy_must_equal_the_frozen_quote_even_when_metadata_is_valid(tmp_path,monkeypatch):
    cp,term,row,_=inherited_fixture(tmp_path,monkeypatch)
    row['raw_open']='101.0';term['proxy']['source_observation_sha256']=f.digest(row)
    with pytest.raises(ValueError,match='ONE_EQUIVALENT_FORWARD_EVENT'):f.remaining_ordinary_terms(cp,[term],tmp_path)
    assert removed_guard('remaining_ordinary_terms','FUTURE_INHERITED_ORDINARY_ONE_EQUIVALENT_FORWARD_EVENT')(cp,[term],tmp_path)[0]==[]


def test_inherited_quote_cannot_change_its_pinned_full_raw_row(tmp_path,monkeypatch):
    cp,term,row,_=inherited_fixture(tmp_path,monkeypatch);row['raw_open']='101.0'
    with pytest.raises(ValueError,match='EXACT_FROZEN_IDENTITY_AND_PROXY'):f.remaining_ordinary_terms(cp,[term],tmp_path)


def test_inherited_proxy_positive_quote_guard_removal_falsifier():
    term,row=fixture();row['raw_open']='-1.0';term['proxy']['source_observation_sha256']=f.digest(row)
    with pytest.raises(ValueError,match='EXACT_POSITIVE_RAW_OPEN'):f.inherited_delivery_addition(term,row)
    assert removed_guard('inherited_delivery_addition','FUTURE_INHERITED_DELIVERY_EXACT_POSITIVE_RAW_OPEN')(term,row)['cash_in_lieu_price_per_delivered_share']==-1.


def test_inherited_delivery_duplicate_row_guard_removal_falsifier(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    term,row=fixture()
    monkeypatch.setattr(f,'hosted',lambda:None)
    monkeypatch.setattr(f.zipfile,'ZipFile',lambda name:nullcontext(object()))
    monkeypatch.setitem(sys.modules,'research.pooled_input_support',
        SimpleNamespace(inputs=SimpleNamespace(_archive_rows=lambda archive,name:[row,deepcopy(row)])))
    with pytest.raises(ValueError,match='ONE_FROZEN_ROW'):f.inherited_delivery_row(term)
    assert removed_guard('inherited_delivery_row','FUTURE_INHERITED_DELIVERY_ONE_FROZEN_ROW')(term)==row
