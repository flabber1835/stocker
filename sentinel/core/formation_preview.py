"""Read-only canonical formation shared by GO and observation admission proofs."""
from sentinel.core.formation import Formation
from sentinel.feed import progress


def run(source, *, capital, strategy, data_version):
    progress.emit('historical_formation', 'started', sessions=0, required_sessions=126)
    formed = Formation(source.plan(capital=capital, strategy=strategy),
                       source.warmup(), data_version=data_version)
    while not formed.complete:
        session = formed.axis[formed.plan.warmup_sessions + formed.count]
        formed.advance(source.session(session, formed.state))
        progress.emit('historical_formation', 'completed' if formed.complete else 'working',
                      sessions=formed.count, required_sessions=126, session=session)
    proof = dict(schema='sentinel.formation-parity/1', policy=formed.plan.metadata_policy,
                 sessions=formed.count, end=formed.plan.end, chain_sha256=formed.chain,
                 state_sha256=formed.state.state_hash, source_sha256=formed.plan.source_sha256)
    return formed.state, formed.warmup_identity, source.session(source.axis[-1], formed.state), proof
