# Backtester context checkpoint — 2026-08-28 / split integrity + acceleration

Branch: `research/backtester`

Pinned production/main source: `c502d077cae9c494f8b74a41ee8be7f40b25837d`

Production/main has not been modified.

## A/D invariant

A and D share one Wealth Core economic path by experiment design. D changes only Sentinel peer/sector grouping to strict-prior SEC SIC -> FF12. Any accelerated runner must preserve exact Wealth Core state and exact A/D economics session by session.

## Corporate-action terminal repairs already certified

Frozen research-only terminal terms cover:

- LIT1 / sid 120448 — 2001-05-30 cash merger, $80/share.
- CIT.A / sid 122131 — 2001-06-01, 0.6907 TYC per CIT share plus exact fractional CIL using the prior TYC close.
- GPU / sid 121383 — 2001-11-07, strategy no-election treatment, $36.50/share; 204,677 shares -> $7,470,710.50.

Current terminal-terms digest: `b9a143e84548e2569391aa8080d75b97034d61187c81f40319f640480fb16a4a`.

Current three-event terms verification run `33211232016` is green.

## Full-corpus split audit — authoritative current finding

Normalization-only workflow run: `33213682310`

Artifact ID: `9702956209`

Artifact ZIP SHA256: `2df5fa78404e41ea437240dd64ce4495e4fcc131f83143c48a3c124b81724cba`

Result JSON SHA256: `ea821c8c63d463438c8e9e77352957751268e9a357d7d05b11823086c2240feb`

Exact result:

- 46,238,394 SEP bars processed.
- Through 2026-07-31.
- 128 split reconciliations remain `unresolved` under exact frozen-main semantics.

The complete 128-record list lives in the immutable workflow artifact above. An attempted repository copy was found incomplete immediately and deleted; do not use that deleted file as evidence.

### Important economic correction

It is insufficient to test whether a split-conflict security was held on the action date.

Split handling changes the reconstructed signal-close series. That series feeds momentum, durable ranking, candidate selection and admissions. A wrong split can therefore alter Wealth Core before ownership. Certification must account for the candidate/ranking path as well as held positions.

### First taxonomy of the 128 conflicts

- 114: ACTIONS says split, while SEP has no material adjusted-vs-raw transition on the ACTIONS date.
- 3: SEP transformation matches the reciprocal of the ACTIONS value within 1%.
- 1: SEP transformation is a near direct match within 5%.
- 10: other material ACTIONS-vs-SEP transformation conflicts.

The 14 rows with material SEP transformations are:

- ACER 2017-09-21: stated 0.09662, SEP-derived 0.09996041171813144.
- AZN 1998-04-08: stated 0.33333, SEP-derived 3.000021476279449.
- DAYR 1998-03-18: stated 2.0, SEP-derived 10.0.
- ETELY 2007-09-04: stated 0.5, SEP-derived 2.0.
- GOLLQ 2017-11-22: stated 2.0, SEP-derived 2.5.
- MTL 2008-05-20: stated 0.5, SEP-derived 3.0000088894420096.
- MTL 2016-01-12: stated 3.0, SEP-derived 0.5.
- NCRI 2003-06-16: stated 1.9, SEP-derived 0.5263530601922105.
- NEOM 2014-05-29: stated 0.06667, SEP-derived 0.07142857142857142.
- ONSM 2003-06-24: stated 0.16667, SEP-derived 0.06666666666666667.
- PRPO 2017-06-06: stated 0.03333, SEP-derived 0.0022222222222222227.
- PRTK 2009-02-06: stated 0.2, SEP-derived 2.4.
- PTIX 2016-07-27: stated 0.00006, SEP-derived 0.00006500260010400415.
- SQNS 2019-11-29: stated 0.4, SEP-derived 0.25.

## Targeted 14-event nearby-session triage

Workflow run: `33217264493`

Artifact ID: `9703839221`

Artifact ZIP SHA256: `29afe059df702c2b7bff7b2836f8d3e88723ea31f60e20e098d1bf1bfeefeeee`

The targeted scanner checks nearby SEP adjustment transitions around each action date.

Key facts:

- AZN: action-date SEP factor ~3.0000214763; exact reciprocal match to stated 0.33333.
- ETELY: action-date SEP factor 2.0; exact reciprocal match to stated 0.5.
- NCRI: action-date SEP factor 0.5263530602; essentially 1/1.9.
- GOLLQ: action-date SEP factor 2.5.
- MTL 2008: action-date SEP factor ~3.0000088894.
- MTL 2016: action-date SEP factor 0.5.
- ACER: action-date SEP factor ~0.0999604, but the legal reverse-split ratio is 1/10.355527 (~0.09656679), so SEP alone is not sufficient for exact legal share-count reconstruction at this low-price/merger boundary.

## Primary-source confirmations obtained

### ACER / former OPXA

SEC filing confirms:

- merger completed 2017-09-19;
- 1-for-10.355527 reverse stock split effected 2017-09-19;
- pre-split OPXA traded through 2017-09-20 close;
- post-split ACER began trading 2017-09-21.

Primary source:
`https://www.sec.gov/Archives/edgar/data/1069308/000156459018004714/R8.htm`

Exact legal multiplier = `1 / 10.355527 = 0.09656678988910945`.

### GOLLQ / GOL

SEC Form 6-K dated 2017-11-09 confirms ADS ratio change:

- old: 1 ADS = 5 preferred shares;
- new: 1 ADS = 2 preferred shares;
- holders receive 1.5 additional ADS per ADS;
- distribution date 2017-11-21.

Therefore the listed ADS share multiplier is exactly 2.5. SEP shows 2.5 at the 2017-11-22 transition.

Primary source:
`https://www.sec.gov/Archives/edgar/data/1291733/000129281417002835/gol20171109_6k2.htm`

### MTL / Mechel 2008

SEC Form 20-F confirms that on 2008-05-19 Mechel announced a change in ADS/common-share ratio from 1:3 to 1:1 and issued two additional ADS for each old ADS. Legal ADS multiplier = 3.0. SEP shows ~3.0000088894 at the 2008-05-20 price-domain transition.

Primary source:
`https://www.sec.gov/Archives/edgar/data/1302362/000104746908007591/a2186351z20-f.htm`

### MTL / Mechel 2016

Mechel/SEC historical disclosures confirm ratio change from 1 ADS per 1 common share to 1 ADS per 2 common shares effective 2016-01-12. Legal ADS multiplier = 0.5. SEP shows exactly 0.5 on 2016-01-12.

SEC supporting source:
`https://www.sec.gov/Archives/edgar/data/1302362/000119312521085807/d29899dex21.htm`

Mechel annual-report source:
`https://mechel.com/upload/iblock/7ca/7ca0c375c51d12adc8df55c1b69ae5bc.pdf`

### AZN

SEP shows a 3x action-date transition while Sharadar ACTIONS says 0.33333. Multiple historical references identify a 3-for-1 event on 1998-04-08, but a sufficiently strong primary issuer/source witness has not yet been pinned. Do not freeze an AZN override until that primary witness is obtained or an accepted independent historical authority is explicitly documented.

## Split repair acceptance rule

Do not globally invert ACTIONS ratios.

Do not globally trust SEP-derived ratios.

Each research-only override must have:

1. exact ticker/security identity and effective trading session;
2. exact legal/listed-security share or ADS multiplier;
3. a causal/public-availability statement;
4. primary or equivalently strong historical provenance;
5. frozen source reference/hash where practical;
6. replay verification that exact current-main normalization consumes the override;
7. economic A-path verification after repair.

A separate data-driven rule may be promoted only if it is first proven over the complete conflict population and has no counterexamples.

## Acceleration status

Shared-Wealth-Core runner:
`backtester/run_sector_ad_shared_wealth_core.py`

Design:

- A calls real production `plan_session()`.
- D receives deep-copied exact post-plan Wealth Core state, pending events, ledger, marks, feed and `LiveSessionPlan`.
- D then executes its independent Sentinel/controller/LD-RC path.
- Pre-plan A/D state equality and post-session Wealth Core parity remain fail-closed gates.

Prior equivalence run `33213523888`:

- corrected bounded baseline passed 252 sessions through 1998-12-31;
- baseline final A=B=1.097576;
- baseline elapsed 1802.26 seconds;
- optimized arm did not reach the shared-Wealth-Core seam because the 1998-only test axis rejected frozen 2001 terminal terms as off-axis.

Patch `19ac4b2caf9e29656e3c54ad2856ec9f606b9906` excludes those future 2001 terminal records only in a pre-2001 bounded equivalence test. Full replay terminal handling is unchanged.

Current equivalence run: `33217309808`.

No acceleration speedup is certified until this run executes both arms and proves byte-identical daily/metrics output.

## Other active long runs at this checkpoint

- A/D full replay v2: `33210946520`.
- original allocation-boundary unresolved-open scanner: `33196508963`.
- comprehensive held-terminal-gap scanner: `33211049538`.
- current shared-Wealth-Core equivalence: `33217309808`.

Live job-log blobs are intermittently unavailable from GitHub while jobs execute.

## Next actions

1. Finish equivalence run and inspect exact speedup + plan-call counts.
2. Run nearby-session classification across all 128 split conflicts so shifted action dates are separated from true no-listed-event cases.
3. Freeze primary-source-backed split overrides incrementally (ACER/GOLLQ/MTL are first strong candidates).
4. Re-run normalization-only audit after each coherent override batch and require the unresolved count to fall exactly as expected.
5. Use the full A path to verify economic effects; include ranking/candidate effects, not only held-position overlap.
6. Resolve the remaining terminal-gap scanner findings when the comprehensive scan completes.
7. Add exact checkpoint/resume only after shared-Wealth-Core equivalence passes.
