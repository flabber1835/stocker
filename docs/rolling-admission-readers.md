# Rolling admission and operational readers

This closes the A21 integration gap from the economic code-closure ledger.
It grants neither paper transport nor economic certification. The existing
provider, accounting, first-GO and deployed evidence gates remain required.

## Decisions before implementation

One broker-free feed reader owns explicit publication-version dispatch. Reuse
the existing execution reader's authenticated legacy/rolling dispatch and expose
it to admission, deployment and monitoring. Legacy publication readers retain
their refusal of rolling data. Only their exact reader-version refusal permits
dispatch; malformed receipts and other integrity failures never permit fallback.

Readiness, frontier and publication identity must describe the same pinned
generation. Rolling readiness uses the existing sealed-input validator and
source-final clock. An empty legacy table cannot supply evidence for a rolling
publication. Saved rolling readiness carries its publication fingerprint;
monitoring may display its age but cannot apply it to another generation.

Observation metadata comes from the immutable TICKERS reference bundle bound
to the admitted snapshot, with its complete content hash and retained provider
refresh date (not a fabricated historical observation date). Publication roots
retain the existing complete publication-row hash. Build
and activation read these identities under a common publication pin.

The observation-candidate warmup executes the selected production strategy's
canonical feature warmup and one pure session transition. The legacy default
25-slot bootstrap cannot attest the selected 20-slot V5 strategy. Record the
252-session input identity, selected strategy, decision and state hashes, and
publication identity. Persist no parallel strategy state, simulated fills or
broker commands. Candidate construction refuses evidence from a different
generation or strategy. A current-input calculation does not become a 20-year
backtest or historical-causality certificate.

The public installer consumes these same readers for readiness, its retained
publication subject, and causal timing. Keep the next-open margin and all
signed review, image, schema, account, backup and shadow-authority requirements.
Validate through the actual generated installer programs and signed candidate
installation/activation using isolated PostgreSQL and synthetic input/accounts.
Include publication/tamper/clock/strategy falsifiers and preserve legacy tests.

A current rolling generation must never be refreshed through legacy
`feed-daily`. The public installer accepts its measured readiness, rechecks it
with `check-data`, and retains the generation binding. Stale rolling inputs
refuse with an explicit preparation requirement; they are not relabelled as
legacy retryable freshness. Automatic rolling renewal belongs to the still-open
single-owner maintenance lifecycle, not a second deployment writer. The new
reader participates in the strategy's data-semantics source identity.

Canonical warmup evidence uses `sentinel.paper-observation-warmup/2`. The
offline issuer requires its selected strategy and complete corpus-root identity
to match the signed bindings, verifies its decision/input hashes and refuses
legacy `/1` target-book-only evidence for new issuance. Existing signed records
remain retained; this does not rewrite them. The original 25-position accepted
boundary experiment is historical evidence and is not repinned to the current
20-slot strategy. Current warmup remains explicitly uncertified historically.

## Certification boundary and handoff

This is a follow-up to owner-merged #403 on independently verified base
`4dd5af636ed48d6c17d8a75af4209cbc23a17e48`. PR #404 independently addresses
notification succession and streaming deadlines; it is not a dependency of this
reader change. Keep its separate evidence and schema migration requirements.

| Gate | Disposition |
|---|---|
| A21 admission, P1 | Versioned publication, current immutable metadata, selected-strategy warmup, CLI readiness and generated installer readers are connected. Candidate stages share a publication pin, and claims reject a different generation/strategy. Local acceptance is described in the retained evidence package. |
| A21 visibility, P2 | The panel reads a cached verdict under the publication pin. A green legacy or different-generation report is unknown for current rolling data. Full window validation remains outside page loads. |
| A5 maintenance, P1 | Still open code work: recurring verified backups, proactive horizon renewal, single-owner restart-safe coordination and bounded outage recovery. Stale rolling admission refuses; this change does not create another producer. |
| C1/F6, F19, C3 | Provider/implementation gates remain open: exhaustive cash finality, native fill corrections/busts and predecessor interval completeness. Existing refusal and takeover fences remain. |
| A12/A1, A14/A16 | Full-universe resources, state-filesystem stalls, current SIP entitlement and held-spinoff policy remain separate unresolved gates in the economic ledger. |
| Historical returns | No 20-year multiple or historical-causality certification. Current metadata warmup is explicitly prospective. Preserve the original goldens and reference differences. |
| NAS qualification | Exact built images/PostgreSQL 16, full-size input latency, actual storage and physical restore evidence remain unexecuted. No NAS or real broker account was accessed. |

For subsequent NAS qualification, first review/merge the PRs and obtain the
exact-head CI image/source receipts. Keep automation disabled and the kill
switch engaged. Require the existing verified backup/restore, signed account
binding, image/schema, reviewed input generation, source-final clock and
next-open margin prerequisites. A stale rolling generation requires the
existing reviewed GO preparation path; never run legacy `feed-daily` to convert
it, manufacture a capability flag, or reset a retained book.

In the reviewed runtime environment, retain stdout, stderr, exit status,
timestamps and immutable image/commit identity for:

```bash
docker compose -f docker-compose.sentinel.yml --profile cli run --rm -T --no-deps sentinel check-data
docker compose -f docker-compose.sentinel.yml --profile cli run --rm -T --no-deps --entrypoint python sentinel tools/sentinel_operational_parity.py --starting-cash "$SENTINEL_SHADOW_STARTING_CASH" --expected-commit "$REVIEWED_SHA"
docker compose -f docker-compose.sentinel.yml --profile cli run --rm -T --no-deps sentinel create-paper-observation-candidate --certificate-id "$CERTIFICATE_ID" --issuer-generation "$ISSUER_GENERATION" --deployment-id "$SENTINEL_DEPLOYMENT_ID" --expect-account "$SENTINEL_PAPER_ACCOUNT_ID" --cash "$SENTINEL_SHADOW_STARTING_CASH" --maximum-exposure "$SENTINEL_DEPLOY_MAXIMUM_EXPOSURE" --not-before "$NOT_BEFORE_UTC" --reviewer "$REVIEWER" --ticket "$TICKET" > "$EVIDENCE/candidate.json"
```

Use the deployment's reviewed Compose/env/image overrides in addition to the
base file. The uppercase placeholders must come from the reviewed deployment,
with a future not-before and the existing pre-open deadline margin. These are
broker-free observations, not permission to enable automation.

Pass only if readiness has no failed clause; frontier and publication
fingerprint agree across the reports; candidate metadata comes from the sealed
reference bundle and retains its provider refresh date; warmup contains 252
sessions plus one decision; and the independent parity run has the same
strategy, cash, result-state hash and decision session. Require zero new
commands/fills/processed strategy state from these observation commands. Record
the panel's readiness timestamp and generation, then verify a subsequent
generation displays unknown until its own readiness is computed. Run stale
clock, changed-generation, malformed-receipt and competing-publisher cases only
on disposable restored clones: each must refuse or show unknown, never gain
authority or reset state. A failed or missing report keeps qualification open.
