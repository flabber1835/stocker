# Wealth Core V1 — 10 bp open-time sizing A/B

## Objective

Test whether moving buy quantity determination from the prior close to the actual next open removes execution binding while keeping the frozen Wealth Core V1 decision logic and a 10 basis-point close-time cash cushion.

## Authority

Base evidence head: `3b5d70de258dadaac6272f2bd9d682d291117d29`.

Control authority is the certified 10 bp sweep arm from workflow `34291013480`:

- generated source SHA-256: `5f61d5ed5afd784bfb247d554344199743de11dcf9b31956430c6a77b91fedf7`
- canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- dividend lag: 1 session
- initial capital: $100,000
- measurement window: 2006-07-31 through 2026-07-31

## Frozen economics

Keep frozen:

- Wealth Core V1 stock selection
- ranking and candidate ordering
- exits and review timing
- 4% intended entry target
- costs/slippage
- PIT data and security-type authority
- terminal-event handling
- dividend timing
- initial capital and measurement window

## Experimental change

The close chooses the ticker and records the 4% intended dollar target. The 10 bp cushion is enforced as a close-time admission condition: a candidate can be reserved only when cash above 10 bp of close NAV is positive.

At the next valid open, the 10 bp cushion is released into the execution funding pool and the actual share quantity is calculated from the actual open price and available cash.

No share quantity is frozen at the prior close.

### Arm A — open-time whole shares

At the open:

`execution_budget = min(intended_close_dollar_target, actual_cash_before_buy)`

`shares = floor(execution_budget / (open_price * (1 + cost)))`

A trade is blocked only if zero whole shares are affordable or the execution price/volume is invalid.

### Arm B — open-time fractional shares

At the open:

`execution_budget = min(intended_close_dollar_target, actual_cash_before_buy)`

`shares = execution_budget / (open_price * (1 + cost))`

Fractional quantities are allowed. A trade is blocked only if the execution budget is zero or the execution price/volume is invalid.

## Required outputs

For each arm report:

- CAGR, max drawdown, Sharpe, ending equity
- close admissions
- completed entries
- close q=0 skips from having no cash above the 10 bp cushion
- next-open complete blocks
- invalid-open blocks
- cash-limited open executions
- whole-share rounding underfill dollars and percentages
- entries below 1%, 5%, 10%, 25%, 50%, and 99% of intended size
- minimum/average/maximum entry fraction
- minimum actual cash
- fractional buy count
- transaction ledger
- complete open-execution event ledger
- path divergence versus the certified 10 bp control

## Decision question

Determine whether open-time sizing makes every close admission executable, and whether fractional shares add meaningful economic/execution benefit beyond open-time whole-share sizing.

Do not select an arm based solely on CAGR. Treat performance differences as path-dependent.

Research only. No production modification. No merge.
