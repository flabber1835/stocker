# Rolling admission follow-up to #403

Verified base: `4dd5af636ed48d6c17d8a75af4209cbc23a17e48`, rechecked with
authenticated `git fetch origin main` immediately before delivery. The changes
are on `codex/rolling-admission-closure`, independently of sibling PR #404.
See [design, dispositions and NAS commands](../../../docs/rolling-admission-readers.md)
and the [economic ledger](../../../docs/economic-code-closure.md).

This closes the A21 reader/caller integration defect locally. It does not
complete Step 1, economic certification, a provider guarantee or NAS
qualification. No NAS or real broker account was accessed. No golden fixture,
historical return, xfail or broker capability acceptance was repinned/enabled.

## Reproduce

Use an installed local Docker engine and the PostgreSQL-capable test image:

```text
python audit/economic_399/rolling_admission_403/run_local.py final-integration
python audit/economic_399/rolling_admission_403/run_local.py expanded-regression
python audit/economic_399/rolling_admission_403/run_local.py issuer-final
python audit/economic_399/rolling_admission_403/run_local.py legacy-parity
python audit/economic_399/rolling_admission_403/run_local.py admission
python audit/economic_399/rolling_admission_403/run_local.py rolling-go
python tools/validate_test_responsibility.py --base 4dd5af636ed48d6c17d8a75af4209cbc23a17e48 --output ownership.json
git diff --check
```

`commands.json` records the exact pytest argument arrays, mutation commands,
image ID and runtime versions. Docker used `--network none`, a read-only source
mount, an empty `.env` overlay, Python 3.12.13, psycopg 3.3.4 and disposable
PostgreSQL 17.11. This mounted-source run is not qualification of the deployed
image or PostgreSQL 16. A fresh checkout without `.env` needs no overlay.

## Results and scope

| Campaign | Result and applicability |
|---|---|
| Integration | **185 passed in 267.41 s**, before the final warmup `/2` issuer guard (its affected paths were rerun below). Covers public candidate CLI and competing publisher exclusion, sealed source metadata including provider display text, selected 20-slot canonical warmup, signed issuance/install/activation, readiness cache generation, actual generated installer programs, simulated rolling execution, legacy readiness snapshots, and affected panel/CLI regressions. |
| Final versioned issuer/admission | **62 passed in 100.38 s** on final source, including real signed installation/activation, legacy `/1` refusal and rehashed mismatched strategy/corpus/decision/input rejection. |
| Legacy canonical parity | **9 passed in 17.71 s**, including the legacy observation caller using the real selected-strategy warmup and kernel with deterministic loader material. |
| Earlier expanded regression | **245 passed in 186.99 s**, before the final outer candidate pin, provider-shaped metadata fixture and additional panel caller fix. Covers the wider deployment/CLI/authority regression; overlapping cases are not extra coverage. |
| Final admission mutants | **8 killed**, with the actual assertion traces retained: offline issuer semantic binding, integrity fallback, missing candidate pin, warmup binding, cache generation, provider refresh date, starting-capital drift and source-final frontier. Their unmodified acceptance cases pass in the final versioned issuer/admission campaign. |
| Existing rolling-GO mutants | **11 killed** after the readiness-assessment extraction, before the final independent panel/metadata changes. These guard implementations are unchanged afterward: read-only transaction, existing book, caller target, acquisition strategy, final frontier, current domains/population, warmup domains, issuer/BIL evidence and pin exclusion. |
| Static/ownership | 21 changed/new Python files parse; three host scripts also parse under Python 3.8 grammar. No introduced production pyflakes diagnostics; retained existing diagnostics are listed. **473 test modules owned**, zero unowned; diff checks pass. Python 3.8 execution and exact-head CI are separate CI evidence. |

These are integration and falsifier results. Canonical warmup/initializer state
agreement proves caller consistency, not an independent proof that every
strategy calculation is economically correct. Independent assertions require
20 slots, unchanged initial cash, no positions/fills, 252+1 sessions, the actual
provider refresh date and publication-lock exclusion. Existing economic
oracles and historical goldens remain in earlier evidence packages. No 20-year
multiple was calculated here.

The local trust key/account/image identities are explicit synthetic fixtures.
Signing and PostgreSQL installation/activation are real code paths, but the
fixture does not manufacture deployed trust or authorize a real account. The
installer runner executes its generated Python against isolated PostgreSQL;
Compose service startup is not run on the NAS.

## Retained failures

`results.zip` preserves the intermediate failures as well as green runs.
Initial acceptance needed a private test-key file mode and the fixture's closed
session clock to be advanced explicitly for the stale case. A later legacy
panel test caught loss of its pre-publication visible frontier; production
behavior was restored, not its expected answer changed. An enriched provider
fixture initially supplied a `Decimal` to the fake CSV-export receipt serializer,
which cannot encode it; the fixture now uses the export's string representation.
Those setup errors were **NOT PROVED**, never counted as killed mutants. The
final mutant report retains each failed assertion, not just a green summary.

`source-provenance.json` hashes final source bytes. `SHA256SUMS.json` binds this
package, including raw output ZIP, commands and static/ownership records. The
reviewed commit is recorded in the PR description, avoiding a self-referential
commit hash inside its own tree. All NAS commands, prerequisites and pass/fail
criteria remain an unexecuted handoff in the linked design document.
