"""Pure physical-to-logical candidate read contract and exact price domains."""

_BAR_VIEW = """CREATE OR REPLACE VIEW sentinel_candidate_bars AS
SELECT candidate_id,security_id,session,ticker,close_signal,close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share
FROM sentinel_snapshot_bars
UNION ALL
SELECT r.candidate_id,p.security_id,r.session,p.ticker,p.close_signal,p.close_unadjusted,p.open_unadjusted,p.volume,p.split_ratio,p.dividend_per_share
FROM sentinel_candidate_blocks r JOIN sentinel_normalized_blocks b USING(block_sha256)
CROSS JOIN LATERAL jsonb_to_recordset((b.canonical_payload::jsonb)->'rows') AS p(
 security_id text,session date,ticker text,close_signal double precision,close_unadjusted double precision,
 open_unadjusted double precision,volume double precision,split_ratio double precision,dividend_per_share double precision)
WHERE r.kind='BARS'"""


_BENCHMARK_VIEW = """CREATE OR REPLACE VIEW sentinel_candidate_benchmarks AS
SELECT candidate_id,session,spy_total_return,bil_open_signal,bil_close_signal,bil_close_adjusted,bil_close_unadjusted
FROM sentinel_snapshot_benchmarks
UNION ALL
SELECT r.candidate_id,r.session,p.spy_total_return,p.bil_open_signal,p.bil_close_signal,p.bil_close_adjusted,p.bil_close_unadjusted
FROM sentinel_candidate_blocks r JOIN sentinel_normalized_blocks b USING(block_sha256)
CROSS JOIN LATERAL jsonb_to_recordset((b.canonical_payload::jsonb)->'rows') AS p(
 session date,spy_total_return double precision,bil_open_signal double precision,bil_close_signal double precision,
 bil_close_adjusted double precision,bil_close_unadjusted double precision)
WHERE r.kind='BENCHMARKS'"""



def table_name(kind, *, shared):
    if kind not in ('BARS','BENCHMARKS'):
        raise ValueError('NORMALIZED_LAYOUT_KIND_INVALID')
    return ('sentinel_candidate_' if shared else 'sentinel_snapshot_')+kind.lower()


def route(statement, *, shared):
    if not shared:
        return statement
    return statement.replace('sentinel_snapshot_benchmarks','sentinel_candidate_benchmarks').replace(
        'sentinel_snapshot_bars','sentinel_candidate_bars')
