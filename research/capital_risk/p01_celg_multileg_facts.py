"""Typed retained CELG facts/quotes and exact component math. No engine or I/O routes."""
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

PRIMARY_SHA = 'd37338e720666f2c3bd9bf6c8f2a0e315f1eebc53ec597d5348bc36b5a6e3156'
QUOTE_GZIP_SHA = '17358d350e627caa2eda430fbad850a4f13e68f6db689428bcb270ae876aa455'
QUOTE_RAW_SHA = 'fbbd4ee52eadf5e8498c2ab3135b9b368b35a5f9354941a06307468b96e24769'


def need(value, reason):
    if not value:
        raise ValueError('P01_CELG_'+reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Identity(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    issuer_cik: Literal['14272'] = '14272'
    legal_symbol: Literal['BMYRT'] = 'BMYRT'
    provider_symbol: Literal['BMY.RT'] = 'BMY.RT'
    legal_source_accession: Literal['0001104659-19-065939'] = '0001104659-19-065939'
    legal_source_url: Literal['https://www.sec.gov/Archives/edgar/data/816284/000110465919065939/tm1923405d1_8k.htm'] = \
        'https://www.sec.gov/Archives/edgar/data/816284/000110465919065939/tm1923405d1_8k.htm'
    canonical_security_id: None = None
    alpha_eligible: Literal[False] = False


class Quote(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    identity: Identity
    session: Literal['2019-11-21'] = '2019-11-21'
    source_timestamp: Literal['2019-11-21T05:00:00Z'] = '2019-11-21T05:00:00Z'
    raw_open: Literal['2.30'] = '2.30'
    raw_close: Literal['2.25'] = '2.25'
    adjustment: Literal['raw'] = 'raw'
    feed: Literal['sip'] = 'sip'
    gzip_sha256: Literal[QUOTE_GZIP_SHA] = QUOTE_GZIP_SHA
    raw_sha256: Literal[QUOTE_RAW_SHA] = QUOTE_RAW_SHA


class Terms(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.p01-celg-multileg-factual-preparation/1'] = 'research.p01-celg-multileg-factual-preparation/1'
    source_security_id: Literal['11651249425833422'] = '11651249425833422'
    source_ticker: Literal['CELG'] = 'CELG'
    delivered_security_id: Literal['578964201416671255'] = '578964201416671255'
    delivered_ticker: Literal['BMY'] = 'BMY'
    delivered_issuer_id: Literal['SEC_CIK:14272'] = 'SEC_CIK:14272'
    completion_calendar_day: Literal['2019-11-20'] = '2019-11-20'
    economic_session: Literal['2019-11-21'] = '2019-11-21'
    legal_cash_per_source: Literal['50.00'] = '50.00'
    delivered_shares_per_source: Literal['1'] = '1'
    right_units_per_source: Literal['1'] = '1'
    contingent_maximum_is_fixed_cash: Literal[False] = False
    right: Identity
    quote: Quote
    financial_input_admitted: Literal[False] = False
    predecessor_selected: Literal[False] = False
    old515_source_changed: Literal[False] = False
    canonical_multileg_decoder_qualified: Literal[False] = False


def decode_quote(compressed, capture):
    """Authenticate retained gzip/raw bytes and exact query before interpreting price."""
    need(type(compressed) is bytes and len(compressed) == 263 and sha(compressed) == QUOTE_GZIP_SHA,
         'EXACT_RETAINED_QUOTE_GZIP')
    raw = gzip.decompress(compressed)
    need(len(raw) == 473 and sha(raw) == QUOTE_RAW_SHA, 'EXACT_RETAINED_RAW_RESPONSE')
    receipt = [r for r in capture['receipts'] if r.get('file') == 'provider-001.json.gz']
    need(len(receipt) == 1, 'UNIQUE_RETAINED_QUOTE_RECEIPT')
    receipt = receipt[0]
    need(receipt['sha256'] == QUOTE_GZIP_SHA and receipt['raw_sha256'] == QUOTE_RAW_SHA
         and receipt['endpoint'] == 'https://data.alpaca.markets/v2/stocks/bars'
         and receipt['status'] == 'RESPONSE_CAPTURED'
         and receipt['params'] == dict(adjustment='raw',asof='2019-11-21',
             end='2019-11-23T00:00:00Z',feed='sip',limit=100,sort='asc',
             start='2019-11-21T00:00:00Z',symbols='BMY,BMY.RT',timeframe='1Day'),
         'EXACT_RAW_SIP_QUERY_AND_SYMBOL_MAPPING')
    data = json.loads(raw, parse_float=Decimal)
    need(data['next_page_token'] is None and set(data['bars']) == {'BMY','BMY.RT'},
         'COMPLETE_RESPONSE_IDENTITIES')
    rows = [r for r in data['bars']['BMY.RT'] if r['t'] == '2019-11-21T05:00:00Z']
    need(len(rows) == 1 and rows[0]['o'] == Decimal('2.30') and rows[0]['c'] == Decimal('2.25'),
         'UNIQUE_FIRST_SESSION_RAW_OPEN_AND_CLOSE')
    return Quote(identity=Identity())


def prepare(primary, compressed, capture):
    need(sha(primary) == PRIMARY_SHA, 'EXACT_RETAINED_PRIMARY_EXTRACTION')
    source = json.loads(primary)
    need(source['source_accession'] == '0001104659-19-065939'
         and source['consideration_per_eligible_common_share'] == dict(
             BMYRT_tradeable_CVR_units='1',BMY_common_shares='1',cash_usd='50.00')
         and source['cessation']['preopen_date'] == '2019-11-21'
         and source['contingent_CVR_payment']['fixed_merger_cash'] is False,
         'PRIMARY_ALL_THREE_LEGS_AND_CORRECT_CLOCK')
    right = Identity()
    return Terms(right=right, quote=decode_quote(compressed,capture))


def exact(value, *, positive=False, nonnegative=False):
    need(type(value) in (str,int,Decimal,Fraction), 'EXACT_DECIMAL_OR_FRACTION_INPUT_NO_FLOAT_BOOL')
    try:
        parsed = Fraction(value)
    except (ValueError,TypeError,OverflowError,ZeroDivisionError) as error:
        raise ValueError('P01_CELG_INVALID_EXACT_NUMBER') from error
    need(not positive or parsed > 0, 'POSITIVE_NUMBER_REQUIRED')
    need(not nonnegative or parsed >= 0, 'NONNEGATIVE_NUMBER_REQUIRED')
    return parsed


class Package(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    authority: Literal['PREPARATION_ONLY_NOT_CANONICAL_EXECUTION'] = 'PREPARATION_ONLY_NOT_CANONICAL_EXECUTION'
    source_shares: str
    delivered_whole_bmy_shares: int
    right_units: int
    legal_merger_cash: str
    gross_right_value: str
    right_sale_fees: str
    net_right_sale_cash: str
    gross_opening_package: str
    raw_reference_multiplier: str
    signal_reference_multiplier: str
    leadership_close_consideration: str
    financial_input_admitted: Literal[False] = False
    canonical_settlement_qualified: Literal[False] = False


def package(terms, quantities, *, bmy_raw_open, bmy_raw_close,
            source_signal_to_raw, delivered_signal_to_raw, cost_bps):
    """Hand-checkable exact expectations for a later canonical qualifier; no state mutation."""
    terms = Terms.model_validate(terms)
    need(type(quantities) in (list,tuple) and quantities, 'NONEMPTY_HOLDER_QUANTITIES')
    shares = sum((exact(q, positive=True) for q in quantities),Fraction())
    need(shares.denominator == 1, 'FRACTIONAL_RIGHT_ENTITLEMENT_UNSUPPORTED')
    units = shares.numerator
    opening = exact(bmy_raw_open,positive=True); closing = exact(bmy_raw_close,positive=True)
    source = exact(source_signal_to_raw,positive=True); delivered = exact(delivered_signal_to_raw,positive=True)
    costs = exact(cost_bps,nonnegative=True)
    need(costs < 10000, 'SALE_COST_MUST_BE_BELOW_GROSS_PROCEEDS')
    legal = shares*exact(terms.legal_cash_per_source)
    gross_right = shares*exact(terms.quote.raw_open)
    fees = gross_right*costs/10000
    gross_package = legal+shares*opening+gross_right
    raw_multiplier = shares*opening/gross_package
    close_consideration = exact(terms.legal_cash_per_source)+closing+exact(terms.quote.raw_close)
    return Package(source_shares=str(shares),delivered_whole_bmy_shares=units,right_units=units,
        legal_merger_cash=str(legal),gross_right_value=str(gross_right),right_sale_fees=str(fees),
        net_right_sale_cash=str(gross_right-fees),gross_opening_package=str(gross_package),
        raw_reference_multiplier=str(raw_multiplier),signal_reference_multiplier=str(raw_multiplier*delivered/source),
        leadership_close_consideration=str(close_consideration))


def require_exact_canonical_allocations(source_quantities, actual_delivered):
    """Check actual canonical helper output later; never repair its float representations."""
    need(len(source_quantities) == len(actual_delivered), 'CANONICAL_ALLOCATION_COUNT')
    source = [exact(q,positive=True) for q in source_quantities]
    need(all(type(q) in (int,float) and type(q) is not bool for q in actual_delivered),
         'CANONICAL_NUMERIC_SHARE_OUTPUT_REQUIRED')
    actual = [exact(str(q),positive=True) for q in actual_delivered]
    need(actual == source and sum(actual,Fraction()).denominator == 1,
         'CANONICAL_CONVERSION_REPRESENTATION_OR_QUANTITY_REFUSED')
