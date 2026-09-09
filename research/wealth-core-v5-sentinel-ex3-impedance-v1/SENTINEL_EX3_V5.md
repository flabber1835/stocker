# Sentinel EX3 V5

**Sentinel EX3 V5** is the canonical name for the Sentinel EX3 controller impedance-matched to Wealth Core V5.

## Definition

Sentinel EX3 V5 uses:

- LDRC_REC: 8 sessions
- LDRC_R20: -8.5%
- LDRC_V: +11.0%
- LDRC_DD: -10.0%
- divergence SPY floor: 0.0%
- full-recovery recent-leadership r40 floor: **-5.0%**
- divergence ceiling: 55.0%
- native FAST damaged breadth: 88.0%
- native healthy damaged ceiling: 63.0%

The defining impedance-match change from the prior Sentinel EX3 configuration is the full-recovery recent-leadership r40 floor moving from 0.0% to -5.0%.

## Pairing

The name **Sentinel EX3 V5** specifically refers to this controller when paired with frozen Wealth Core V5:

- Median-5 ranking
- 20 holdings
- 5% target entry weight
- 10 bp close admission reserve
- total-cash one-share affordability
- next-valid-open whole-share sizing
- one-session dividend lag

## Evidence

The naming decision is based on the 10-arm full-PIT impedance study in GitHub Actions run `34319850800`.

The selected `REC=8 / r40=-5%` arm is path-identical to the adjacent `REC=8 / r40=-4%` full replay and produced:

- 20-year CAGR: 21.5572%
- 20-year max drawdown: -27.3755%
- 20-year Sharpe: 1.1211
- 20-year ending multiple: 49.6193x

Full rationale and evidence are in `RESULTS.md` and `FINAL_IMPEDANCE_CONFIG.json` in this directory.

## Scope

This naming record is research-only. It does not by itself change production or main.