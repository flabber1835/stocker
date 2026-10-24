"""One owner-approved local PAPER execution-policy transition, not a wildcard."""
from sentinel.authority import canonical_sha256

SIGNED_PREDECESSOR = "7f94cb127d4abac3001ffbe3de7d794775fbaae95a9406708eef990524f7c437"
PERSISTENT_SHARE_STRATEGY = "caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095"


def allows_execution_transition(signed_strategy_sha256: str, strategy_identity: dict) -> bool:
    """The caller must already verify explicit local PAPER/runtime ownership."""
    return (signed_strategy_sha256 == SIGNED_PREDECESSOR
            and canonical_sha256(strategy_identity) == PERSISTENT_SHARE_STRATEGY)
