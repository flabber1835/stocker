# Capital risk research execution

The owner authorized an isolated eight-arm research comparison of concentration
trimming, volatility-scaled stops and a rearm-independent drawdown governor.
The economic protocol is frozen separately under commitment
`a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52`.
The original 2008 experiment and its fixed/control sources remain immutable.
This document governs execution infrastructure, not production financial policy.

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
