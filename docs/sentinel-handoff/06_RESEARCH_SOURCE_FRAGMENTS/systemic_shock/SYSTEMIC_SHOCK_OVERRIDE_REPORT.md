# Wealth Core systemic-shock override experiment

## Executive result

A breadth-and-speed emergency override materially improved COVID behavior in this historical research screen.

The existing architecture remains:

- Wealth Core with its fixed 30% individual-position trailing stop;
- a continuously running full-exposure shadow book;
- the standard portfolio backstop at a 15.5% shadow-book drawdown;
- 40% Wealth Core / 60% SHY-BIL defensive allocation while the backstop is active.

The new override does not replace that controller. It activates the same 40% equity floor earlier when the internal portfolio structure indicates an unusually fast, broad shock.

## Selected emergency rule

Trigger only when all of these are true:

1. Wealth Core shadow drawdown is at least 10%.
2. At least 85% of current holdings are damaged.
3. No more than 20% of holdings remain green.
4. The shadow lost at least 5% over five sessions or 8% over ten sessions.
5. Damaged breadth increased by at least 40 percentage points over five sessions.

Action:

- reduce live Wealth Core exposure to 40%;
- place the remaining 60% in the SHY/BIL defensive sleeve.

Recovery:

- remain defensive for at least 10 sessions;
- then require three consecutive healthy sessions;
- shadow 20-session return must be positive;
- damaged breadth must be no more than 60%;
- green breadth must be at least 20%;
- rearm only after shadow drawdown recovers above 6%.

The override activated 11 times and was active for 504 of 7,062 sessions, approximately 7.1% of the test history.

## Full-history result

| Strategy | CAGR | Maximum drawdown | Ending wealth |
|---|---:|---:|---:|
| Wealth Core without portfolio protection | 19.97% | -41.16% | 165.8× |
| Current 15.5% backstop | 19.78% | -34.42% | 158.5× |
| **Backstop plus systemic-shock override** | **20.56%** | **-31.61%** | **190.1×** |

The override improved the current controller by:

- 0.78 percentage points of annual CAGR;
- 2.81 percentage points of full-history maximum drawdown;
- 31.6× of ending wealth.

This apparent free improvement must be treated cautiously because the shock thresholds were selected using the same historical period being evaluated.

## Trailing periods through July 31, 2026

| Period | Shock override CAGR | Shock override max DD | Current backstop CAGR | Current max DD | SPY CAGR | SPY max DD |
|---|---:|---:|---:|---:|---:|---:|
| 5 years | 24.71% | -24.48% | 24.71% | -24.48% | 12.83% | -24.50% |
| 10 years | 21.88% | -30.97% | 20.75% | -30.97% | 15.01% | -33.70% |
| 15 years | 18.72% | -30.97% | 17.70% | -30.97% | 14.44% | -33.70% |
| 20 years | 18.31% | -31.14% | 17.69% | -33.06% | 11.26% | -55.20% |

## Official U.S. recession windows

Because the COVID recession lasted only about three months, annualized CAGR is mathematically valid but visually extreme. Total return is included to show the actual investor experience.

| Recession | Strategy | Annualized CAGR | Total return | Maximum drawdown |
|---|---|---:|---:|---:|
| 2001 recession | Shock override | -4.85% | -3.66% | -9.73% |
| 2001 recession | Current backstop | -4.85% | -3.66% | -9.73% |
| 2001 recession | SPY | -10.01% | -7.61% | -25.62% |
| Great Recession | Shock override | -11.08% | -16.89% | -31.14% |
| Great Recession | Current backstop | -8.54% | -13.11% | -33.06% |
| Great Recession | SPY | -24.00% | -35.09% | -53.91% |
| COVID recession | Shock override | -46.38% | -13.80% | -17.72% |
| COVID recession | Current backstop | -62.82% | -21.00% | -24.59% |
| COVID recession | SPY | -35.23% | -9.83% | -33.70% |

## COVID peak-to-trough

Measured from February 19 through March 23, 2020:

| Strategy | Loss / drawdown | Recovery of February 19 high |
|---|---:|---:|
| Shock override | -17.70% | 2020-06-23 |
| Current backstop | -24.57% | 2020-07-02 |
| Wealth Core | -28.49% | 2020-06-30 |
| SPY | -33.70% | 2020-08-10 |

The emergency override reduced the COVID loss from -24.57% to -17.70%, an improvement of approximately 6.9 percentage points. It recovered its pre-crash high on June 23, 2020, nine calendar days earlier than the current backstop.

## Recession interpretation

### 2001

The override made no additional change during the official March-November 2001 recession window. Results therefore matched the current backstop.

### Great Recession

The override reduced maximum drawdown from -33.06% to -31.14%, but total recession-window return was worse because it spent more time defensive during partial rebounds. This is the largest trade-off in the result.

### COVID

This is where the mechanism worked as intended. Portfolio damage and breadth deterioration accelerated together, triggering on February 27, 2020—before the normal 15.5% portfolio threshold.

## Parameter stability

The selected shock signal was tested across 648 recovery and rearming variations at a 40% equity floor.

- Median CAGR: 20.51%
- Median maximum drawdown: -31.61%
- COVID drawdown was -17.72% across the tested recovery neighborhood.
- 432 of 432 nearby recovery combinations retained at least 19.5% CAGR, maximum drawdown no worse than 33%, and at least four percentage points of COVID improvement.

This indicates that the recovery settings are not dependent on one exact parameter point.

However, the emergency signal itself was chosen after screening 14 distinct signal behaviors and 27,216 complete configurations. The result is therefore in-sample research, not proof of future performance.

## Recommendation

Promote this to the leading research challenger, but do not replace the current 15.5% controller yet.

The proposed architecture is:

> Wealth Core + 30% position stops + immutable shadow book + fast systemic-shock override + normal 15.5% portfolio backstop + 40% Wealth Core / 60% T-bills + shadow-controlled recovery.

Required validation before promotion:

1. exact next-open execution through the trusted ledger;
2. rolling-origin and leave-one-crisis-out testing;
3. frozen parameters with an untouched forward shadow;
4. explicit treatment of taxes, spread and real execution slippage;
5. verification that live holding breadth is identical across live, windtunnel and backtester.

## Status

This is a close-to-close research overlay over the certified Wealth Core aggregate path, with actual Sharadar SHY/BIL defensive returns and 10 basis points per traded side. It is not yet certified through the exact next-open accounting engine.
