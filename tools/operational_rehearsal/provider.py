"""Serve the shared synthetic Alpaca SIP and OpenFIGI source to the private rehearsal."""
import argparse
from http.server import ThreadingHTTPServer

from tools.acquisition_resources import fixtures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--small', action='store_true')
    small = parser.parse_args().small
    profile = fixtures.Profile(name='joint-small' if small else 'joint-full',
        securities=30 if small else 6000, tickers=100 if small else 30000,
        actions=500 if small else 1000000)
    ThreadingHTTPServer(('0.0.0.0', 8080), fixtures.handler(profile, end='2026-09-23')).serve_forever()


if __name__ == '__main__':
    main()
