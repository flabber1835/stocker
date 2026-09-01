"""Source-owned production history requirements shared by readiness and routing."""

# Above Wealth Core's engine-owned 127-close minimum, this is the explicit
# production safety margin used for feature warm-up and operational coherence.
PREFERRED_SESSIONS = 252

# Production's dated SPY sensor tail: 20-session return plus volatility context
# and margin.
REQUIRED_SPY_SESSIONS = 41

__all__ = ["PREFERRED_SESSIONS", "REQUIRED_SPY_SESSIONS"]
