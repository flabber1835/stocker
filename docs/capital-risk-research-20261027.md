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

The ciphertext upload was denied by automatic approval review because explicit
owner approval for this public destination had not been recorded. No payload was
uploaded. The empty staging prerelease and new research-only secret exist. The
staging request remains local and is deliberately absent from the branch, so
publishing the reviewed transfer code does not dispatch a download. Only after
the destination is authorized and both exact assets are uploaded and verified
may that request be added to the branch to trigger the staging workflow.
