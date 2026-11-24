"""Typed wait for newly closed Alpaca facts that cannot yet be certified."""


class AlpacaSourcePending(RuntimeError):
    """A missing current observation may be retried within the original job."""

    def __init__(self, reason: str, *, symbol: str | None = None):
        if reason not in {
            'ALPACA_IDENTITY_ACTION_PENDING',
            'ALPACA_MERGER_TERMS_PENDING',
            'ALPACA_ACTION_REOBSERVATION_PENDING',
            'ALPACA_BENCHMARK_CLOSE_PENDING',
        }:
            raise ValueError('unknown Alpaca source wait reason')
        self.reason, self.symbol = reason, symbol
        super().__init__(reason + (':' + symbol if symbol is not None else ''))
