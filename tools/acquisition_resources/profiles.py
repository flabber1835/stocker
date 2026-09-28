"""Synthetic dimensions; importing the native controller needs only stdlib."""
SPECS = {
    "smoke": dict(securities=50, tickers=100, actions=500),
    "startup": dict(securities=5000, tickers=22000, actions=250000),
    "daily": dict(securities=5000, tickers=22000, actions=250000, formation=False),
    "stress": dict(securities=10000, tickers=30000, actions=1000000),
}
