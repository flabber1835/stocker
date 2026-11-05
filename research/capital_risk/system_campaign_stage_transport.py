"""Host-only release transfer fallback; immutable stage owns every byte check."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'flabber1835/stocker'
RELEASE = 'research-capital-risk-inputs-20261027'
STAGE_SHA = '2ab2596762e059c6178361b45295739a14973992701ca95ee0e77d34b534f163'
STAGE_REQUEST_SHA = '68e416c622427fa97d4e405e046955ff341c1ce98b33c4c74a499fce366d1e7f'
TRANSIENT = {408, 500, 502, 503, 504}
REDIRECT_HOSTS = {'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
API_ROOT = 'https://api.github.com/repos/' + REPOSITORY
PUBLIC_ROOT = 'https://github.com/' + REPOSITORY + '/releases/download/' + RELEASE + '/'
METADATA_LIMIT = 2 * 1024 * 1024
MAX_RETRY_AFTER = 5.0
WAIT_BUDGET = 15.0


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def rate_limited(code, headers):
    return code in (403, 429) or headers.get('X-RateLimit-Remaining') == '0'


def transient_open(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, (TimeoutError, ConnectionError))


def declared_parts(request):
    need(request['release'] == RELEASE, 'REFUSED_STAGE_TRANSPORT_RELEASE')
    declared = {}
    for name, spec in request['assets'].items():
        for part in spec.get('parts', [dict(name=name, **spec)]):
            url = PUBLIC_ROOT + part['name']
            need(url not in declared, 'REFUSED_STAGE_TRANSPORT_DUPLICATE_PART')
            declared[url] = dict(part)
    need(0 < len(declared) <= 64, 'REFUSED_STAGE_TRANSPORT_PART_BUDGET')
    return declared


class OpaqueResponse:
    """Delegate bytes unchanged; never expose a signed URL in stream errors."""
    def __init__(self, response):
        self.response = response
        self.headers = response.headers

    def read(self, *args):
        try:
            return self.response.read(*args)
        except Exception:
            raise ValueError('REFUSED_STAGE_TRANSPORT_STREAM_INTERRUPTED') from None

    def close(self):
        self.response.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ReleaseTransfer:
    def __init__(self, request, token, original, *, api_opener=None, sleep=time.sleep,
                 now=lambda: datetime.now(timezone.utc)):
        need(isinstance(token, str) and token and not any(c.isspace() for c in token),
             'REFUSED_STAGE_TRANSPORT_READ_TOKEN')
        self.parts = declared_parts(request)
        self.token, self.original = token, original
        self.api = api_opener or urllib.request.build_opener(NoRedirect())
        self.sleep, self.now = sleep, now
        self.calls = 0
        self.max_calls = 1 + 2 * len(self.parts)
        self.waited = 0.0
        self.seen = set()
        self.assets = None

    def delay(self, headers):
        value = headers.get('Retry-After')
        if value is None:
            return
        try:
            try:
                delay = float(value)
            except ValueError:
                parsed = parsedate_to_datetime(value)
                need(parsed.tzinfo is not None, 'REFUSED_STAGE_TRANSPORT_RETRY_AFTER')
                delay = max(0.0, (parsed - self.now()).total_seconds())
        except (TypeError, ValueError, OverflowError):
            raise ValueError('REFUSED_STAGE_TRANSPORT_RETRY_AFTER') from None
        need(0 <= delay <= MAX_RETRY_AFTER and self.waited + delay <= WAIT_BUDGET,
             'REFUSED_STAGE_TRANSPORT_RETRY_AFTER_BUDGET')
        self.waited += delay
        if delay:
            self.sleep(delay)

    def request(self, url, *, authenticated, accept):
        parsed = urllib.parse.urlsplit(url)
        need(parsed.scheme == 'https' and parsed.username is None and parsed.password is None
             and parsed.port in (None, 443) and not parsed.fragment,
             'REFUSED_STAGE_TRANSPORT_URL')
        if authenticated:
            need(parsed.netloc == 'api.github.com' and url.startswith(API_ROOT + '/'),
                 'REFUSED_STAGE_TRANSPORT_CREDENTIAL_ORIGIN')
        else:
            need(parsed.hostname in REDIRECT_HOSTS and parsed.path.startswith('/'),
                 'REFUSED_STAGE_TRANSPORT_REDIRECT_ORIGIN')
        need(self.calls < self.max_calls, 'REFUSED_STAGE_TRANSPORT_CALL_BUDGET')
        self.calls += 1
        headers = {'Accept': accept, 'User-Agent': 'stocker-frozen-stage-transfer',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            response = self.api.open(req, timeout=60)
        except urllib.error.HTTPError as error:
            code, reply = error.code, error.headers
            if rate_limited(code, reply):
                error.close()
                raise ValueError('REFUSED_STAGE_TRANSPORT_RATE_LIMIT_HTTP_' + str(code)) from None
            if code == 302 and authenticated and accept == 'application/octet-stream':
                location = reply.get('Location')
                error.close()
                need(isinstance(location, str) and location, 'REFUSED_STAGE_TRANSPORT_REDIRECT_LOCATION')
                return self.request(location, authenticated=False, accept=accept)
            error.close()
            raise ValueError('REFUSED_STAGE_TRANSPORT_API_OPEN_HTTP_' + str(code)) from None
        except (OSError, urllib.error.URLError):
            raise ValueError('REFUSED_STAGE_TRANSPORT_API_OPEN') from None
        if response.status != 200 or response.geturl() != url or rate_limited(response.status, response.headers):
            limited = rate_limited(response.status, response.headers)
            response.close()
            raise ValueError('REFUSED_STAGE_TRANSPORT_RATE_LIMIT' if limited else 'REFUSED_STAGE_TRANSPORT_RESPONSE_OR_REDIRECT')
        return OpaqueResponse(response)

    def metadata(self):
        need(self.assets is None, 'REFUSED_STAGE_TRANSPORT_METADATA_ONCE')
        endpoint = API_ROOT + '/releases/tags/' + RELEASE
        with self.request(endpoint, authenticated=True, accept='application/vnd.github+json') as response:
            raw = response.read(METADATA_LIMIT + 1)
        need(len(raw) <= METADATA_LIMIT, 'REFUSED_STAGE_TRANSPORT_METADATA_SIZE')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError('REFUSED_STAGE_TRANSPORT_METADATA_JSON') from None
        release_id = data.get('id')
        need(type(release_id) is int and release_id > 0 and data.get('tag_name') == RELEASE
             and data.get('url') == API_ROOT + '/releases/' + str(release_id)
             and data.get('html_url') == 'https://github.com/' + REPOSITORY + '/releases/tag/' + RELEASE
             and data.get('assets_url') == API_ROOT + '/releases/' + str(release_id) + '/assets'
             and data.get('draft') is False and isinstance(data.get('assets'), list),
             'REFUSED_STAGE_TRANSPORT_RELEASE_IDENTITY')
        result, ids = {}, set()
        for url, part in self.parts.items():
            matches = [a for a in data['assets'] if isinstance(a, dict) and a.get('name') == part['name']]
            need(len(matches) == 1, 'REFUSED_STAGE_TRANSPORT_UNIQUE_ASSET_NAME')
            asset = matches[0]
            asset_id = asset.get('id')
            need(type(asset_id) is int and asset_id > 0 and asset_id not in ids
                 and type(asset.get('size')) is int and asset['size'] == part['bytes']
                 and asset.get('state') == 'uploaded' and asset.get('browser_download_url') == url
                 and asset.get('url') == API_ROOT + '/releases/assets/' + str(asset_id)
                 and asset.get('digest') in (None, 'sha256:' + part['sha256']),
                 'REFUSED_STAGE_TRANSPORT_ASSET_IDENTITY_SIZE_AND_DIGEST')
            result[url] = asset['url']
            ids.add(asset_id)
        self.assets = result

    def open(self, url, *args, **kwargs):
        if not isinstance(url, str) or url not in self.parts:
            return self.original(url, *args, **kwargs)
        need(not args and kwargs == {'timeout': 60} and url not in self.seen,
             'REFUSED_STAGE_TRANSPORT_EXACT_ORIGINAL_OPEN_ONCE')
        self.seen.add(url)
        if self.assets is not None:
            return self.request(self.assets[url], authenticated=True, accept='application/octet-stream')
        try:
            return OpaqueResponse(self.original(url, *args, **kwargs))
        except (OSError, urllib.error.URLError) as error:
            headers = error.headers if isinstance(error, urllib.error.HTTPError) else {}
            code = error.code if isinstance(error, urllib.error.HTTPError) else None
            if rate_limited(code, headers):
                if isinstance(error, urllib.error.HTTPError):
                    error.close()
                raise ValueError('REFUSED_STAGE_TRANSPORT_RATE_LIMIT') from None
            eligible = transient_open(error)
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            need(eligible, 'REFUSED_STAGE_TRANSPORT_NONTRANSIENT_PUBLIC_OPEN')
            self.delay(headers)
        if self.assets is None:
            self.metadata()
        return self.request(self.assets[url], authenticated=True, accept='application/octet-stream')


@contextmanager
def installed(request, token, **kwargs):
    original = urllib.request.urlopen
    transfer = ReleaseTransfer(request, token, original, **kwargs)
    try:
        urllib.request.urlopen = transfer.open
        yield transfer
    finally:
        urllib.request.urlopen = original
        transfer.token = None


def validate_binding(here, factual, stage_request):
    expected = {Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'stage.py': STAGE_SHA, 'stage-request.json': STAGE_REQUEST_SHA}
    need(all(factual['sources'].get(name) == digest for name, digest in expected.items()),
         'REFUSED_STAGE_TRANSPORT_FACTUAL_SOURCE_BINDING')
    need(hashlib.sha256((here / 'stage.py').read_bytes()).hexdigest() == STAGE_SHA
         and hashlib.sha256(stage_request.read_bytes()).hexdigest() == STAGE_REQUEST_SHA,
         'REFUSED_STAGE_TRANSPORT_IMMUTABLE_STAGE_AND_REQUEST')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--factual-request', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    factual = json.loads(args.factual_request.read_bytes())
    validate_binding(here, factual, args.request)
    import stage
    need(Path(stage.__file__).resolve() == here / 'stage.py', 'REFUSED_STAGE_TRANSPORT_IMPORTED_STAGE_ORIGIN')
    stage.check_context(os.environ)
    request = json.loads(args.request.read_bytes())
    stage.validate_request(request)
    token = os.environ.pop('GH_TOKEN', '')
    original_argv = sys.argv
    try:
        sys.argv = [str(here / 'stage.py'), '--request', str(args.request), '--output', str(args.output)]
        with installed(request, token):
            stage.main()
    finally:
        sys.argv = original_argv
        token = None


if __name__ == '__main__':
    main()
