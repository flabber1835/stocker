"""Read-only canonical formation shared by GO and observation admission proofs."""
from sentinel.core.formation import Formation


def run(source, *, capital, strategy, data_version):
    formed = Formation(source.plan(capital=capital, strategy=strategy),
                       source.warmup(), data_version=data_version)
    while not formed.complete:
        formed.advance(source.session(formed.axis[252 + formed.count], formed.state))
    proof = dict(schema='sentinel.formation-parity/1', policy=formed.plan.metadata_policy,
                 sessions=formed.count, end=formed.plan.end, chain_sha256=formed.chain,
                 state_sha256=formed.state.state_hash, source_sha256=formed.plan.source_sha256)
    return formed.state, formed.warmup_identity, source.session(source.axis[-1], formed.state), proof
