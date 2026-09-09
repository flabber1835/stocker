# Wealth Core V2 + Caesar 20 + next-open sizing + EX3 — full PIT

Research-only experiment. No production changes and no merge.

## Objective

Run one fresh 20-year canonical full-PIT replay with:

- Wealth Core V2 slot-funding semantics as the frozen base;
- Caesar 20 portfolio architecture only: `N_SLOTS = 20`, `ENTRY_W = 0.05`;
- initial capital `$100,000`;
- 10 bp close-time admission cushion;
- close-bound economic intent, with **no share quantity bound at the close**;
- next-valid-open whole-share quantity determination from the actual opening price;
- frozen EX3 Sentinel/Candidate-A exposure controller in parallel on the same Wealth Core path;
- canonical PIT window 2006-07-31 through 2026-07-31 (5,032 measurement sessions).

This is a broad-universe canonical PIT experiment. It is separate from the contemporaneous S&P-500-filtered experiment.

## Frozen authorities

- Formal Wealth Core V2 source base: `880209078f2b4817e837431984dc0ba0bf0b9d79`
- Canonical PIT dataset SHA256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Pinned runtime authority: `887f479b15ad861313da666ad698034d3847121c`
- Caesar 20 evidence head: `171d2e1fcea7f7ada2f6eeeefeccceb8d5c120b0`
- Caesar 20 definition: only 20 slots and 5% nominal entry weight. No Median-5 rank hardening is included.
- EX3 controller: frozen Candidate-A / `A_nav` path already present in the formal Research Champion source.
- Dividend settlement remains exactly one session.

## Next-open sizing contract

At the close:

1. Wealth Core selects the ticker using its unchanged ranking and admission logic.
2. Target capital is `close_NAV * 5%` under Caesar 20.
3. A 10 bp cushion is excluded from close-time uncommitted cash.
4. V2 admission requires the **full target dollar intent** to be fundable above that cushion.
5. The close also requires at least one whole share to be affordable at the known close price; this is only an admission gate, not share-quantity binding.
6. The slot stores ticker + target dollars. `pending_shares` is deliberately not used to bind quantity.

At the next valid open:

`shares = floor(min(reserved_target_dollars, actual_cash) / (actual_open_price * (1 + COST)))`

The frozen capacity guard is evaluated using that newly determined open-time share quantity. No leverage and no negative cash.

## Measurements

Record separately:

- pure Wealth Core raw-book path (`shadow_equity`);
- EX3 path (`A_nav`);
- 5/10/15/20-year CAGR, max drawdown and daily Sharpe for both;
- EX3 incremental contribution;
- admissions, open-time zero-quantity blocks, close affordability rejects and V2 cash rejects;
- whole-share rounding underfill;
- buys/sells and integer-share verification;
- EX3 allocation statistics and transition counts;
- generated-source hashes and canonical-data bindings.

## Interpretation

Caesar 20 is an in-sample research challenger, not a production-certified replacement. Performance is not used to modify parameters during this run.
