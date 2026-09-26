# Formed-start Owned55 research

This experiment is **not yet a completed twenty-year result**. Its source is
the production code at main `f3e60671b525219287231d517ad6945e6ef2b649`.
The design and conditional owner authorization are recorded in
[the design document](../../docs/owned55-formed-20y-research.md).

The full 2005 source still says FAIL. Current-code analysis found that its two
unresolved split identities cannot enter the eligible pool or recent-leadership
witness: maximum ADV20 was $5,052,708.95 for FSNMQ and $532,709.20 for FCEC,
against the frozen $20 million threshold. All metadata was treated as common
stock for this test. The full source scan found no incoming terminal/spinoff
references to either identity. Three counterfactual feed runs over 5,410
sessions produced identical ranking/candidate/witness commitments. The
positive control qualified on 5,284 sessions. Removing ADV20 admitted FSNMQ
on 2005-09-01; removing both liquidity conditions admitted both identities
on 2005-07-29, and both experiments refused scope. These facts support only
the exact, conditional research permission; they do not repair the input.

`scope-certificate.json` binds the reviewed runtime, proof programs and retained
evidence bytes. The input reader verifies these plus every prefix/base member.
The original strict validator is unchanged and continues to reject the prefix.
The full replay additionally refuses either identity in holdings, scored
candidates or witness membership. A future source or runtime needs new proof.

The first attempt and original scope evidence remain in
`C:/GitHub/stocker/.codex-tmp/owned55-formed-20y-run`. The replacement attempt's
evidence directory is its `attempt-002` subdirectory. The retained input root is
`C:/GitHub/stocker/.codex-tmp`. These large licensed/research data are not
redistributed in Git. Reproduction requires those exact input bytes.

Using the pinned dependency container
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
mount the checkout read-only at `/work`, input root read-only at `/inputs`,
and evidence at `/evidence`; set `PYTHONPATH=/work:/work/shared` and
`PYTHONDONTWRITEBYTECODE=1`. Networking is disabled; memory is 4 GiB and CPU
limit is two. The following are commands inside that container:

```sh
python -m research.formed_20y.prepare_supplements \
  --base /inputs/owned55-20y-run/supplements.json --output /evidence/supplements.json
python -m research.formed_20y.extract_scope --inputs /inputs --output /evidence
python -m research.formed_20y.verify_scope --inputs /inputs --output /evidence --supplements /evidence/supplements.json
python -m research.formed_20y.verify_scope --inputs /inputs --output /evidence --supplements /evidence/supplements.json --mutation adv20
python -m research.formed_20y.verify_scope --inputs /inputs --output /evidence --supplements /evidence/supplements.json --mutation both
```

The baseline exits 0; each mutation must exit 2 with
`TARGET_BECAME_ELIGIBLE`, not merely an unrelated process error.

```sh
python -m research.formed_20y.run --inputs /inputs --scope-evidence /evidence \
  --supplements /evidence/supplements.json \
  --output /evidence/segment-001 --seconds 21600
```

Resume into a new segment directory using `--resume` with the prior
`latest-checkpoint.json`. Code, inputs, policy and capital must still match.
Output states distinguish `RUNNING`, `STOPPED_RESUMABLE`, `REFUSED`, and
`REPLAY_COMPLETE_PENDING_INDEPENDENT_REVIEW`. A checkpoint, partial CAGR or
process exit alone does not establish completion. After all closes finish:

```sh
python -m research.formed_20y.review --segments /evidence/segment-001 \
  --output /evidence/performance-review.json
```

Supply every continuation directory to `--segments` in execution order.
Review checks 126 formation sessions, 5,032 measured closes, source bindings,
checkpoint/trace commitments, the $50,000 baseline and daily NAV factor
continuity before computing return multiples, CAGR and maximum drawdown.
Review of actual economic events and remaining research assumptions is still
required before interpreting these figures. This is not full provider,
cash-finality, native-fill, broker or NAS certification.

## Targeted validation before the replay

* `python -m pytest research/formed_20y/test_run.py research/formed_20y/test_inputs.py tests/sentinel/test_formed_economics.py -q -p no:cacheprovider`: **24 passed in 8.70s**.
* `python -m pytest research/formed_20y/test_review.py -q -p no:cacheprovider`: **6 passed in 1.61s**.
* Both actual-data guard-removal controls above refused for target eligibility.
* Full input constructor verified all bytes, 5,410 exact closes and source
  status FAIL under the separate research scope certificate.
* Production files are unchanged; Python parsing and whitespace checks pass.

Tests include an independent first-funded-entry calculation: a $50,000 account
with 55% allocated to a half-stock/half-cash Core book pays $36.25 in entry
costs on flat prices. Removing formed-entry accounting incorrectly charges
$22.50 and is caught. Historical shadow wealth is never substituted for the
new funded baseline. The arithmetic oracle checks accounting equations; it
does not independently establish every source event's historical truth.

## First refusal and sourced replacement input

Attempt one stopped at 2006-11-13 after 74 measured closes. TRBS was still a
57-share holding, but the original November 10 terminal record lacked cash
terms and the November 13 session had no quote. The financial refusal and exact
candidate state were independently reproduced from the November 10 checkpoint.

The issuer's SEC-archived completion release establishes $38.90 per share at
5 p.m. Central on November 10. Its cancelled $0.04 dividend is not payable.
`trbs-supplement.json` retains these sources and the existing next-session
research cash-equivalent convention, which is not broker cash finality. The
original archive and 160 existing supplement records are unchanged. The new
combined file has SHA256
`03e5b0afa32c6db5f827ff705a3793ef4d533f39e76e91b6ab4f92e15eefe6d3`.

On the actual stopped book, the added record converts 57 shares to $2,217.30,
resolves Core opening/closing equity, and passes independent funded accounting.
Missing terms still refuse; including the cancelled dividend fails the payout
oracle. The original trace is not joined to the replacement attempt. The new
input binding requires a fresh 252+126 run.

Validation after the addition:
`python -m pytest research/formed_20y/test_run.py research/formed_20y/test_inputs.py research/formed_20y/test_review.py research/formed_20y/test_supplements.py tests/sentinel/test_formed_economics.py -q -p no:cacheprovider`
passed **34 tests in 9.15s**. Removing the supplement hash, duplicate-identity,
and exclusive-output guards separately killed their acceptance tests after the
positive baseline. Both actual-data liquidity falsifiers were rerun and refused
after the new supplement's passing scope baseline. Source/proof hashes now bind
that new input; production bytes and policy remain unchanged.

## Third refusal and reviewed spinoff inputs

Attempt 003 at `da1acc87ba709027258d1724d074739a0f19ab53` refused
2014-08-28 after 2,034 measured closes through August 27. Its stopped worker,
final log, checkpoint and refusal are retained under
`.codex-tmp/owned55-formed-20y-run/attempt-003/segment-003` (the final Docker
log is `attempt-003/segment-003-final.log`). The checkpoint SHA256 is
`df101f3d534d8263b00da0761f7f156d0f7e49642e941d9e0fc0c5ca236695d1`.
The two LVNTA shares required reviewed LTRPA child terms. SEC sources and
the exact treatment are in `lvnta-supplement.json` and the design document.

The research adapter also now removes three exact in-kind cash proxies,
bound to original observation hashes and matching reviewed child identities
and ratios. This prevents counting both child ownership and cash for the same
distribution. LVNTA, BAX and MRK original observations and ACTIONS records
are preserved in `spinoff-source-rows.json`; unrelated dividends are unchanged.
This is an economic correctness finding in research inputs. Earlier results
past an owned affected distribution require re-evaluation. Production source,
provider loader and frozen policy remain unchanged from `f3e60671`.

The new combined supplement retains all 160 originals plus TRBS, ISLN and
LVNTA (163 records), SHA256
`ec3f380e6d6c0037da6f80e09facb9217bc4b1b952538c9d2cc0e868fd991bc9`.
The new source/input binding requires fresh attempt 004; attempts 001â€“003
remain distinct, stopped evidence and cannot contribute to its return trace.

Validation on the replacement source:

```sh
python -m pytest research/formed_20y/test_run.py research/formed_20y/test_inputs.py research/formed_20y/test_review.py research/formed_20y/test_supplements.py research/formed_20y/test_spinoff_inputs.py tests/sentinel/test_formed_economics.py -q -p no:cacheprovider
```

**42 passed in 12.21s** in the pinned image, network disabled, 4 GiB and two
CPUs. The six new spinoff checks passed again before source-hash, child-terms
and cash-proxy mutants each failed the relevant oracle. The actual-data scope
baseline passed; both `adv20` and `both` liquidity mutants refused with
`TARGET_BECAME_ELIGIBLE`. All 337 production/dependency commitments and two
proof programs matched. Exact commands and outputs are retained in
`attempt-004/run-scope-checks.py`, `scope-*.log`, `mutate-spinoff-inputs.py`
and `spinoff-*.log`. No skipped tests, repinned production goldens or relaxed
guards were introduced. Full replay and independent final review remain pending.

`attempt-004/accept-lvnta.py` reproduced the actual stopped transition using
the canonical kernel and all verified input bytes. Its successful evidence is
`acceptance-2014-08-28-v4/results.json`: two child shares received and sold,
$74.64528 net proceeds, no extra $74 parent dividend, parent quantity/slot
preserved, resolved valuation and independent funded accounting passed.
Missing terms still refused; wrong-ratio and duplicate-dividend candidates
failed the independent oracle. Earlier diagnostic directories are retained:
v1/v3 selected another same-day distribution in the wrong-ratio diagnostic,
and v2 refused the temporarily unrebound scope evidence. They are diagnostic
setup failures, not replay segments or successful acceptance evidence.

## Fourth refusal and reviewed CNQR cash terms

Attempt 004 refused 2014-12-05 after 2,103 measured closes through December 4.
The stopped book held 45 CNQR shares, while the next session had neither a
quote nor terminal cash terms. The exact checkpoint, refusal and daily trace
are retained under `attempt-004/segment-003`; this trace remains stopped.

Concur's SEC-filed completion report and SAP's SEC-archived completion release
establish that the merger completed on December 4, 2014 and converted each
outstanding CNQR share into $129 cash. `cnqr-supplement.json` records those
terms using the existing next-session research recognition convention. For the
stopped position the independently checked payout is $5,805. This convention
does not establish broker cash finality.

The replacement supplement retains all 160 original records plus the reviewed
TRBS, ISLN, LVNTA and CNQR events (164 records), SHA256
`c75d45188f61e6c777064ca3e2e5c0eacc7d4954a527430802192782b724166c`.
Missing terms and a wrong identity still refuse. An altered cash amount fails
the independent payout oracle. Because the supplement and scope-evidence
bindings changed, attempt 004 cannot be joined to the replacement economic
trace. Production strategy, provider loading and policy remain unchanged.

Validation on this replacement source passed **45 tests in 9.03s** in the
pinned offline image. Actual stopped-state acceptance is retained at
`attempt-005/acceptance-2014-12-05-v2/results.json`: the sourced transition
paid exactly $5,805, freed the CNQR slot, resolved valuation and passed funded
accounting. Missing terms and wrong identity refused; $128.99 consideration
failed the payout oracle. The scope baseline passed and both real liquidity
mutants refused with `TARGET_BECAME_ELIGIBLE`.

## Discovery checkpoint migration

Research discovery and final qualification now use separate evidence rules.
`migrate_checkpoint.py` may rebind a verified stopped checkpoint only when all
retained supplements are unchanged, every addition is effective strictly after
the selected cursor, production/proof commitments are identical and harness
changes are confined to the named supplement and migration files. If an added
event reaches further back, select an earlier verified checkpoint and replay
from there. State, accounting, metadata, counters and formation evidence remain
unchanged; the migration creates a source-linked chain root and records both
bindings. Changed prior records, an event at or before the cursor, production
changes, removed harness files or economic harness changes refuse.

The owner intentionally stopped fresh attempt 005 during formation with zero
measured sessions so discovery could continue from attempt 004. Its evidence is
retained and marked `PRESERVED_NOT_JOINED`. The real migration from the
attempt-004 December 4 checkpoint passed with state SHA256
`2469263c37d7cea91d167f7159082741499b2afd0cffb92ece025ae9e84afecb`.
A one-session canonical smoke continuation processed December 5, paid exactly
$5,805 for 45 CNQR shares, reached measured session 2,104 and stopped resumably.
The migration and smoke trace are discovery evidence only.

After discovery reaches 2026-07-31, run all 252 warmup, 126 formation and 5,032
measured sessions fresh under one frozen binding. Only that end-to-end trace is
eligible for the final independent twenty-year review; migrated discovery
segments are never joined into final performance evidence.

## Fifth refusal and reviewed YOKU cash terms

Discovery attempt 006 refused 2016-04-06 after 2,437 measured closes through
April 5. The stopped book held 231 YOKU ADSs, but YOKU disappeared from the
next session without complete terminal terms. The stopped checkpoint, refusal
and trace remain immutable evidence.

Youku Tudou's SEC-filed completion release establishes that the merger
completed on April 5, 2016 and that each outstanding ADS became the right to
receive $27.60 cash. The research supplement recognizes that gross economic
entitlement on the next session, April 6, matching the retained convention for
an after-close completion. The separately disclosed ADS cancellation fee of up
to $5 per 100 ADSs is broker/depositary cash-finality information: this replay
does not invent an exact assessed fee or claim spendable cash. The resulting
research entitlement for 231 ADSs is exactly $6,375.60.

Discovery continuation must use the latest verified checkpoint strictly before
April 6 and a new binding that retains every earlier supplement byte-for-byte.
Missing terms and wrong identity must still refuse; altered consideration must
fail an independent payout oracle. Production strategy code and policy remain
unchanged. As with every discovery migration, this continued trace is not final
uniform qualification; the completed source must later run fresh end to end.

The conditional FCEC/FSNMQ scope proof was regenerated against the exact
YOKU-complete supplement. Its baseline still has no target eligibility and the
same 5,284-day positive control; both real liquidity guard-removal variants
still refuse with `TARGET_BECAME_ELIGIBLE`. The scope certificate pins those
new evidence bytes before any continuation may consume them.

## Sixth refusal and multi-child LVNTA distribution

Discovery attempt 007 refused atomically on 2016-07-25 after 2,513 measured
closes through July 22. The held book contained two LVNTA shares. Liberty's
SEC-filed completion report establishes two simultaneous entitlements per
LVNTA share: 0.1 CommerceHub Series A (CHUBA) and 0.2 CommerceHub Series C
(CHUBK), with fractional shares paid in cash. The retained PIT tape supplies
the first regular-session opens of $13.60 and $13.51 respectively.

The prior kernel incorrectly treated one parent/session as permitting only one
child. That is a production correctness defect: collapsing the two children
would invent identity and value, while accepting only one would omit an
entitlement. The reviewed design admits distinct children keyed by session,
parent and child, preflights the complete sibling set before mutation, rejects
exact duplicates, and records each child separately. For this research replay
the two fractional entitlements use the existing first-regular-open convention;
this is an economic research proxy and does not claim actual broker cash-in-lieu
timing or finality.

Because this changes the economic kernel, ordinary data-only migration remains
insufficient. A narrowly scoped compatibility migration may retain the July 22
checkpoint only if it proves that `sentinel/core/spinoffs.py` is the sole
production-file change, every reviewed in-kind event through the checkpoint has
exactly one child, all prior unresolved multi-child source events were unheld
(the completed trace would otherwise have refused), the new sibling terms are
strictly future-effective, and the old single-child behavior remains identical.
The migration may rebind only the strategy identity's
`data_semantics_source_sha256` to the reviewed kernel; every policy, controller,
Wealth Core source, configuration and research-reference identity field must be
unchanged. The resulting state hash and chain change, while cash, holdings,
ledger, controller history, metadata, counters and accounting remain byte-for-byte
equal.
Any broader change refuses. The final result still requires a fresh
252+126+5,032 run under one frozen source and runtime binding.


## Seventh refusal: ITC/Fortis mixed consideration

Attempt 008 stopped before committing 2016-10-14, preserving the verified
2016-10-13 state after 2,571 measured closes. The 153-share ITC episode lost its
mark because the retained source carries incomplete cash-merger terms dated
October 13. The SEC completion 8-K establishes suspension before the October 14
open and conversion to $22.57 plus 0.7520 Fortis shares per ITC share:
https://www.sec.gov/Archives/edgar/data/1317630/000110465916150305/a16-19905_18k.htm

Use the existing CASH_PLUS_STOCK path on October 14. Retain the original
incomplete source row and all earlier supplements. The supplied FTS tape identity
is 900440039260292770, with the first US regular-session raw open $31.03 and
close $31.66. The research fractional-share convention uses that first open as
an explicitly labelled proxy, never as the actual exchange-agent cash rate.
For 153 ITC shares the independent oracle is $3,453.21 contractual cash,
115 whole FTS shares and a 0.056-share fraction valued at $1.73768. Total research
cash is $3,454.94768; the original slot and episode age remain, and the existing
cash-adjusted conversion rule rebases references at the FTS open.

No production implementation or policy change is intended. Acceptance must
reproduce the actual stopped state, preserve the original refusal without terms,
refuse wrong identity/missing fraction valuation, reject altered cash/ratio via
independent oracles, and pass funded daily accounting. Only then may a data-only
migration retain October 13 and resume October 14. This discovery path remains
separate from the final fresh run and from PIT or broker cash-finality evidence.


ITC acceptance: 60 targeted tests passed in 9.89s with
`python -m pytest -q -p no:cacheprovider research/formed_20y/test_supplements.py research/formed_20y/test_checkpoint_migration.py research/formed_20y/test_spinoff_inputs.py research/formed_20y/test_run.py research/formed_20y/test_inputs.py research/formed_20y/test_review.py`.
The actual October 13 checkpoint acceptance passed sourced conversion and
independent daily accounting; missing terms, missing fractional valuation and
wrong identity refused; altered cash and ratio failed the independent oracle.
Evidence and the diagnostic script are retained in local
`.codex-tmp/owned55-formed-20y-run/attempt-009/acceptance-2016-10-14/results.json`
and `attempt-009/accept-itc.py`. All 167 earlier supplement records are unchanged;
the 168-record source hashes to
`307b3ff1bed7b3a0a9e7a5420429eae546af3642ce08be07b8dc92c25c10d0ae`.
Scope baseline and both actual liquidity guard-removal controls were rerun;
no target reached eligibility in the baseline, and both controls refused.

## Eighth refusal: LVNTA/GCI Liberty one-for-one conversion

Attempt 009 stopped before committing 2018-03-12 after 2,923 measured closes.
The March 9 checkpoint held two LVNTA shares in slot 6, while the retained
terminal row described an incomplete cash merger and LVNTA no longer printed.
The fail-closed unresolved-equity refusal is preserved in
`attempt-009/segment-001` and its candidate evidence in
`attempt-009/diagnostic-2018-03-12`.

The Liberty Interactive and GCI Liberty March 9 Form 8-K filings establish that
the after-close split-off redeemed each LVNTA share for one GLIBA share, leaving
no LVNTA shares outstanding. The issuer release establishes March 12 regular
trading. The retained tape names that security `GLIBA1`, identity
`758943436528193872`, with raw open $54.29. The new supplement records an exact
one-for-one `CONVERSION` on March 12 with no cash or fractional proxy:

* https://www.sec.gov/Archives/edgar/data/1355096/000110465918017857/a18-8242_18k.htm
* https://www.sec.gov/Archives/edgar/data/808461/000110465918017479/a18-8247_18k.htm
* https://www.sec.gov/Archives/edgar/data/75679/000110465918017494/a18-8246_1ex99d1.htm

All 168 previous supplement records are unchanged; the 169-record source hashes
to `9da63845647634783857156e484ffd50eb90c947ff9bbe96d0671fa6bd96b22c`.
The six targeted modules passed 66 tests in 10.47s. The actual March 9 stopped
state passed sourced conversion and independent daily accounting: two LVNTA
shares became two GLIBA1 shares in the same slot with the same episode age,
zero cash consideration and NAV $383,755.3222025809406430702172. Original
missing terms, missing ratio and wrong delivered identity refused; an altered
ratio was killed by the independent two-share oracle. Results hash to
`b3628db670cbc0ec2579769da91bb33a4db5890d28f244cb6610d4e9059882b8`.

The regenerated scope baseline passed and both actual liquidity guard-removal
controls refused. Migration-v9 verified the old checkpoint bytes, all retained
records and both bindings, and preserved economic state hash
`c8a4bc40ba78f752c23f532d52225807a25448265b6bebd5e307d78da1433011`.
This is discovery continuation only. Production code is unchanged, PIT and
broker finality remain open, and final performance still requires the fresh
single-binding 252+126+5,032-session replay.
