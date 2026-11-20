"""Route the four reviewed provider requests to the isolated synthetic server."""
import ipaddress
import os
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request

from sentinel.feed import alpaca_transport, openfigi, publisher_pipeline
from sentinel.feed.alpaca_source import AlpacaSource


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class FixtureTransport:
    def __init__(self, address):
        parts = urlsplit(address)
        if parts.scheme != 'http' or parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise ValueError('invalid isolated fixture address')
        if parts.hostname != 'provider' and not ipaddress.ip_address(parts.hostname).is_private:
            raise ValueError('an isolated fixture address is required')
        self.address = address
        self.local = build_opener(ProxyHandler({}), NoRedirects())

    def open(self, request, timeout):
        if (os.environ.get('ALPACA_API_KEY') != 'fixture-data-id' or
                os.environ.get('ALPACA_SECRET_KEY') != 'fixture-data-secret' or
                os.environ.get('OPENFIGI_API_KEY', '') not in ('', 'fixture-mapping')):
            raise ValueError('only synthetic credentials are permitted')
        uri = urlsplit(request.full_url)
        endpoint = uri._replace(query='', fragment='').geturl()
        allowed = ({openfigi.ENDPOINT} if request.get_method() == 'POST' else
                   alpaca_transport.ALLOWED if request.get_method() == 'GET' else set())
        if endpoint not in allowed:
            raise ValueError('request is outside the fixture market-data boundary')
        # No production credential headers or proxy configuration cross this boundary.
        target = self.address + uri.path + ('?' + uri.query if uri.query else '')
        return self.local.open(Request(target, data=request.data, method=request.get_method(),
                               headers={'Content-Type': 'application/json'}), timeout=timeout)


def market_source(address, window, conn, lease, *, verify_during_coverage=False):
    local = FixtureTransport(address)
    return AlpacaSource(window, conn, lease, client=alpaca_transport.Client(opener=local),
        classifier=openfigi.Client(opener=local), verify_during_coverage=verify_during_coverage)


def install_fixture(address):
    def source(window, conn, lease, *, corrections, verify_during_coverage):
        return market_source(address, window, conn, lease, verify_during_coverage=verify_during_coverage)
    publisher_pipeline._operational_source = source
