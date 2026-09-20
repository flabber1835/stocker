# Complete status resource review

Review base: owner-merged main `29cdd7727ba2adea27672830c538d76a2218943e`,
with pending #415 `558673b1b434760673ee1de52c25c4e1e1f707c7` integrated in an
isolated branch. The existing PRs are not changed by this review.

## Measurement plan

Build a synthetic full-universe operational publication and canonical shadow
origin in disposable PostgreSQL using the existing provider/identity test
scaffolding. Use the real publication, warmup, transition, checkpoint, receipt
and status code. A fresh child process measures complete public shadow status,
separating its peak RSS from fixture/acquisition/warmup allocations. Instrument
phase duration and peak RSS without replacing their implementations. Retain
state/record/authority hashes and require read-only repeated status to agree.

First validate the harness on a smaller universe, then measure 5,000 securities
and concurrent readers on the same database. No deployment certification,
provider completeness guarantee or actual broker state is manufactured: test
clocks and test identity are explicit fixtures. No NAS access is authorized.
The synthetic references/actions do not establish realistic retained-history
capacity; that limitation must remain visible in the ledger.

Review the HTTP caller's concurrency behavior independently. A SQL statement
timeout does not bound cumulative Python work or concurrent memory. Any code
change needed to enforce a resource boundary must be documented here before
implementation, with real concurrency acceptance and a removal falsifier.

## Decision: bound simultaneous panel builds

The three full-build HTTP routes (`/`, `/panel.json`, `/operational-health`)
currently enter the synchronous thread pool independently, multiplying the
entire status working set inside one 512 MiB panel container. Permit one such
request at a time in the deployed single worker. Contenders receive immediate
503 UNKNOWN with a five-second retry hint and no cached evidence. The HTML
response retries automatically; health, static assets and subscription enrollment
remain independent. Hold admission through response construction and release in
`finally`, including exceptions. Explicitly select one Uvicorn worker so an
environment worker override cannot silently multiply the process-local limit.

This limits simultaneous allocation; it does not make a single read's memory
or elapsed time bounded. Preserve that distinction in qualification results.
Tests must hold a real routed request while every other full-build route is
called, show that only one build starts, keep health responsive, and prove that
success and failure both release admission. Removing acquisition, release or
the deployment worker selection must fail the respective falsifier.
