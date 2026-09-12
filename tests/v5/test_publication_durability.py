"""PostgreSQL proof of publication visibility and forward listing authority."""
from dataclasses import replace

from sentinel.core.production import load_signal_basis_anchors
from sentinel.feed import universe
from tests.sentinel.test_feed_universe import conn, pg
from tests.v5.test_publication_regressions import metadata_row, prior_book, step


def test_postgres_forward_execution_identity(conn):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO feed_universe_current '
            '(permaticker,ticker,first_price_date,last_price_date,is_delisted,'
            'is_delisted_snapshot_date,snapshot_date) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            metadata_row('SEC-AAA', 'AAA'))
    conn.commit()
    assert universe.load_resolver(conn).resolve('AAA', '2026-08-12') is None
    assert universe.load_resolver(conn, execution_session='2026-08-12').resolve('AAA', '2026-08-12') == 'SEC-AAA'
    with conn.cursor() as cur:
        cur.execute("UPDATE feed_universe_current SET is_delisted=true")
    conn.commit()
    assert universe.load_resolver(conn, execution_session='2026-08-12').resolve('AAA', '2026-08-12') is None


def test_postgres_anchor_is_prior_visible_same_security_and_drives_transition(conn):
    prior, pub = prior_book()
    previous = pub.signal_basis_anchors['A'].session
    with conn.cursor() as cur:
        # NULL ownership is the existing readable legacy source authority.
        cur.execute('INSERT INTO sentinel_bars '
            '(security_id,ticker,session,close_signal,close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            ('A','A',previous,50.,100.,100.,1e6,1.,0.))
        cur.execute('INSERT INTO sentinel_bars '
            '(security_id,ticker,session,close_signal,close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            ('A','A',pub.session,50.,50.,50.,2e6,2.,0.))
        cur.execute('INSERT INTO sentinel_bars '
            '(security_id,ticker,session,close_signal,close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            ('OTHER','A',previous,999.,999.,999.,1e6,1.,0.))
    conn.commit()
    anchors = load_signal_basis_anchors(conn, session=pub.session, security_ids=('A',))
    assert set(anchors) == {'A'}
    assert anchors['A'].session == previous
    assert anchors['A'].raw_close == 100.
    assert anchors['A'].signal_close == 50.
    actual = step(prior, replace(pub, signal_basis_anchors=anchors))
    assert actual.pending == []
    assert actual.shadow_nav_history[-1] == 100000.
    assert actual.last_evidence['recent_leadership'] == {'recent_r20':0.,'recent_r40':0.}
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_bars SET last_written_run_id="
                    "'00000000-0000-0000-0000-000000000001' "
                    "WHERE security_id='A' AND session=%s", (previous,))
    conn.commit()
    assert load_signal_basis_anchors(conn, session=pub.session, security_ids=('A',)) == {}
