"""One primary-confirmed mandatory common-share exchange; no new financial model."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_stock_calendar as stock

CATALOG = 'system-campaign-wwe-tko-terminal-facts.json'
SID, DELIVERED = '426024777347801008', '351179184194166734'
NATIVE, DAY = '2023-09-11', '2023-09-12'


def validate(catalog):
    term, = catalog['terms']
    stock.validate_term(term)
    added = term['added']
    need(term['ticker'] == 'WWE' and term['security_id'] == SID
         and term['native_session'] == term['last_trading_session'] == NATIVE
         and term['actual_completion_date'] == added['session'] == DAY
         and added['kind'] == 'CONVERSION' and added['cash_per_share'] is None
         and type(added['exchange_ratio']) is float and added['exchange_ratio'] == 1.0
         and added['delivered_security_id'] == DELIVERED and added['delivered_ticker'] == 'TKO'
         and added['delivered_issuer_id'] == 'SEC_CIK:1094084'
         and term['frozen_provider_issuer_limitation']['actual_new_issuer'] == 'SEC_CIK:1973266'
         and term['primary_source'] == 'https://www.sec.gov/Archives/edgar/data/1091907/000119312523233499/d519698d8k.htm'
         and term['timing_source'] == 'https://corporate.wwe.com/f/docs/sec-filings/16925127.PDF',
         'WWE_EXACT_COMMON_SHARE_RATIO_CLOCK_AND_FROZEN_DELIVERY_IDENTITY')
    dividend = catalog['separate_dividend']
    need(dividend == dict(issuer='TKO', amount='3.86', ex_date='2023-09-21',
        record_date='2023-09-22', payable_date='2023-09-29',
        frozen_bar_already_contains_dividend=True, new_dividend_or_merger_cash_added=False),
        'WWE_SEPARATE_EXISTING_DIVIDEND_NOT_ADDED_TO_CONVERSION')
    need(catalog['commitment_group']['catalog_file'] == CATALOG
         and catalog['commitment_group']['loader_file'] == 'system_campaign_stock_calendar.py'
         and catalog['loader_sha256'] == sha(Path(stock.__file__).read_bytes()),
         'WWE_EXACT_ORIGINAL_UNCHANGED_STOCK_COMPILER')
    return catalog


def build(cp, old, out):
    path = Path(__file__).parent / CATALOG
    validate(json.loads(path.read_bytes()))
    return stock.build(cp, old, out, path)
