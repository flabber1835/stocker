# Readiness workflow and bounded dashboard refresh

Decision: 2026-10-13, before implementation. The operator observed repeated
preflight/status messages and two full physical copies and semantic restores
on one activation. This decision changes orchestration and presentation only;
it does not change Wealth Core, controller decisions, signed broker guards,
missed-open policy, source deadlines or paper-only execution.

## Startup and activation

| Boundary | Work that belongs here | Evidence that can be reused |
| --- | --- | --- |
| Software install | Signed immutable software, writer fence, schema compatibility, operator services | Unchanged schemas require no backup or replay |
| Financial preparation | Accepted source, retained book admission, canonical shadow verification and broker identity | Accepted source partitions and unchanged book remain reusable |
| Activation | Current signed authority, exact saved plan/shadow match, durable state, killed-first startup | Exact selected-base/current-image full restore receipt |
| Next open | Fresh mutable account, permission, market timing, affordability, order identity and reconciliation | No old broker observation replaces a required fresh check |

Supersedes the fresh-base/full-restore requirement for every activation in
`ci-certified-paper-installation.md` and `installation-activation-separation.md`.
A full restore validates a physical generation and its executable/schema; it
does not need to be repeated after every later durable transaction. PostgreSQL
WAL is the recovery mechanism for those later transactions.

After saving the plan and authority while writers remain quiesced and paper
remains killed, the target-lock owner may reuse only the *currently selected*
base with an exactly bound full semantic receipt for the current immutable
image, cluster, metadata digest, marker and target LSN. Physical-only, mutable,
foreign, mismatched or absent receipts cannot authorize reuse. Normal 12-hour,
256-MiB and timeline renewal triggers remain unchanged. If reuse is ineligible,
the ordinary fresh base plus full semantic restore is performed once.

For eligible reuse, append one uniquely identified recovery marker with
synchronous commit, then capture the flushed LSN after that commit, switch WAL
and wait within one fixed 60-second archive budget. Fresh exact-path status
must authenticate the contiguous archive through the marker's WAL segment.
The selected generation, metadata, cluster and timeline must remain identical
across that operation. Publish the normal chain observation and retain a
separate activation checkpoint naming the reused full receipt and new archived
state boundary. This checkpoint is *not* a new semantic restore receipt and
cannot authorize retention without the original full receipt. Media, chain,
identity, archive or deadline failure refuses activation before kill release.
Do not start another backup merely to disguise a failed reuse check.

Finalization reuses the same activation checkpoint. Startup service probes
remain at their meaningful mutation boundaries; status polling must not launch
validation or acquire new authority. Earlier protected software/readiness
evidence remains subject to its existing exact-identity and temporal guards.

## Daily close and maintenance

The daily cycle is discovery, accepted-source refresh, one canonical decision
and account-scaled plan, waiting for the next eligible open, execution and
reconciliation. It does not invoke the installer, GO certification or a host
base/restore ceremony. Backup mutation guards remain fresh checks of continuous
archiving and the bounded restore horizon, not instructions to make copies.
The single independent maintenance owner renews only on its existing age,
WAL-size, timeline or executable transition triggers, restores a new generation
once and reuses its bound proof thereafter. No close-time backup trigger or
trading callback is added. A necessary maintenance renewal may coincide with a
close; it is background work under that policy, not a repeated daily ritual.

## Dashboard refresh

An overlapping HTTP build currently returns retained HTML rendered with every
row UNKNOWN. The browser also turns all rows red immediately on any refresh
failure. This makes a healthy scheduled wait appear to fail during an ordinary
short transport/build delay.

A retained busy response remains explicitly LAST_KNOWN, with its original
timestamp and finite document budget. It cannot acquire current authority.
Previously successful rows show amber while a fresh request is pending;
existing failed/unknown rows stay red, and future steps stay pending. A browser
that already holds an unexpired current response may retain its original row
states during a bounded busy/transport retry, with an amber refresh headline.
It must not extend any timestamp or proof lifetime. Expiry, invalid clocks,
offline/background restoration, malformed successful responses and known
negative financial facts still withdraw current status immediately. Only a
new valid CURRENT response can restore a current headline. No machine-health
or execution gate consumes these retained presentations.

Pin this renderer transition in the existing authenticated shadow UI source
profile, admitting its previous exact target alongside historical predecessors.
The renderer transition retains its original scope. The following explicitly
requested plan/notification extension adds the named presentation/notification
files below; unreviewed neighbors and profile/module tampering remain refused.

## Next-open plan visibility and notification

The owner requested a visible next-open trade plan and a notification if it
contains trades. Add one bounded typed read-only projection of the current
generation's unsuperseded, account-bound PLAN_READY/WAITING_OPEN plan. It reads
saved target quantities, canonical dollar opening intents and the latest
complete same-account recorded broker observation; it never calls Alpaca or
creates orders. The UI shows the effective trading date, execution time,
targets, proposed buys/sells and original observation time. Opening dollar
intents have no invented share quantity. Missing or stale broker evidence
means proposed deltas are unavailable, not zero. Final opening quantities can
change after fresh price, unit, affordability and broker checks.

An independently delivered INFO alert for a trade-containing next-open plan
uses a stable cycle/plan idempotency key, existing recipient enrollment and
retry/fan-out machinery. The dispatcher can discover the current saved plan
after a restart without changing financial preparation. Empty trade plans,
already notified plans, superseded/foreign/expired plans and absent current
broker evidence do not produce a trade notification. This explicit event is
allowed through the existing INFO suppression; unrelated INFO stays quiet.
Actual order/fill notifications remain separate. Notification content is a
dated plan summary, never a claim that orders were submitted or filled.
Before push fan-out, recheck that this exact cycle/plan is still future,
current-generation, unsuperseded and bound to the enabled, kill-released
account. Consume superseded queued notifications quietly; do not announce
an obsolete plan after a restart or delivery delay.
Malformed optional plan display data suppresses its informational notification
without blocking delivery of unrelated critical alerts. Database/schema errors
retain the dispatcher's ordinary failed-health behavior. The dashboard reports
the unreadable plan separately; it never invents a no-trade result.

Authenticate the exact added projection module and model/source/notification
transitions in the reviewed retained-source profiles. Explicitly pin additions
and predecessors; do not broadly exempt their neighboring modules or change
financial book identity. Qualify matching/mismatched account/generation/session,
stale/incomplete observations, dollar intentions, no-trade plans, restart/dedup,
payload bounds, recipient policy and actual HTML/JSON presentation.
Extend the existing UI profile only by `panel/app.py`, `panel/model.py`,
`automation/outbox.py`, `web_push.py` and the added `paper_plan_preview.py`.
Existing source/renderer/presentation entries receive exact successor hashes.

## Worker clock sampling after database delays

The October 13 evening incident exited the automation child with a reported
6.637-second host/database skew. Its scheduler timestamp was captured before
control/lineage reads and creation of the separate clock connection. Database
latency between those operations was incorrectly measured as clock drift. The
supervisor recovered the existing WAITING_OPEN cycle; recovery does not make
this false failure acceptable.

The production loop supplies its host clock to the tick. After control reads
and clock connection creation, bracket the database clock query with fresh
host samples and a monotonic duration. Keep the configured five-second skew
limit: the database sample must be within that limit of both sampled host
endpoints. If the interval proves material drift, refuse; if latency makes
the verdict ambiguous, wait for a precise new sample before financial work.
A backwards host clock or material wall/monotonic disagreement refuses
the tick. A sample taking longer than the limit proves insufficient timing
precision and returns a bounded scheduler wait before any lease or callback,
without exiting the worker. No stale sample authorizes financial work. Use
the final fresh host sample for scheduling decisions in that tick. Explicit
fixed-clock tick callers keep their existing strict comparison.

Admit only this exact service successor through the existing authenticated
startup-contention source profile, with committed historical predecessors.
Keep real skew, expired execution, authority, lease and process-death guards.
Qualify slow control reads, connection creation, sample latency, real drift,
host clock jumps and the run-loop behavior with zero callbacks on uncertain
samples. No production restart or safety-threshold increase is part of this fix.
Compute the next ordinary polling interval from a fresh host sample after the
tick and its completion hooks. A slow database read must not consume an old
polling deadline and cause an immediate burst of repeated checks. Exact future
cycle/market boundaries and earlier control/alert wakes still take precedence.

## Qualification

Completed local results and exact commands are recorded in
[readiness workflow qualification](readiness-workflow-qualification.md).

Exercise the real reuse coordinator, fresh fallback and failure sequencing;
falsify exact-image/full-receipt, unchanged selection, archive coverage and fixed
deadline guards. Use isolated PostgreSQL to prove a post-commit WAL boundary
contains the saved plan/control and can be replayed without another base copy.
Verify daily callbacks have no host backup producer and normal maintenance
retains its renewal thresholds and proof reuse. Exercise actual browser script
for busy/transport retry, expiry, malformed replies, known failures, overlapping
requests and recovery without timestamp renewal. Preserve all original financial
records and qualify adjacent installer/activation/maintenance/panel paths.
Run the readiness falsifiers in the protected mutation lane using a disposable
source copy with no network, primary database, credentials or production mounts.
