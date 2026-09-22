"""Predeclared price paths: registration commit 48da5169."""
import math

EXTRA = ("rebound_relapse", "owned_recovery", "leaders_recovery", "concentration",
         "stationary_volatility", "repeated_shocks")


def factors(original, case, day, sid, held):
    if case not in EXTRA:
        return original(case, day, sid, held)
    equity = market = 1.
    if case in ("rebound_relapse", "owned_recovery", "leaders_recovery") and day == 0:
        return .82, .92
    if case == "rebound_relapse":
        if 15 <= day <= 34:
            equity, market = 1.012, 1.004
        elif day == 45:
            equity, market = .82, .92
    elif case in ("owned_recovery", "leaders_recovery") and 15 <= day <= 74:
        if case == "owned_recovery":
            equity = 1.008 if sid in held else .998
        else:
            equity = .999 if sid in held else 1.008
    elif case == "concentration" and sid in sorted(held)[:2]:
        if 0 <= day <= 39:
            equity = 1.025
        elif 40 <= day <= 49:
            equity = .94
    elif case == "stationary_volatility":
        equity, market = math.exp(.025 if day % 2 == 0 else -.025), math.exp(.015 if day % 2 == 0 else -.015)
    elif case == "repeated_shocks":
        if day in (0, 30, 60):
            equity, market = .86, .94
        elif 10 <= day <= 24 or 40 <= day <= 54 or 70 <= day <= 94:
            equity = 1.006
    return equity, market
