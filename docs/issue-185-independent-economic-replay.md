# Issue #185 — independent economic replay evidence

This artifact records an independent raw-Sharadar before/after replay of the
liquidity-domain correction. It is **economic evidence**, not a substitute for
the repository's authoritative full-retention Wealth Core chain rehearsal.

## Controlled change

The replay uses the retained canonical Sentinel 1.1 raw-Sharadar implementation
and its terminal-order and issuer-identity corrections. All strategy, accounting,
corporate-action, next-open execution, cost, controller and issuer rules are held
fixed. The only experimental switch is the liquidity input:

```text
before / invalid    dollar_volume = closeunadj * volume
corrected           dollar_volume = close * volume
```

Equivalently, the corrected Wealth Core adapter consumes
`raw_compatible_volume = volume * close / closeunadj`, so
`closeunadj * raw_compatible_volume == close * volume`.

The measurement window is 2006-07-31 through 2026-07-31, with the same 1998
warm-up history used by the retained canonical replay. Sharpe below uses simple
daily returns, sample standard deviation, zero risk-free rate, and sqrt(252)
annualization.

## Baseline reproduction check

Before changing liquidity, the independent replay reproduces the retained
canonical lineage exactly at the headline level:

```text
CAGR             22.09461850%
max drawdown    -21.96309788%
ending multiple  54.195852100x
Sharpe             1.166905829
buy events       462
```

This is important: the comparison is not against an approximate reconstruction
that already changed terminal or issuer behavior.

## Trailing-window results

| Window | Liquidity | CAGR | Max DD | Sharpe | Ending multiple | Trade events |
|---|---|---:|---:|---:|---:|---:|
| 5y | old | 26.4975% | -20.9254% | 1.2276 | 3.2344x | 270 |
| 5y | corrected | 26.4756% | -21.7132% | 1.2357 | 3.2316x | 272 |
| 10y | old | 26.1316% | -21.9631% | 1.2449 | 10.1823x | 507 |
| 10y | corrected | 26.7506% | -22.5980% | 1.2637 | 10.6930x | 523 |
| 15y | old | 21.5514% | -21.9631% | 1.1431 | 18.6745x | 650 |
| 15y | corrected | 21.0529% | -22.5980% | 1.1185 | 17.5582x | 674 |
| 20y | old | 22.0946% | -21.9631% | 1.1669 | 54.1959x | 927 |
| 20y | corrected | 20.2884% | -39.9295% | 1.0565 | 40.2258x | 959 |

The trailing 10-year corrected result is slightly better on CAGR/Sharpe than the
old result; the major adverse delta is concentrated in earlier history.

## Trade-path differences

Trade identity here is `(session, side, ticker, reason)`; quantity changes on an
otherwise identical identity are not counted as a different identity in these
figures.

| Window | Old-only trade identities | Corrected-only trade identities |
|---|---:|---:|
| 5y | 31 | 33 |
| 10y | 95 | 111 |
| 15y | 138 | 162 |
| 20y | 269 | 301 |

Over the 20-year measurement window, event counts move from 462 buys / 464 sells
/ 1 terminal settlement to 477 buys / 481 sells / 1 terminal settlement.

## Eligible-universe impact

Across the 5,032 measured sessions, the final Wealth Core eligibility membership
set differs on 5,010 sessions after all liquidity/history/category/price gates
used by this standalone path are applied.

```text
old-only eligible security-sessions          199,596
corrected-only eligible security-sessions    229,145
symmetric membership differences             428,741
distinct securities affected                   1,406
```

The largest one-session membership delta in this replay is 2021-02-22:

```text
old eligible          1,816
corrected eligible    1,971
old-only                 18
corrected-only           173
```

This confirms that #185 changes the candidate population, not only reported
liquidity diagnostics.

## Why the 20-year drawdown changes so much

The corrected stock-selection path also changes Sentinel's controller evidence
because the controller observes the resulting Wealth Core book. The clearest
historical divergence is 2008:

```text
old path risk-off open        2008-07-03
corrected path risk-off open  2008-10-06
```

Calendar-2008 results from the same replay:

```text
old          return +11.99%, max DD -12.15%, Sharpe +0.647
corrected    return -14.34%, max DD -31.07%, Sharpe -0.422
```

The full corrected max-drawdown trough is 2009-03-05. This is why the 20-year
max drawdown deteriorates even though recent windows remain close.

For additional context, 2022 improves modestly under corrected liquidity in this
replay: calendar return changes from -11.16% to -9.09% and calendar max drawdown
from -14.22% to -12.30%.

## Direct architecture controls on the corrected shadow

As a partial champion-selection check, the same corrected Wealth Core shadow was
run through the current Sentinel 1.1 controller, its immediate Sentinel 1.0
parent, and no controller at all. Parent NAV is reconstructed with the same
next-open allocation-change accounting and BIL sleeve as Sentinel 1.1.

| Corrected architecture | 20y CAGR | Max DD | Sharpe | Ending multiple |
|---|---:|---:|---:|---:|
| Sentinel 1.1 current | **20.2884%** | **-39.9295%** | **1.0565** | **40.2258x** |
| Sentinel 1.0 parent | 20.2367% | -39.9295% | 1.0464 | 39.8817x |
| Wealth Core shadow | 18.3971% | -42.9168% | 0.9168 | 29.2991x |

So the corrected current strategy remains ahead of both its direct parent and
unprotected Wealth Core on CAGR and Sharpe in this independent replay. The 1.1
increment over its parent is small, consistent with the prior research finding
that the recovery ramp is mainly a tail-shaping rule rather than independently
proven return alpha.

This three-path check is **not** the full retained eight-architecture CSCV
selection process. It narrows the risk that the correction trivially dethroned
1.1 in favor of its parent or plain Wealth Core, but the full finalist rerun is
still required before making the stronger champion claim.

## Interpretation / certification consequence

The prior ~22.09% 20-year CAGR is not valid evidence for the corrected Sharadar
liquidity contract. The corrected independent result is ~20.29% with materially
worse historical maximum drawdown. Expected hashes must therefore not be blindly
repinned.

This evidence does **not** establish that a different strategy should replace
the current champion. It deliberately changes no strategy rule. The direct
three-path check above still favors Sentinel 1.1, but champion status remains a
separate acceptance item: rerun the same complete selection procedure that
originally chose the strategy on corrected liquidity before #185 is closed.

The repository's authoritative full-retention before/after rehearsal comparator
remains the final parity/certification gate. If that result disagrees materially
with this independent replay, the disagreement itself is a blocker requiring
forensic resolution rather than averaging or choosing the preferred number.
