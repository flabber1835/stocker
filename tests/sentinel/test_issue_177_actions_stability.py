from __future__ import annotations

import pytest

from sentinel.feed import authority, ingest, publication, sharadar
from tests.sentinel.test_actions_wiring import (  # noqa: F401
    TODAY,
    conn,
    pg,
    sess,
    vendor,
)


def _publication_version(conn):
    current = publication.current(conn)
    return None if current is None else current.version


def _active_action_count(conn, *, ticker: str, day: str, action: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_active_actions"
            " WHERE ticker=%s AND session=%s AND action=%s",
            (ticker, day, action))
        return int(cur.fetchone()[0])


def test_partial_actions_fetch_cannot_remove_prior_or_publish_candidate(conn):
    # Keep the known action inside the daily ACTIONS window so an empty first
    # traversal really does stage a REMOVED candidate. The assertion below is
    # that this candidate cannot become authoritative, not that append-only
    # evidence of the failed observation must be erased.
    day = sess()[-5]
    prior = {
        "ticker": "AAA", "date": day, "action": "dividend", "value": 0.25,
        "name": "ordinary dividend", "contraticker": None, "contraname": None,
    }
    ingest.seed(
        conn, date_from="2024-11-01", date_to=TODAY,
        fetch=vendor(actions=[prior]))

    before_version = _publication_version(conn)
    assert _active_action_count(
        conn, ticker="AAA", day=day, action="dividend") == 1

    calls = 0
    stable = vendor(actions=[prior])

    def moving_actions(table, params=None, **kwargs):
        nonlocal calls
        if table == sharadar.ACTIONS:
            calls += 1
            # The first complete traversal catches the vendor mid-publication;
            # the second sees the previously known action again.
            return [] if calls == 1 else [prior]
        return stable(table, params, **kwargs)

    with pytest.raises(authority.VendorPublicationUnstable):
        ingest.daily(conn, fetch=moving_actions, today=TODAY)

    assert calls == 2
    # The first observation may have staged a REMOVED row in append-only
    # evidence, but without a publication it cannot replace the active action.
    assert _active_action_count(
        conn, ticker="AAA", day=day, action="dividend") == 1
    assert _publication_version(conn) == before_version


def test_terminal_seen_only_after_partial_observation_needs_stable_snapshot(conn):
    day = sess()[-5]
    prior = {
        "ticker": "AAA", "date": day, "action": "dividend", "value": 0.25,
        "name": "ordinary dividend", "contraticker": None, "contraname": None,
    }
    terminal = {
        "ticker": "AAA", "date": sess()[-1], "action": "acquisitionby",
        "value": 500.0, "name": "acquired", "contraticker": "BBB",
        "contraname": "Buyer Inc",
    }
    ingest.seed(
        conn, date_from="2024-11-01", date_to=TODAY,
        fetch=vendor(actions=[prior]))

    calls = 0
    stable_prices = vendor(actions=[prior, terminal])

    def publication_moves(table, params=None, **kwargs):
        nonlocal calls
        if table == sharadar.ACTIONS:
            calls += 1
            return [prior] if calls == 1 else [prior, terminal]
        return stable_prices(table, params, **kwargs)

    with pytest.raises(authority.VendorPublicationUnstable):
        ingest.daily(conn, fetch=publication_moves, today=TODAY)

    assert _active_action_count(
        conn, ticker="AAA", day=terminal["date"], action="acquisitionby") == 0

    # A later attempt sees the complete key-set twice. Only now may the terminal
    # row enter the candidate lifecycle and participate in publication.
    ingest.daily(conn, fetch=stable_prices, today=TODAY)
    assert _active_action_count(
        conn, ticker="AAA", day=terminal["date"], action="acquisitionby") == 1
