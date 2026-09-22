# Resumed provisional historical economic run

Production source is merged PR #430 at
`ee23c894c97a2c4023654ce3a56a62728f5b061e`. Current Sentinel champion
parameters are unchanged. The source-fork rules and every supplemental action
decision are documented in
[`docs/economic-replay-resume-430.md`](../../docs/economic-replay-resume-430.md).

This run continues the existing $100,000 January 2006 formation and measures
CAGR from July 31, 2006. It is a mixed-source historical economic experiment,
not full-system certification. The full retained reference is 56.265349x /
22.323600% over twenty years; all interim comparisons below use the same date.

## Accepted result and boundary

The accepted lineage contains 4,027 exchange sessions from January 3, 2006
through December 30, 2021. The measurement baseline after formation is
$92,527.416634823.

| Series | Multiple | CAGR |
| --- | ---: | ---: |
| Current Sentinel | 9.987627x | 16.098855% |
| Matched-date reference | 15.148477x | 19.278468% |
| SPY | 5.063147x | 11.094024% |

Account NAV is $924,129.350316094 and maximum drawdown is 29.773249%. The
multiple uses the July 31 measurement baseline, so it is not account NAV divided
by the original $100,000. Full twenty-year economics remain incomplete.

`verification.json` reports **PASS** for independent CAGR/multiple arithmetic,
all-session coverage, NAV continuity, checkpoint byte/hash integrity, final
holdings marked from the PIT archive, applied-supplement equality, source
binding, and final Wealth Core cash/receivables/positions reconciliation. The
maximum CAGR arithmetic error is 6.772e-15. These checks establish trace and
arithmetic integrity; they do not establish deployed provider or broker
behavior.

`latest-checkpoint.json` points to the clean December 30 checkpoint, SHA256
`03c966068ac73f2b5c2034cd4dbe9108da5ffb8677cbf7d3d775d4358f675550`,
19,878,633 bytes. The checkpoint and licensed source archive stay local. The PR
retains the compact accepted daily trace, source/evidence identities, and exact
resume pointer.

## Accepted retry lineage

`build_series.py` selects retries by reviewed causal boundary rather than
performance. Segment 044 is accepted only through July 6, 2015; segment 047 only
through January 28, 2016; exploratory segments 048-051 are excluded; corrected
segment 052 and later segments are required to be non-overlapping. Segment 069
owns the final pointer. `series-provenance.json` records every source hash and
date owner, 313 predecessor overlaps (six different), and 112 excluded rows.

## Validation commands

```powershell
python audit/economic-replay-resume-430/build_series.py `
  --root C:/GitHub/stocker/.codex-tmp `
  --output C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/verification-series-069 `
  --last-segment 69

python -B -m research.economic_replay60.verify `
  --segments C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/verification-series-069 `
  --reference C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894/research/bounded_20y/reference-daily.csv.gz `
  --sfp 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' `
  --archive C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip `
  --supplements C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/supplements-continued.json
```

The independent verifier passed at the retained endpoint. Before the next
resume, copy the committed supplements to the runtime mirror, resume from the
pointer named above into a new numbered segment, and retain a new clean
checkpoint. No NAS, broker account, strategy parameter, or production code was
accessed or changed by this continuation.
