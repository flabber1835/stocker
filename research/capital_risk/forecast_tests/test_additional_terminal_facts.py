"""Public factual scope and private hydration fence; no market replay."""
import json
from pathlib import Path
import pytest
from system_campaign_terminal_facts import TerminalFacts


def test_public_catalog_has_no_private_quote_and_no_unproved_aaap_cash():
    path=Path(__file__).parents[1]/'system-campaign-additional-terminal-facts.json'
    doc=json.loads(path.read_bytes());terms={v['ticker']:v for v in doc['terms']}
    assert set(terms)=={'WFM','RICE1','RXDX1','SODA','SONC','BEL'}
    assert terms['RICE1']['added']['exchange_ratio']==.37
    assert terms['SODA']['native_session']=='2018-12-04' and terms['SODA']['added']['session']=='2018-12-06'
    assert terms['BEL']['added']['session']=='2019-04-17'
    for term in terms.values():
        assert term['added']['cash_in_lieu_price_per_delivered_share'] is None
        assert 'source_observation' not in term and 'raw_open' not in term
    assert doc['unresolved'][0]['ticker']=='AAAP1'


def test_hydration_refuses_before_frozen_inputs_or_output(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    facts=TerminalFacts(Path(__file__).parents[1]/'system-campaign-additional-terminal-facts.json')
    target=tmp_path/'must-not-exist.json'
    with pytest.raises(ValueError,match='HOSTED_ADDITIONAL_FACTS_ONLY'):facts.hydrate(target)
    assert not target.exists()
