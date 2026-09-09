# Median-5 + 10 bp cash buffer — pure Wealth Core

## Objective

Measure the economic and execution effect of adding exactly a 10 basis-point NAV cash reserve to the frozen Median-5 Wealth Core configuration.

This experiment is pure Wealth Core. EX3, Research Champion allocation, Sentinel, Caesar exposure control, and defensive-overlay returns are not executed or used in the result.

## Frozen control authority

- Median-5 full-PIT recertification run: `34160387335`
- Artifact: `10032942751`
- Source head: `1c66096c1e3bd650233c630d4e9f71104ac8fc32`
- Median-5 generated source SHA-256: `3b1bb12dc4f246dc855c135bce04f97cef79a38c9bd81245c543b733c492290b`
- Median-5 daily output SHA-256: `4be426c1f92c6684d0227bf613d474ee335aeef71c6b87ac112dfffdb743f66e`
- Canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Measurement: 2006-07-31 through 2026-07-31, 5,032 sessions

Correct pure Wealth Core control metrics are measured from `shadow_equity`, not the controller-layered `A_nav`:

- 20y CAGR: 16.0742527656%
- 20y max drawdown: -48.8397781022%
- 20y daily-252 Sharpe: 0.8065779074
- 20y ending multiple: 19.7126275836x

## Frozen Median-5 economics

- 20 physical slots
- 5% nominal entry target
- Median-5 top-3 admission hardening from trailing five causal rank-order observations
- `COOLDOWN = 21`
- `REVIEW_AGE = 119`
- `STOP_RET = 0.70`
- `COST = 0.001`
- `MIN_ADV20 = 20_000_000.0`
- `MIN_DAY_DV = 5_000_000.0`
- exact one-session dividend settlement
- whole-share buys only

## Sole economic change

Reserve 10 bp = 0.001 of current NAV as uncommitted cash.

At the decision close:

- `required_reserve = close_NAV * 0.001`
- `available_cash = max(0, cash - required_reserve)`
- requested capital remains 5% of NAV
- target shares are the largest whole-share quantity affordable from `min(5% NAV, available_cash)`

At the next executable open:

- recompute `required_reserve = open_NAV * 0.001`
- `available_cash = max(0, cash - required_reserve)`
- fill at most the planned whole-share quantity
- if fewer shares are affordable, clip the quantity
- if zero shares are affordable, do not fill

The reserve may not be spent by a buy.

## Fail-closed gates

- exact Median-5 control source identity reproduced before applying the 10 bp patch
- exact formal/candidate/runtime pins preserved
- canonical PIT package/dataset unchanged
- replay mode `fullpit`
- 5,032 measurement sessions
- one-session dividend lag; any 15-session regression fails
- security-type traversal and candidate coverage unchanged
- zero reserve violations
- no negative cash
- all executed buy quantities integer
- EX3/Sentinel controller calls absent from the executed generated variant
- result metrics use only pure Wealth Core `shadow_equity`
- no performance target is used

## Outputs

Preserve generated sources, `daily.csv`, `summary.json`, `transactions.csv`, `RESULT.json`, hashes, package/corpus validation, and full run log as a GitHub Actions artifact.
