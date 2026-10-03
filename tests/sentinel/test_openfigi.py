import io
import json
from urllib.error import HTTPError

import pytest
from sentinel.feed import openfigi
from sentinel.feed.alpaca_transport import AlpacaTransportRefused, AlpacaTransportUnavailable


def asset(symbol='ABC'):
    return {'asset_id':'uuid', 'ticker':symbol, 'name':'Name', 'exchange':'NYSE'}


def response(kind='Common Stock', broad='Common Stock', **changes):
    return {'data':[{'ticker':'ABC','exchCode':'US','marketSector':'Equity',
        'securityType':kind,'securityType2':broad,'compositeFIGI':'composite',
        'shareClassFIGI':'share', **changes}]}


@pytest.mark.parametrize('kind,broad', list(openfigi.ALLOWED_TYPES.items()))
def test_preserves_typed_broad_ordinary_equity_universe(kind,broad):
    item, reason = openfigi.classify(asset(), response(kind,broad))
    assert reason is None and item['asset_id']=='uuid'


@pytest.mark.parametrize('kind,broad', [('ETP','Mutual Fund'), ('Unit','Unit'),
    ('Preferred','Preferred'),('Equity WRT','Warrant'),('Right','Right')])
def test_no_name_or_suffix_can_turn_nonstock_into_common_stock(kind,broad):
    item, reason = openfigi.classify({**asset(),'name':'Common Stock'}, response(kind,broad))
    assert item is None


@pytest.mark.parametrize('changes', [{'ticker':'OTHER'},{'exchCode':'LN'},
    {'shareClassFIGI':None},{'marketSector':'Corp'},{'securityType2':None}])
def test_incomplete_or_wrong_listing_cannot_be_admitted(changes):
    assert openfigi.classify(asset(), response(**changes))[0] is None


def test_distinct_share_classes_cannot_be_merged_and_class_symbol_is_generic():
    values=response()
    values['data'].append({**values['data'][0],'shareClassFIGI':'different'})
    assert openfigi.classify(asset(), values)==(None,'ambiguous_mapping')
    assert openfigi.job(asset('CLASS.B'))['idValue']=='CLASS/B'
    assert openfigi.classify(asset('CLASS.B'), response(ticker='CLASS/B'))[0]['ticker']=='CLASS.B'


def test_incomplete_batch_coverage_and_job_errors_are_refusals():
    with pytest.raises(AlpacaTransportRefused,match='coverage'):
        openfigi.select_assets([asset()], {})
    with pytest.raises(AlpacaTransportUnavailable):
        openfigi.classify(asset(), {'error':'upstream test secret'})


class Reply(io.BytesIO):
    status=200


def test_read_only_post_is_fixed_and_credentials_are_absent_from_evidence(monkeypatch):
    monkeypatch.setenv('OPENFIGI_API_KEY','test-key')
    calls=[]
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return Reply(json.dumps([response()]).encode())
    client=openfigi.Client(opener=Opener())
    values, proof=client.mapping([asset()])
    assert client.batch_size==100 and values==[response()]
    assert calls[0].full_url==openfigi.ENDPOINT and calls[0].method=='POST'
    assert 'test-key' not in repr(proof)
    assert not any(key.lower().startswith('apca-') for key in calls[0].headers)


def test_free_pacing_and_retries_are_bounded_without_secret_errors(monkeypatch):
    monkeypatch.delenv('OPENFIGI_API_KEY',raising=False)
    delays=[]; calls=[]
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise HTTPError(openfigi.ENDPOINT,429,'test-secret',{},None)
    client=openfigi.Client(opener=Opener(),sleeper=delays.append,monotonic=lambda:0)
    with pytest.raises(AlpacaTransportUnavailable) as error:
        client.mapping([asset()])
    assert client.batch_size==10 and len(calls)==4 and 2.5 in delays
    assert 'test-secret' not in str(error.value)


def test_response_width_cannot_drop_an_asset_silently():
    class Opener:
        def open(self, request, timeout): return Reply(b'[]')
    with pytest.raises(AlpacaTransportRefused,match='count'):
        openfigi.Client(opener=Opener()).mapping([asset()])
