"""Choose the legal denomination without changing an attempted command."""
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import json

from sentinel.execution import fractional_progress, journal
from sentinel.execution.contract import BrokerAssetRules, Side
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.market_buy_policy import MARKET_BUY_BUFFER_BPS
from sentinel.execution.numeric import exact_decimal
from sentinel.execution.opening_prices import QUOTE_SOURCE, RegularQuotes
from sentinel.execution.states import CommandState as S


async def choose(broker, *, conn, deployment, projection, delta, instrument):
    """Return the concrete amount and any explicit unsellable share residual."""
    try:
        rules = await broker.asset_rules(instrument=instrument)
        if not isinstance(rules, BrokerAssetRules) or rules.instrument != instrument:
            raise ValueError("asset rules do not describe the selected native instrument")
    except Exception as exc:
        raise OrderEvidenceNotReady(f"current fractional eligibility unavailable: {exc}") from exc
    evidence = json.dumps({"fractionable": rules.fractionable,
        "asset_id": instrument.broker_id, "observed_at": rules.observed_at.isoformat()}, sort_keys=True)
    delta = replace(delta, detail="asset trading rules: " + evidence)
    residual = None
    if delta.side is Side.SELL:
        if not rules.fractionable and delta.quantity != delta.quantity.to_integral_value():
            whole = Decimal(Fraction(delta.quantity) // 1)
            residual = "FRACTIONAL_SELL_RESIDUAL: " + str(exact_decimal(Fraction(delta.quantity) - Fraction(whole)))
            if whole == 0:
                raise OrderEvidenceNotReady(residual)
            delta = replace(delta, remaining=whole.copy_negate(), desired=exact_decimal(Fraction(delta.held) - Fraction(whole)))
        return delta, residual
    if delta.notional is None or rules.fractionable:
        return delta, None
    attempted = [c for c in journal.load_commands(conn, deployment, plan_id=projection.plan_id,
                 security_id=delta.security_id) if c.state not in {S.PLANNED, S.SUPERSEDED}]
    if attempted:
        raise OrderEvidenceNotReady("fractional eligibility changed after an attempted dollar purchase; retain its obligation")
    quote = await broker.opening_prices(session=projection.through_session,
        instruments={delta.security_id: instrument})
    if (not isinstance(quote, RegularQuotes) or quote.source != QUOTE_SOURCE
            or quote.session != projection.through_session
            or quote.broker_ids.get(delta.security_id) != instrument.broker_id
            or quote.symbols.get(delta.security_id) != instrument.symbol
            or delta.security_id not in quote.prices):
        raise OrderEvidenceNotReady("whole-share fallback requires a fresh native IEX quote")
    unit = Fraction(quote.prices[delta.security_id]) * Fraction(10000 + MARKET_BUY_BUFFER_BPS, 10000)
    quantity = Decimal(Fraction(delta.notional) // unit)
    if quantity == 0:
        raise OrderEvidenceNotReady("BELOW_WHOLE_SHARE: allocation cannot fund one fallback share")
    return replace(delta, notional=None, remaining=quantity,
                   desired=exact_decimal(Fraction(delta.held) + Fraction(quantity))), None
