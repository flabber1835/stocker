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

The evidence directory on the originating workstation is
`C:/GitHub/stocker/.codex-tmp/owned55-formed-20y-run`. The retained input root is
`C:/GitHub/stocker/.codex-tmp`. These large licensed/research data are not
redistributed in Git. Reproduction requires those exact input bytes.

Using the pinned dependency container
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
mount the checkout read-only at `/work`, input root read-only at `/inputs`,
and evidence at `/evidence`; set `PYTHONPATH=/work:/work/shared` and
`PYTHONDONTWRITEBYTECODE=1`. Networking is disabled; memory is 4 GiB and CPU
limit is two. The following are commands inside that container:

```sh
python -m research.formed_20y.extract_scope --inputs /inputs --output /evidence
python -m research.formed_20y.verify_scope --inputs /inputs --output /evidence
python -m research.formed_20y.verify_scope --inputs /inputs --output /evidence --mutation adv20
python -m research.formed_20y.verify_scope --inputs /inputs --output /evidence --mutation both
```

The baseline exits 0; each mutation must exit 2 with
`TARGET_BECAME_ELIGIBLE`, not merely an unrelated process error.

```sh
python -m research.formed_20y.run --inputs /inputs --scope-evidence /evidence \
  --supplements /inputs/owned55-20y-run/supplements.json \
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
