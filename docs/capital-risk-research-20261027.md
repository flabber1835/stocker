# Capital risk research execution

The owner authorized an isolated eight-arm research comparison of concentration
trimming, volatility-scaled stops and a rearm-independent drawdown governor.
The economic protocol is frozen separately under commitment
`a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52`.
The original 2008 experiment and its fixed/control sources remain immutable.
This document governs execution infrastructure, not production financial policy.

## Owner-authorized fast screening amendment (2026-10-27)

The owner rejected the multi-day initial pass and authorized a different approach
or shorter test periods. This amendment changes the sequence, not the frozen
C/V/G parameters. Preserve the original protocol and every completed/partial
baseline artifact. Do not launch further full baseline suffixes for this screen.
The completed suffix-002 output is retained; it is not evidence of full baseline
equivalence. The eight-arm campaign and multi-origin/capital/cost sweep are
deferred until a useful initial result warrants them.

First compare only B and G on the already independently audited, immutable
2008-2026 Core trace. G cannot change Core trades, holdings, cash, action
entitlements or observations, so replaying those identical Core transitions is
unnecessary for this restricted exposure calculation. This explicitly supersedes
the fresh 4,639-close gate below for this initial trace screen only. It does not
waive that gate for C/V, change an old checkpoint, or qualify production.

Authenticate the existing sealed inputs and completion-review commitment on a
GitHub-hosted runner. Verify the formation/daily/monthly journal commitments
against the canonical final checkpoint. Consume all 126 formation observations
before the 4,639 measured closes; do not reset governor memory at reporting
windows. The B account must reproduce every retained daily accounting field and
NAV using the frozen canonical account operation. G changes only that account's
close-committed next-open target. Preserve the old allocation's overnight return,
the exact Core/BIL factors, 10bp transition costs and the original day-zero anchor.

At the first funded open both B and G must have the same zero Core allocation;
verify this condition and reproduce the retained cash-only startup exactly.
Do not invent the otherwise unavailable historical holdings to reconstruct a
different formed entry. Refuse this restricted screen if its startup condition
is false. Later accounting calls use the unchanged canonical account operation
with read-only trace valuation evidence, not a parallel holdings book.

Publish full-period and every-calendar-year results plus the predeclared
2008-2009, 2020-2022 and 2025-July2026 diagnostic windows. Use full-path governor
memory in all subperiods, include the predecessor close in window returns/DD,
and label short-window annualization as diagnostic. No threshold sweep or best
window selection is authorized. Independently recompute account factors and
metrics; serialized governor/account continuation must equal uninterrupted
evaluation. Guard falsifiers cover old-overnight/new-intraday exposure, costs,
day-zero, unavailable data, exact daily axes, identity and nonmutation.

The screen can reject or prioritize G; it cannot prove general robustness or
replace PAPER. If Core changes remain necessary, use separate freshly formed
canonical B/C/V screens over 2021-2022 and 2025-July2026 before considering
combinations. Those implementations and their action/restart gates remain
mandatory; do not apply changed Core rules to an old book or infer a rebalanced
path from scaled old returns. A full matched replay is required before advancing
a Core-changing candidate. All financial outputs remain encrypted; no local
replay/container or production contact is permitted.

`research/capital_risk/screen-protocol.json` is the versioned initial-screen
request contract. The existing original protocol hash remains the source of
the unchanged governor rule; the new screening contract is separately hashed.

## Production boundary

PAPER services, broker endpoints, installed source/configuration, database,
financial books, command journals and deployment remain untouched. LIVE remains
forbidden. No research job receives production secrets or mounts. No main merge,
deployment, production workflow dispatch or reopening of PR 541 is authorized.

Only GitHub-hosted Ubuntu machines may execute the research. A self-hosted
runner on the PAPER computer is not an alternative. Repository token access is
read only and is not persisted into the checkout. The new workflow has its own
concurrency group and cannot cancel production jobs.

## Initial probe

The first job is a capacity probe only. It reads the explicit request, confirms
the exact repository, owner actor, research branch and GitHub-hosted Linux
context, checks that named production credentials are absent, and records CPU,
memory, disk, Python and Docker-server capability. It does not acquire market
data, instantiate a strategy, access a broker/database, or start a replay.

The only published probe artifact is its small, allowlisted JSON report. It
contains neither environment dumps nor input files. Insufficient capacity and
unexpected contexts refuse explicitly. A passing probe is permission to continue
engineering, not evidence of baseline equivalence or economic success.

GitHub requires a workflow to exist on the default branch before ordinary
`workflow_dispatch` use. To avoid a main merge, a manually pushed, versioned
request on `codex/capital-risk-research` can trigger this workflow. The push
trigger is limited to that branch and three research paths. There is no main,
PR, release, schedule or production-workflow trigger. The workflow also declares
`workflow_dispatch` for future use if separately admitted; its branch/actor
fences still apply. The initial request admits only `probe`.

## Replay admission remains separate

Before any replay, stage the approximately 1.70 GB frozen inputs through private
or authenticated-encryption research storage and verify the transferred bytes.
This repository is public; neither the raw inputs nor unencrypted financial
checkpoints may be uploaded as a staging shortcut. Any transfer key must be new,
research scoped, and withheld from the offline replay process. No production
credential can be reused. The probe deliberately has no transfer key.

The baseline must reproduce all 4,639 measured closes and its complete financial
path before changed arms are interpreted. Each changed Core policy starts with
its own fresh formation. Governor-only pairs must retain identical Core trades,
holdings and observations. New partial reductions and stop state require
canonical ledger transitions, explicit identities, action transformations,
restart proofs and guard falsifiers; editing checkpoint balances is forbidden.

Replay segments must stop cleanly well before GitHub's six-hour job limit,
verify checkpoint and journal commitments, and preserve resumable encrypted
artifacts. Successor jobs verify every prefix and resume the next unsent
session. Actual capacity and throughput determine concurrency and estimates.
The eight-arm frontier and all negative results are retained. No favorable
research result grants production admission.

## Encrypted staging decision

The first hosted probe passed with 4 CPUs, 15.7 GB available RAM, 93.0 GB free
disk and Linux Docker. Staging uses a research-only, non-latest prerelease
`research-capital-risk-inputs-20261027`, with two encrypted assets below GitHub's
2 GiB per-asset limit. No existing workflow listens for releases; production
publication remains fenced to successful main-push Sentinel safety runs.
These assets are research inputs, never a deployable release or promotion.

An independently generated 256-bit research key is stored as the new Actions
secret `CAPITAL_RISK_RESEARCH_KEY_20261027`. The local recovery copy is protected
with Windows CurrentUser DPAPI. It is never committed, printed or placed in
process arguments. Existing secrets are neither read nor changed. The frozen
runtime image is exported read-only; no local container or replay is started.

Each asset uses cryptography's streaming AES-256-GCM with a fresh random 96-bit
nonce and a full 128-bit tag. The versioned header is authenticated. The framing
is `CRSEAL01 || nonce[12] || ciphertext || tag[16]`. A SHA256 commitment also
binds each ciphertext in the branch request. Decryption writes a private partial
file and authenticates the entire payload before making it available to parsers
or Docker. Failed authentication deletes that partial file. The staging key is
provided only to the decrypt step; the replay container never receives it.

The data tar contains only explicitly inventoried frozen source, bundle,
archive, references, four repair fact/evidence sets and baseline comparison
journals. Its first member is a versioned manifest. Extraction accepts only
unique regular files with confined relative POSIX paths, exact manifest sizes
and hashes, and bounded total size; symlinks, devices and extra members refuse.
All 514 source files, recorded bundle/archive/reference hashes and the exact
retained image ID are verified at the hosted destination before replay admission.
The staging workflow may load that image and verify its frozen `/fixed` source,
but cannot start a backtest. Its public output is an allowlisted nonfinancial
verification receipt. No data or decrypted financial output is an Actions
artifact. Temporary plaintext remains only on the fresh hosted VM.

The owner subsequently explicitly approved uploading the two encrypted research
assets to that public research staging release, with the key kept separately.
This resolves the earlier automatic approval rejection for that destination.
The branch request is added only after both remote assets match their exact
SHA256 and length commitments. No other destination or plaintext payload is
authorized by that approval.

Two direct uploads of the 1.76 GB data ciphertext failed with `tls: bad record
MAC`; GitHub retained no data asset. Recovery transfers the identical ciphertext
as sequential 64 MiB parts to the same approved release. Each part has its own
server-verified SHA256 and size; the request also retains the original full-file
SHA256 and size. The hosted downloader verifies each part while concatenating,
then verifies the original aggregate ciphertext before GCM authentication. This
changes transport framing only, not plaintext, nonce, tag, input manifest or key.
Only one temporary encrypted part is staged locally at a time, bounded to 64 MiB,
and is removed after its exact remote commitment is verified. Complete remote
parts are reused on retry; an existing mismatched name refuses rather than
overwriting. No shared storage or protected experiment file is cleaned up.

## Fresh baseline prefix admission

After hosted staging passes, the first financial job is deliberately bounded to
32 fresh canonical formation transitions, following the unchanged 299-session
feature warmup. It runs the retained fixed image and original backtest module,
original fixed policy and exact frozen inputs. Its output is disjoint from all
completed experiments. No completed checkpoint initializes this book.

The worker has no network, capabilities, production mounts or credentials. It
uses one CPU, 2 GiB RAM without swap, a read-only root and input mounts, a private
64 MiB temporary filesystem and a host-owned private output directory. The
research key remains on the hosted orchestration process and is never forwarded
to Docker. Worker stdout/stderr is captured privately; public workflow logs show
only an allowlisted progress/admission receipt.

The 32 canonical formation records must equal the retained baseline's first 32
records exactly, including state/input/chain hashes, decisions, evidence and
accounting. The new checkpoint's canonical roundtrip and every committed journal
prefix must pass, with no tails. A second zero-transition restore must preserve
all financial bytes and the exact cursor. This is a direct canonical
restore/serialize proof, not a backtest invocation with a zero limit (the
original CLI defines zero as unlimited). The entire output, including private
logs and reviews, is authenticated-encrypted before Actions upload. Only the
small nonfinancial receipt is plaintext. Failure refuses further baseline or
variant execution; it never repins the comparison or edits financial state.

This prefix proof establishes fresh initialization and restart compatibility.
It does not satisfy the separate full 4,639-close baseline gate. Later baseline
segments must bind factual overlays to their own actual predecessors, preserve
recovered tails and prove the complete financial path before interpreting arms.

## Research policy arithmetic

Policy helpers are pure intent/state calculations; they do not create a second
financial book or execute trades. Canonical ledger integration and the full
baseline comparison remain mandatory before any variant is run.

Core episodes can contain fractional shares after reviewed corporate actions.
A C trim therefore aggregates quantities as exact fractions. The close-bound
remaining target is still a whole-share floor, as specified in the protocol.
When that holder target is positive, each internal episode retains its exact
proportion `episode_quantity * target / aggregate_quantity`. No episode age,
entry reference, review flag or source-lot history is reset. Rounding internal
episodes to whole shares would destroy valid entitlements and is forbidden.
The canonical reduction/ledger transition, including fees and full-exit
semantics when the remaining target is zero, is a separate integration gate.

The V width helper requires the exact 21 causal session labels as well as 21
positive finite closes. It uses sample standard deviation of 20 log returns,
the frozen multiplier/bounds, and checks the previous transformed floor before
accepting a newly calculated floor. Stop comparison uses exact decimal-string
fractions, matching the existing inclusive stop convention. Every action-domain
transformation still requires a canonical integration proof.

G persists only its own mode, capped eight-close recovery streak and cursor in
a strict, protocol-bound research envelope. It consumes Core observations and
the existing final target, and returns a ceiling-composed next-open target.
Missing recovery observations reset the streak; missing Core drawdown refuses.
Escalation precedes recovery and resets the streak. NORMAL keeps no accumulated
recovery credit. The account model, not this pure helper, is responsible for
applying a close decision at the following open.

## Portable retained-image identity

The first hosted staging attempt authenticated the ciphertext and all 591
inventory members, then refused when Docker 28's classic store could not resolve
the original containerd image-index ID. Inspection of the authenticated export
proves the original index `97b69cf2...` points to the Linux/amd64 manifest
`6388fb9b...`, which binds config `1b449754...` and 25 layer blobs. Every exported
blob hash passed. The exact plaintext export SHA256 is
`35330c13dd2eb5bdee647751dd95d9c7b93814423d1c3ab2c90477d404819241`.

`runtime-identity.json` preserves the complete index/manifest/config/layer chain.
Before loading, the hosted job must verify that exact archive hash, every blob
hash, the original index's platform link, config and compressed-layer links.
After loading, classic Docker's config-based local ID and all 25 uncompressed
RootFS diff IDs must match. Only then may the config ID address the retained
image for source verification and replay. This is the identical exported image;
no rebuild, substitution, retag, source change or financial-checkpoint relabeling
is permitted. Receipts retain both original index and execution/config IDs.
Every `docker run` explicitly forbids pulls. The new staging attempt is separately
identified as `stage-002`; the refused first attempt remains evidence.

Docker documents that its classic store does not support image indices or build
attestations, whereas the containerd store does:
https://docs.docker.com/desktop/features/containerd/ and
https://docs.docker.com/engine/storage/containerd/.

## Fresh baseline suffix continuation

Hosted run 40532524116 passed the first 32 formation transitions through
2007-10-05. The authenticated output and a separate local read-only review agree
on exact original formation bytes, outer/inner/state hashes, all four journal
prefixes and zero tails. No measured close has completed. This freshly formed
checkpoint is the sole B predecessor; it must be continued, never restarted or
replaced with a completed old book.

Successor jobs download only an explicitly selected encrypted predecessor
artifact from its exact research run/head/attempt. Bootstrap may use an
Actions-read-only token, which never reaches Docker. Before restoring, verify
the artifact's receipt, ciphertext hash/size, GCM tag, confined manifest inventory,
canonical checkpoint and every journal commitment. Preserve original artifact
bytes and all historical checkpoints/tails. The frozen /fixed backtest source
and policy are unchanged, so the existing canonical resume path verifies its
base/source/input identity without a source-successor or policy relabeling.

Each hosted segment has an explicit nonzero transition limit and deadline below
the six-hour GitHub limit. Pilot timing was 291 seconds for warmup and 495 seconds
through the first 32 transitions; choose initial suffix budgets conservatively,
then use actual throughput. Encrypted output needs no artifact recompression.
Never capture mutable financial output before exact writer termination is proved.

Stop before each retained factual repair's earliest affected session. Bind a
sparse overlay to that fresh book's actual canonical predecessor, check every
source/outer/inner/input/state/prefix identity and canonical roundtrip, and resume
only the adjacent suffix through the existing repair/load/Journal.recover path.
Copy factual terms and source evidence, not the old bound checkpoint identity.
Validate once-only entitlement, position removal/pending state and the exact
daily axis after replay. New unsupported actions refuse for separate primary
evidence review. No cash, holding, flag or balance edits are allowed.

The first staging inventory omitted DADE's separate completion extraction even
though the retained template carried its hash/citation. Retain its exact bytes
under `research/capital_risk/primary-evidence/` before fresh DADE repair
qualification. This is a public SEC issuer-filing extraction, not user financial
state or provider market data. Its SHA256 must equal the already retained
completion-source commitment. Keeping the missing evidence outside the immutable
/fixed source preserves the baseline's financial/source/input path.

### First suffix admission

The first successor is explicitly `baseline-suffix-001`: restore the verified
2007-10-05 checkpoint, execute exactly 21 adjacent transitions, and stop on
2007-11-05 after 53 total formation records. This stops before DADE's earliest
affected session; it applies no repair and has no measured closes. It qualifies
encrypted cross-job restoration before adding factual overlays.
Prefix and suffix jobs share one B-specific concurrency group and cannot cancel
production jobs. The prefix dispatch request remains unchanged.

The request binds predecessor run 40532524116, attempt 1, source commit,
workflow path, immutable artifact ID/digest, receipt and ciphertext commitments,
and the actual outer/inner/state/input/base hashes. Bootstrap verifies the
GitHub repository, owner, branch, push event and successful exact source run
before the pinned artifact downloader can act. The token has Actions read only
and remains confined to bootstrap; no credential reaches a worker.

A preflight offline reviewer verifies the authenticated predecessor checkpoint,
canonical roundtrip, source/base identity and every journal/historical prefix.
The canonical backtest resumes that exact output with a nonzero 21-transition
limit, without source-successor, capital or policy overrides. Postflight requires
all 53 original formation records byte-for-byte, the exact final cursor, unchanged
predecessor commitment, all retained historical checkpoints and zero tails.
The predecessor checkpoint/receipt and artifact ancestry are retained alongside
the append-only journal history. Only after postflight can the new checkpoint
become a future predecessor. All financial artifacts remain encrypted.

### DADE suffix admission

Run 40540062773 passed all 53 formation records and stopped on 2007-11-05.
The new actual canonical predecessor independently matches the retained DADE
predecessor hash and holds 33 DADE shares. This equality is evidence from the
fresh book; no old financial state or predecessor identity is substituted.

`baseline-suffix-002` restores that exact artifact, qualifies a sparse factual
overlay against its own checkpoint, and runs 77 adjacent transitions to
2008-02-27 (126 formation records and four measured closes). It stops before
GLDN's earliest affected session. DADE's known 77 USD cash merger on 2007-11-06
is the only admitted correction; its two retained source extractions and exact
suppression/addition facts are hash-bound. Generate the overlay using the fresh
canonical predecessor. With this exact B prefix, the resulting document hash
equals the retained fact document; this is checked, not assumed.

Before replay, load the overlay through the unchanged canonical repair parser,
verify the exact source term and unaffected terms, and demonstrate wrong-parent
and consumed-session refusals. A copy-only canonical terminal proof must remove
the actual DADE holding and pay its actual quantity times 77, while the source
checkpoint stays byte-for-byte unchanged. No mark or financial balance is
fabricated. The replay then uses the original backtest's repair/resume path.

Postflight must prove exactly one actual 2,541 USD DADE payment, no residual or
pending DADE, one retained repair with its exact source/input binding, every
current/historical journal commitment and the exact session axis. All 126
formation and first four daily records must match the original byte-for-byte.
The full-period baseline gate remains pending. Every predecessor checkpoint,
receipt and ancestry link is stored at an immutable hash/run-qualified path so
adding a new generation cannot overwrite earlier lineage evidence.
