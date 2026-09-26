# Multi-child ownership: bounded financial certificate

Reviewed baseline: `f3e60671b525219287231d517ad6945e6ef2b649` (main).
The only production change is `sentinel/core/spinoffs.py`; exact tested source,
test and runner SHA256s are in [certificate.json](certificate.json). The design
and admission limitations are in [multi-child-spinoffs](../../docs/multi-child-spinoffs.md).

The old parent/session uniqueness rule refuses a valid second child. The new
transition validates all supplied children before posting any of them, rejects
the same economic child even under different source-row IDs, and rebases the
parent references once using aggregate gross child value. Child liquidation is
the existing shadow-book policy, not a new broker liquidation path.

## Verified financial witnesses

- 29 focused tests pass, with independent decimal/rational oracles for whole
  shares, fractions, fees, cash, parent references, unchanged quantities/slots,
  complete supplied-set refusal, duplicate terms and ambiguous bar identities.
- A three-share/two-child example produces $64.8501 net proceeds: one $31.90
  whole share less $0.0319 fee, $15 fractional consideration, and one $18 whole
  share less $0.018 fee. The canonical kernel closes at $1,181.4301 NAV from
  $1,000 prior cash and three parent shares marked at $38.86. Serializing before
  the event and restarting after it preserve the exact daily state.
- The LVNTA ratio example (two parent shares, 0.1 CHUBA at $13.60 and 0.2 CHUBK
  at $13.51) produces $2.72 + $5.404, no whole-child liquidation fee and no lost
  parent shares. This is a synthetic ownership witness using the reviewed
  terms, not replay of the historical stopped checkpoint or proof of broker
  cash-in-lieu finality. No research supplements enter this PR.
- 40 single-child cases match current main's complete state, ledger and audit
  JSON byte-for-byte, across five share counts, four ratios and one/two episodes.
- All 11 controlled source mutants are killed after the passing baseline:
  parent-only uniqueness; no duplicate guard; source ID creating another
  entitlement; missing opening-ticker/ambiguous-bar guards; omitted child basis;
  double basis application; per-episode rounding; omitted fees/fractional cash;
  and nondeterministic sibling ordering. JUnit identities and log hashes are
  retained in the certificate.
- `source_identity.py` proves that substituting only main's spin-off module
  changes the aggregate data-semantics identity; all other module commitments
  stay equal. Exact results are in `source-identity.json`.

## Reproduction

The broader command below completed in 639.14 seconds: **1,045 passed,
3 unchanged historical xfailed**, zero failures/errors/ordinary skips/xpasses.
The three strict expected failures cover historical golden result-hash pins;
their exact test identities and reasons are in [regression.json](regression.json).
They are retained limitations, not passes. No fixture, exclusion, mark or golden
pin was changed. Normal PR CI is separate from these local results.

Use Python 3.12 in the pinned local test image recorded in the certificate.
Extract `sentinel/core/spinoffs.py` from the baseline commit to a read-only
`/baseline/spinoffs.py` (SHA256
`415a89ca975d36a4d20ec96cd9e779e473e49d31e5754faefd1cd8fdcf1cfb86`).
Mount this checkout read-only at `/work`, evidence writable at `/evidence`,
set `PYTHONPATH=/work:/work/shared`, `SENTINEL_REPO_ROOT=/work`, and
`PYTHONDONTWRITEBYTECODE=1`. Use `--entrypoint python`, `--network none`,
`--memory 4g` and `--cpus 2`.

```sh
python audit/multi_child_spinoffs/certify.py \
  --baseline /baseline/spinoffs.py \
  --baseline-sha256 415a89ca975d36a4d20ec96cd9e779e473e49d31e5754faefd1cd8fdcf1cfb86 \
  --output /evidence/certification
python audit/multi_child_spinoffs/source_identity.py
python -m pytest \
  tests/sentinel/test_in_kind_distributions.py \
  tests/sentinel/test_canonical_session_kernel.py \
  tests/sentinel/test_production_state.py \
  tests/sentinel/test_production_decision.py \
  tests/sentinel/test_operational_parity.py \
  tests/sentinel/test_formed_economics.py \
  tests/sentinel/test_formed_startup.py \
  tests/sentinel/test_formed_restore.py \
  tests/sentinel/test_binding_and_handover.py \
  tests/sentinel/test_terminal.py tests/sentinel/test_terminal_identity.py \
  tests/wealth_core -q -p no:cacheprovider \
  --junitxml=/evidence/regression-v2.xml
```

Original logs/JUnit and the baseline source are retained locally under
`C:/GitHub/stocker/.codex-tmp/multi-child-spinoff-evidence/`.
An initial broader-regression invocation inherited the image's stale
`SENTINEL_REPO_ROOT=/work/repo`, failed the documentation-path check and was
explicitly stopped (exit 137). Its incomplete `regression.log` is retained;
it is not a passing regression or an economic runtime refusal. The replacement
explicitly binds the repository root to `/work`.

## Scope

This certificate covers the bounded canonical ownership transition. Runtime
source identity changes, so prior checkpoints still require normal admission
under matching source. This PR grants no migration exception. Completely
omitted children, reviewed terms admission, provider/PIT completeness, cash
finality, native fills, NAS qualification and full economic certification remain
separate gates. The running discovery replay and its frozen source are untouched.
No strategy selection, Owned55 policy, funding, sizing or execution change is
included. Nothing has been merged or deployed by this task.
