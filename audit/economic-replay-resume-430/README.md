# Resumed provisional historical economic run

Production source is merged PR #430 at
`ee23c894c97a2c4023654ce3a56a62728f5b061e`. Current Sentinel champion
parameters are unchanged. The source-fork rules and every supplemental action
decision are documented in
[`docs/economic-replay-resume-430.md`](../../docs/economic-replay-resume-430.md).

This run continues the existing $100,000 January 2006 formation and measures
CAGR from July 31, 2006. It is a mixed-source historical economic experiment,
not full-system certification. It reached the full retained endpoint without
changing Sentinel parameters or repinning the research reference.

## Accepted result and boundary

The accepted lineage contains 5,176 exchange sessions from January 3, 2006
through July 31, 2026. The measurement baseline after formation is
$92,527.41663482299.

| Series | Multiple | CAGR |
| --- | ---: | ---: |
| Current Sentinel | 29.243785x | 18.385953% |
| Retained research reference | 56.265349x | 22.323600% |
| SPY | 8.443307x | 11.256316% |

Account NAV is $2,705,851.862725465 and maximum drawdown is 29.773249%. The
multiple uses the July 31 measurement baseline, so it is not account NAV divided
by the original $100,000. The production-path result trails the reference by
27.021564 multiples and 3.937647 annualized percentage points. The result is
preserved as observed rather than fitted to the reference.

`verification.json` reports **PASS** for independent CAGR/multiple arithmetic,
all-session coverage, NAV continuity, checkpoint byte/hash integrity, final
holdings marked from the PIT archive, applied-supplement equality, source
binding, and final Wealth Core cash/receivables/positions reconciliation. The
maximum CAGR arithmetic error is 6.772e-15. These checks establish trace and
arithmetic integrity; they do not establish deployed provider or broker
behavior.

`latest-checkpoint.json` points to the clean July 31 checkpoint, SHA256
`72d621aac063cf6ae2e50d3d1c681c74ce2df8f83c74dcc77978c00eb6d7f918`,
15,200,016 bytes. The checkpoint and licensed source archive stay local. The PR
retains the compact accepted daily trace, source/evidence identities, and exact
resume pointer.

This result remains diagnostic. The retained archive wrongly admitted an IIVI
mandatory convertible preferred security as common stock, gave delivered
Chesapeake the wrong issuer and sector before October 2, 2024, and gave SILV
the wrong issuer and telecom sector from its 2018 listing. Those attributes can
change Wealth Core ranks before any terminal supplement is applied. A corrected
authoritative archive and replay from before the first affected session are
required before treating the CAGR or multiple as certified strategy economics.

## Accepted retry lineage

`build_series.py` selects retries by reviewed causal boundary rather than
performance. In addition to the earlier retry cuts, segments 073-075 and
079-081 are excluded, while segments 076-078 and 082-084 own explicit clean
date ranges. Segment 084 owns the final pointer. `series-provenance.json`
records every source hash and date owner, 313 predecessor overlaps (six
different), and 190 excluded rows.

## Validation commands

```powershell
python audit/economic-replay-resume-430/build_series.py `
  --root C:/GitHub/stocker/.codex-tmp `
  --output C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/verification-series-084 `
  --last-segment 84

python -B -m research.economic_replay60.verify `
  --segments C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/verification-series-084 `
  --reference C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894/research/bounded_20y/reference-daily.csv.gz `
  --sfp 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' `
  --archive C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip `
  --supplements C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/supplements-continued.json
```

The independent verifier passed at the retained endpoint. No NAS, broker
account, strategy parameter, or production code was accessed or changed by
this continuation.
