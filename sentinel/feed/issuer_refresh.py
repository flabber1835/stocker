"""Bounded SEC acquisition outside execution; no database or broker access."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import hashlib
from html.parser import HTMLParser
import re
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from sentinel.feed import issuer_reference as reference

CONTACT_ENV = 'SENTINEL_SEC_CONTACT_EMAIL'
PETROBRAS_URL = 'https://www.sec.gov/Archives/edgar/data/1119639/000129281426002168/ex2-4.htm'
CONTACT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"


def declared_user_agent(email):
    if (not isinstance(email, str) or len(email) > 254
            or re.fullmatch(CONTACT_PATTERN, email, flags=re.ASCII) is None
            or '..' in email.split('@')[0] or email.split('@')[0].endswith('.')):
        raise ValueError('SEC contact email is missing or invalid')
    return 'Sentinel-issuer-reference/1.0 (' + email + ')'


def symbol_key(symbol):
    return symbol[:-2] + '-' + symbol[-1] if re.fullmatch(r'[A-Z0-9]+[.-][A-Z]', symbol) else symbol


def quarantine_observation(rows, anchors, quarantined):
    """First observed identities survive disappearance and provider contradictions."""
    if len(rows) > 30000 or len(anchors) > 50000 or len(quarantined) > 30000:
        raise ValueError('SEC association catalog exceeds its bound')
    blocked = set(quarantined)
    prior, families = {}, defaultdict(set)
    for row in anchors:
        row = reference.IssuerAssociation.model_validate(row)
        key = row.ticker, row.exchange
        if key in prior and prior[key].cik != row.cik:
            blocked.add(symbol_key(row.ticker))
        prior.setdefault(key, row)
        families[symbol_key(row.ticker)].add(row.cik)
    seen, forms = set(), defaultdict(set)
    for row in rows:
        key = row.ticker, row.exchange
        triple = row.ticker, row.exchange, row.cik
        if triple in seen:
            raise ValueError('SEC source repeated an association')
        seen.add(triple)
        family = symbol_key(row.ticker)
        families[family].add(row.cik)
        forms[family, row.exchange].add(row.ticker)
        if key in prior and prior[key].cik != row.cik:
            blocked.add(family)
    blocked.update(family for family, ciks in families.items() if len(ciks) != 1)
    blocked.update(family for (family, _exchange), names in forms.items() if len(names) != 1)
    for row in rows:
        if symbol_key(row.ticker) not in blocked:
            prior.setdefault((row.ticker, row.exchange), row)
    order = lambda row: (row.ticker, row.exchange or '', row.cik)
    return (tuple(sorted((row for row in rows if symbol_key(row.ticker) not in blocked), key=order)),
            tuple(sorted(prior.values(), key=order)), tuple(sorted(blocked)))


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def disclosure_proof(raw, *, previous, now):
    if (len(raw) > reference.MAX_RESPONSE_BYTES or previous.source_url != PETROBRAS_URL
            or previous.cik != '0001119639' or previous.exchange != 'NYSE'
            or set(previous.symbols) != {'PBR', 'PBR-A'}):
        raise ValueError('unsupported SEC disclosure relationship')
    parser = _VisibleText()
    parser.feed(raw.decode('utf-8'))
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).casefold()
    facts = (
        r'common and preferred shares.{0,100}pbr/pbra.{0,40}nyse',
        r'american depositary shares.{0,100}each representing two of our common or preferred shares',
        r'not convertible',
    )
    if any(re.search(fact, text) is None for fact in facts):
        raise ValueError('SEC disclosure lacks reviewed positive ADR facts')
    statement = ('Petrobras PBR/PBRA ADSs each represent two common or preferred shares of '
                 'operating issuer CIK0001119639; the underlying classes are not convertible. '
                 'Direct SEC disclosure body SHA256: ' + hashlib.sha256(raw).hexdigest())
    return reference.UnderlyingIssuerCorroboration.create(
        cik=previous.cik, symbols=previous.symbols, exchange=previous.exchange,
        source_url=previous.source_url, observed_at_utc=now, statement=statement,
        observation_time_basis='CONSERVATIVE_PRIOR_UTC_BOUND')


def refresh(snapshot, *, email, anchors, quarantined=(), now=None, opener=None):
    """At most two official reads. No redirects, proxy inheritance, retries or sleeps."""
    now = reference._now(now)
    user_agent = declared_user_agent(email)
    client = opener or build_opener(ProxyHandler({}), reference._NoRedirect())
    result = reference.refresh_snapshot(snapshot, now=now, opener=client, timeout=4,
        user_agent=user_agent, anchor_rows=anchors, quarantined_symbols=quarantined)
    if result.status != 'REFRESHED':
        return result
    proofs = list(snapshot.corroborations)
    supported = [i for i, proof in enumerate(proofs) if proof.source_url == PETROBRAS_URL
                 and proof.cik == '0001119639' and set(proof.symbols) == {'PBR', 'PBR-A'}]
    reason = result.reason
    if len(supported) == 1:
        try:
            request = Request(PETROBRAS_URL, headers={'User-Agent': user_agent, 'Accept': 'text/html'})
            with client.open(request, timeout=4) as response:
                if response.status != 200:
                    raise ValueError('SEC disclosure response not successful')
                raw = response.read(reference.MAX_RESPONSE_BYTES + 1)
            proofs[supported[0]] = disclosure_proof(raw, previous=proofs[supported[0]], now=now)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError):
            reason = 'sec_source_observed_adr_refresh_unavailable'
    current = result.snapshot
    updated = reference.IssuerReferenceSnapshot.create(observed_at_utc=now,
        associations=current.associations, source_method='DIRECT_HTTP_BODY',
        coverage=current.provenance.coverage, raw_http_sha256=current.provenance.raw_http_sha256,
        corroborations=proofs)
    return result.model_copy(update={'snapshot': updated, 'reason': reason,
                                    'retry_after_seconds': 3600 if reason.endswith('unavailable') else 86400})


def semantic_digest(snapshot):
    return reference._digest({'associations': snapshot.provenance.content_sha256,
        'coverage': snapshot.provenance.coverage,
        'corroborations': [proof.model_dump(mode='json', exclude={
            'observed_at_utc', 'expires_at_utc', 'observation_time_basis', 'content_sha256'})
            for proof in snapshot.corroborations]})


def needs_version(previous, current, now):
    expiry = min([previous.provenance.expires_at_utc]
                 + [proof.expires_at_utc for proof in previous.corroborations])
    return semantic_digest(previous) != semantic_digest(current) or expiry <= now + timedelta(days=7)
