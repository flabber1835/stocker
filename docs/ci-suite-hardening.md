# CI suite hardening and retired-source cleanup

Decision: 2026-10-17, following the owner's comprehensive CI review and explicit
authorization to implement its recommendations and remove retired-source
references and tests wherever possible.

## Production and preservation boundary

The operational source is Alpaca with OpenFIGI classification. The old vendor
is not a production requirement or an operational fallback. Remove its manual
diagnostic workflow, source-specific replay test owner, four required replay
workers, and source-specific replay tests. Keep the current Alpaca acquisition,
formation, daily continuation, execution and recovery witnesses mandatory.

Reusable synthetic corpus/HTTP fixtures move out of the retired research suite
into test support. Their normalized table protocol is a fixture contract, not
evidence of current-provider acquisition. Do not disguise vendor-specific tests
by changing only their names. Explicit independent witnesses for current
Alpaca behavior remain separate from shared canonical-data tests.

Mixed legacy test modules are split by behavior before deletion: preserve pure
price/volume-domain and published-listing-history falsifiers under their current
behavior owners, while dropping retired transport, export-schema and credential
tests. Extract shared HTTP/ZIP doubles into support rather than importing a
deleted test module. No canonical economic assertion is removed just because
its original example was supplied by the retired vendor.

The dividend price-basis witness uses a provider-neutral test filename while
preserving its economic assertions and the shared `sharadar_domains` normalization
API; that historical API name describes price conversion, not source transport.

Do not rewrite byte-pinned historical evidence, frozen economic oracles,
published source identities, database history, or stored schema names in this CI
change. Historical research consumers and normalization compatibility can retain
their exact identifiers when deletion would break those contracts. Inventory
and explain remaining references; remove obsolete active instructions and
credentials from CI rather than manufacturing a migration or destroying data.
New software evidence names current Alpaca/OpenFIGI provider qualification
explicitly and marks historical research performance outside operational scope;
old signed reports keep their original bytes and schema interpretation.

## Mutation evidence

Each reviewed mutant declares its test selector and accepted failure signals.
The unmodified, source-authenticated selector's complete nonempty collection is
the authority for exact expected instances, including every parameter case.
First execute the unmodified source in the same disposable overlay, requiring
every collected instance and all phases to pass. Then modify one source
anchor and run a fresh interpreter with bytecode disabled. Require the same
collection, no skips, setup/teardown errors, unexpected cases or unrelated call
failures, and at least one reviewed invariant failure. Record exception types
from pytest reports rather than inferring them from JUnit failure tags.
Authenticate the loaded overlay source and retain baseline/mutant evidence.
An operational RuntimeError cannot count as a killed guard. Legitimate
domain-exception falsifiers have a finite per-mutant signal allowance.

## Test isolation and local reproduction

Existing legacy test doubles use a finite explicit compatibility registry.
New and renamed modules receive real production validation by default. Preserve
dedicated schema, source-authority and producer-identity witnesses. Shared
synthetic filesystem isolation remains explicit and cannot issue deployment
authority. Remove unused retired-service import activation code.

The local complete pytest command builds or uses the pinned runtime/test lens
and derives test inventory from the permanent owner authority. It must reject
missing tests and unauthorized skips, preserve exact approved expected failures,
and isolate owners in separate processes. The minimum-host Python 3.8 checks
remain a separately identified runtime. Local test success is not signed CI,
deployment, economic or broker authority.

## Scheduling and diagnostics

Assign both ordinary and rolling modules deterministically using retained,
source-bound JUnit module durations, longest estimated work first and stable
path ties. New modules enter automatically with a conservative positive default.
Keep existing module fixture boundaries and the million-row shared fixture;
do not introduce shared mutable books or database state to claim speed gains.
Preserve complete, disjoint module ownership and exact-attempt evidence.

Check shell syntax by invoking bash separately for every tracked shell file.
Remove the full operator-suite repetition from the Docker lens build; retain
small image-layout/import/browser smoke checks and the mandatory owner lane.

## Coverage measurement

Provide an explicit advisory CI coverage campaign using the same pinned test
lens and permanent Python 3.12 owner inventory. It is manually dispatchable so
instrumentation does not double the normal PR workload or change production
deadlines. Publish per-domain branch/statement measurements with all source in
the denominator, source authentication and exclusions disabled. Keep unknown
shell/browser coverage explicitly unmeasured. The first campaign establishes a
baseline, not an arbitrary repository-wide 100 percent release gate. Existing
automation-service branch protection stays mandatory. Any later regression
threshold is a separately documented decision based on measured baseline data.
The campaign checks the exact selected owner receipt union as well as source
hashes. Proven empty interrupted-child counters admit both the documented
`pid123` name and the pinned coverage library's numeric process-name spelling;
their zero-content/known-empty-SQLite checks remain mandatory.

## Acceptance

Run focused falsifiers for each new invariant and demonstrate that breaking the
guard makes its witness fail. Validate workflow/source ownership, exact test
collection and evidence assembly after retirement. Use targeted Linux tests for
subprocess, shell, symlink and PostgreSQL behavior. Do not repin economic golden
fixtures or run the full suite merely to hide an unrelated failure. Publish the
completed validated feature branch through a ready-for-review PR to main.
