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
The new source/input binding requires fresh attempt 004; attempts 001–003
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
