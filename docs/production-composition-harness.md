# Production composition harness

## Purpose

The production composition harness closes the layer above the existing unit,
Sentinel, Wealth Core, environment, Alpaca, Sharadar replay, backup and internal
state harnesses. Those suites remain authoritative for their own contracts. This
harness proves that the contracts are actually connected through the supported
operator lifecycle.

The primary production entry under test is:

```sh
bash scripts/sentinel-go-validate.sh
```

The acceptance target is not module coverage. It is **authority-edge coverage**:
every transition that can grant, retain, consume or revoke production authority
must be exercised at the real process boundary where practical.

## Why this exists

A NAS GO attempt on 2026-09-10 reached exact CI software certification but
refused before Phase C financial preparation. The exact software suite had
5,188 passes with no failures or skips. Preparation reported no schema migration
and no bounded Sharadar ingest. The incident demonstrated that strong component
coverage did not prove the complete host Bash -> flock -> environment -> CI
certificate -> Docker/Compose -> PostgreSQL -> preparation chain.

The internal-state harness deliberately leaves deployment-level GO entry points
to their dedicated suites. The prior script suite also performs most tests
inside the test image with network disabled. The missing layer is host-level
composition.

## Global failure invariant

No production failure may become an anonymous `NO_GO`.

Every causal refusal must retain, through every wrapper and into the final
evidence surface:

1. a stable machine-readable `reason_code`;
2. the phase or authority boundary that emitted it;
3. no raw credential, DSN, account identifier or secret-bearing URL;
4. deterministic classification on replay; and
5. proof that no later authority-bearing side effect occurred.

A known failure that is reduced to generic `NOT_PROVEN` without its available
causal reason is a harness failure.

## Authority graph

The checked catalogue lives in
`tests/production_composition/contract.py`. It currently contains at least
twenty authority edges from operator entry through final handoff, including:

- operator shell -> lifecycle flock;
- flock/open FD -> verified Python entry;
- `.env` -> Bash/process environment;
- GitHub read credential -> certification artifact;
- certification artifact -> GHCR digest -> immutable local image;
- certified image + lifecycle capability -> Phase C;
- backup restore authority -> schema/feed mutation;
- commit/image identity -> feed binding;
- bounded preparation -> current publication;
- publication -> parity/readiness;
- readiness -> requested-target proof;
- target proof -> exact runtime promotion;
- promotion -> runtime pointer;
- pointer -> recreated panel;
- panel -> atomic deployment handoff;
- causal refusal -> evidence bundle; and
- supported restored NAS state -> current GO lifecycle.

Every edge has these eight required variants:

`happy`, `missing`, `stale`, `corrupt`, `crash_before`, `crash_after`,
`retry`, and `concurrent`.

The matrix is therefore at least 160 explicit scenario contracts. Matrix
completeness is itself gated so a future authority edge cannot quietly lose one
of these variants.

## Real-process coverage

The harness does not count a mocked Python function call as proof of a host
boundary.

`tests/production_composition/test_operator_entry_process.py` launches the real
Bash entry and the real lifecycle-lock helper. A controlled executable shim is
used only at external/expensive child boundaries so the test can prove shell
ordering and fail-fast behavior without contacting production services.

`tests/production_composition/test_lock_process_boundary.py` uses actual POSIX
processes, inherited file descriptors and kernel `flock`. It proves:

- a real child sees the inherited flock and one-run token;
- forged environment markers do not confer authority;
- a second GO lifecycle is refused;
- the flock survives death of the small lock parent while the inherited child
  remains alive; and
- the lock becomes available after that child terminates.

`tests/production_composition/test_env_process_boundary.py` sources the real
Bash environment bridge, including NUL-delimited record transport and process
environment precedence.

`tools/production_composition_harness.py` is a required live CI gate. It uses
real Docker Compose and real PostgreSQL 16 to exercise the production
PostgreSQL startup/health wrapper, SQL reachability, restart/retry, an
unhealthy service and a missing service. Missing Docker/PostgreSQL prerequisites
are failures, not skips.

Existing backup and internal-state physical PostgreSQL campaigns remain required;
this harness does not duplicate their economic, WAL or broker oracles.

## Fail-fast GitHub credential

Normal CI-certified GO requires a GitHub read credential because protected
certification artifact download is authenticated even when repository metadata
can be read anonymously. The supported credential precedence is
`SENTINEL_GITHUB_READ_TOKEN`, then `GITHUB_TOKEN`.

The operator shell now refuses before bootstrap/certification work if neither is
present. `--local-full-certification` is intentionally exempt because it does
not consume the protected GitHub certification artifact.

## CI

### Complete GO acceptance (issue #363 item 1)

`tools/production_go_e2e_audit.py` launches the supported operator shell with
real Docker/Compose/PostgreSQL and exact source-built runtime/test images.
Sharadar and the PAPER account use local protocol fixtures with dummy keys.
The resolved CLI environment must select the local source before seed begins.
The seed stops one XNYS session before the available fixture frontier, so the
successful GO itself must perform source catch-up and publish the final session.
The before/after publication observer runs in the exact built runtime against
the fixture PostgreSQL container, holding a read-only repeatable-read pin. This
observer loads the same fixture receipt key through the canonical environment
parser so it verifies the seed's signed publication chain. The test observation
does not require an operational Compose execution override.
When the retained window includes May 2026, the fixture includes TRI and the
reviewed stale vendor dividend observation. The production v7 migration applies
its own adjudication and records the canonical cash audit.

Acceptance binds the validation bundle, runtime promotion, recreated panel, and
handoff to the same commit, images, publication, and invocation. It also requires
the complete ordered production phase transcript and every SHADOW authority gate.
Current-strategy parity follows `production-certification-separation.md`.

Sensitivity runs deliberately fail the actual called boundaries: host stages,
schema/feed write authorization, schema migration, feed catch-up, final
publication check, operational parity, Sharadar readiness, database health,
validation ZIP creation, requested-target proof, panel recreation, and final
handoff write. A temporary interpreter/Docker wrapper installs only the selected
raising mutation; all preceding production work runs normally. The successful
run uses the production programs unchanged. Each fault must emit its specific
marker, make GO fail, and prevent subsequent promotion or final success as
appropriate. This is stage reachability/sensitivity evidence; interruption,
durable recovery, and convergence campaigns remain issue #363 item 2.

CI partitions sensitivity into operator, preparation, financial, and handoff
campaigns. Every campaign starts with a complete real GO success and then runs
its selected faults through new operator invocations. This preserves full
production certification in each invocation while keeping the campaigns within
the job time limit. Both existing required composition check names aggregate all
campaigns; any failed or cancelled campaign prevents acceptance.

Synthetic-merge verification binds the checked-out GitHub merge SHA and its
exact PR-head parent. Its base parent must belong to the freshly fetched base
branch. The event's base SHA can precede a concurrent base-branch update, so it
does not replace verification of the actual merge parents and current ancestry.

`.github/workflows/production-composition-harness.yml` runs on pull requests,
merge groups, `main` pushes and manual dispatch.

Acceptance requires:

- exact scenario catalogue completeness;
- no skipped/xfailed/xpassed production-composition pytest nodes;
- real host process/lock/environment tests;
- exact diagnostic propagation regressions;
- the real operator shell sequencing/fail-fast tests;
- real Docker/PostgreSQL live gates; and
- retained evidence even on failure.

This workflow supplements, and does not replace, Sentinel safety, backup
reliability, internal-state, Sharadar replay, Alpaca and Wealth Core gates.
