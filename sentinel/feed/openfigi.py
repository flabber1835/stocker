"""Typed US-equity classification; identifier lookup has no broker authority."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from sentinel.feed import rolling_work
from sentinel.feed.alpaca_transport import (
    _NoRedirect, AlpacaTransportRefused, AlpacaTransportUnavailable,
)
from sentinel.feed.rolling_contract import digest

ENDPOINT = 'https://api.openfigi.com/v3/mapping'
POLICY = 'OPENFIGI_US_ORDINARY_EQUITY_V1'
ALLOWED_TYPES = {'Common Stock': 'Common Stock', 'ADR': 'Depositary Receipt',
                 'GDR': 'Depositary Receipt', 'MLP': 'Partnership Shares',
                 'REIT': 'REIT', 'Ltd Part': 'Partnership Shares',
                 'Royalty Trst': 'Common Stock', 'NY Reg Shrs': 'Depositary Receipt',
                 'Closed-End Fund': 'Mutual Fund'}


def inventory(assets):
    ids, symbols, result = set(), set(), []
    for asset in assets:
        sid, symbol = asset.get('id'), asset.get('symbol')
        if (not isinstance(sid, str) or not sid or sid in ids
                or not isinstance(symbol, str) or not symbol or symbol in symbols):
            raise AlpacaTransportRefused('Alpaca asset identity is duplicate or missing')
        ids.add(sid)
        symbols.add(symbol)
        if (asset.get('class') == 'us_equity' and asset.get('status') == 'active'
                and asset.get('tradable') is True and asset.get('exchange') != 'OTC'):
            result.append({'asset_id': sid, 'ticker': symbol, 'name': asset.get('name') or '',
                           'exchange': asset.get('exchange')})
    return sorted(result, key=lambda item: item['ticker'])


def job(asset):
    # Alpaca dot class separators correspond to FIGI slash class separators.
    # No symbol suffix determines eligibility or identity.
    return {'idType': 'TICKER', 'idValue': asset['ticker'].replace('.', '/'),
            'exchCode': 'US', 'marketSecDes': 'Equity', 'includeUnlistedEquities': False}


def listing_identity(asset):
    """Fields affecting mapping and prices; a display name is not identity."""
    return {field: asset[field] for field in ('asset_id', 'ticker', 'exchange')}


def reuse_classifications(assets, *, previous_assets, observations):
    """Rebind cosmetic metadata without refreshing the provider observation age.

    Full capture hashes remain the persisted keys. Only an exact listing
    identity can inherit the original mapping response and observation day.
    """
    prior = {digest(listing_identity(asset)): observations.get(digest(asset))
             for asset in previous_assets}
    return {digest(asset): prior[digest(listing_identity(asset))]
            for asset in assets if prior.get(digest(listing_identity(asset))) is not None}


def classify(asset, response):
    if not isinstance(response, dict):
        raise AlpacaTransportRefused('OpenFIGI mapping result is not an object')
    if 'error' in response:
        raise AlpacaTransportUnavailable('OpenFIGI mapping job returned an error')
    rows = response.get('data')
    if rows is None and isinstance(response.get('warning'), str):
        return None, 'no_mapping'
    if not isinstance(rows, list) or not rows:
        raise AlpacaTransportRefused('OpenFIGI mapping result has invalid coverage')
    identities = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get('marketSector') != 'Equity'
                or row.get('exchCode') != 'US' or row.get('ticker') != job(asset)['idValue']
                or not row.get('compositeFIGI') or not row.get('shareClassFIGI')
                or not row.get('securityType') or not row.get('securityType2')):
            return None, 'incomplete_or_foreign_mapping'
        identities.add((row['compositeFIGI'], row['shareClassFIGI'],
                        row['securityType'], row['securityType2']))
    if len(identities) != 1:
        return None, 'ambiguous_mapping'
    composite, share, kind, broad = identities.pop()
    if ALLOWED_TYPES.get(kind) != broad:
        return None, 'non_ordinary_equity'
    return {**asset, 'composite_figi': composite, 'share_class_figi': share,
            'security_type': kind, 'security_type2': broad}, None


def select_assets(assets, observations):
    selected, reasons = [], Counter()
    for asset in assets:
        key = digest(asset)
        if key not in observations:
            raise AlpacaTransportRefused('OpenFIGI classification coverage is incomplete')
        item, reason = classify(asset, observations[key]['response'])
        if item is None:
            reasons[reason] += 1
        else:
            selected.append(item)
    if not selected:
        raise AlpacaTransportRefused('OpenFIGI admitted no ordinary-equity candidates')
    return selected, {'policy': POLICY, 'inventory': len(assets), 'selected': len(selected),
                      'excluded': dict(sorted(reasons.items()))}


class Client:
    def __init__(self, *, opener=None, sleeper=time.sleep, monotonic=time.monotonic):
        self.opener = opener or build_opener(_NoRedirect())
        self.sleep, self.monotonic, self.last = sleeper, monotonic, None
        self.api_key = os.environ.get('OPENFIGI_API_KEY', '').strip()
        self.batch_size = 100 if self.api_key else 10

    def mapping(self, assets):
        if not 1 <= len(assets) <= self.batch_size:
            raise AlpacaTransportRefused('OpenFIGI mapping batch exceeds the reviewed bound')
        body = json.dumps([job(asset) for asset in assets]).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-OPENFIGI-APIKEY'] = self.api_key
        for attempt in range(4):
            rolling_work.checkpoint()
            interval = 0.3 if self.api_key else 2.5
            if self.last is not None:
                self.sleep(max(0, interval - (self.monotonic() - self.last)))
            self.last = self.monotonic()
            try:
                with self.opener.open(Request(ENDPOINT, data=body, headers=headers,
                                             method='POST'), timeout=45) as response:
                    if response.status != 200:
                        raise AlpacaTransportRefused('OpenFIGI returned a non-200 response')
                    raw = response.read(2 * 1024 * 1024 + 1)
                    if len(raw) > 2 * 1024 * 1024:
                        raise AlpacaTransportRefused('OpenFIGI mapping response exceeds size bound')
                    try:
                        values = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise AlpacaTransportRefused('OpenFIGI response is invalid JSON') from None
                    if not isinstance(values, list) or len(values) != len(assets):
                        raise AlpacaTransportRefused('OpenFIGI mapping response count changed')
                    return values, {'endpoint': ENDPOINT, 'request_sha256': hashlib.sha256(body).hexdigest(),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                        'observed_at': datetime.now(timezone.utc).isoformat()}
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504):
                    raise AlpacaTransportRefused('OpenFIGI refused HTTP '+str(exc.code)) from None
                delay = 60 if exc.code == 429 else min(2 ** attempt, 8)
            except (URLError, TimeoutError, OSError):
                delay = min(2 ** attempt, 8)
            if attempt < 3:
                self.sleep(delay)
        raise AlpacaTransportUnavailable('OpenFIGI exhausted bounded retries')


def reference_row(asset, **kwargs):
    first, last = kwargs['first_session'], kwargs['last_session']
    if not first or first > last:
        raise AlpacaTransportRefused('Alpaca listing observation interval is invalid')
    # Retain the canonical category spelling of already reviewed input schemas.
    # Eligibility comes from typed FIGI mapping; no directory lookup is involved.
    category = ('Alpaca Action Unresolved' if kwargs.get('action_unresolved')
                else 'Nasdaq Non-ETF Common Stock Candidate')
    return {'table': 'SEP', 'permaticker': asset['asset_id'], 'ticker': asset['ticker'],
            'category': category, 'relatedtickers': None, 'firstpricedate': first,
            'lastpricedate': last, 'sector': None, 'isdelisted': 'N'}
