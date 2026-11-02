# Dedicated research runner capacity preparation

The P11 native diagnostic export `13110082519` retained an initial disk refusal
with `8,112,300,032` bytes free before parent retrieval or worker launch. That
observation establishes insufficient space at the existing 12 GiB boundary; it
does not identify the cause of the space use. The original refusal remains
unchanged.

The selected preparation is available only to a separately published research
workflow on its own disposable GitHub-hosted Ubuntu 24.04 x64 runner. Before
staging, it may remove the unused preinstalled Android installation at the single
literal path `/usr/local/lib/android`. The official
[runner image inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
sets `ANDROID_HOME` and `ANDROID_SDK_ROOT` to `/usr/local/lib/android/sdk`; the
[image installation script](https://github.com/actions/runner-images/blob/main/images/ubuntu/scripts/build/install-android-sdk.sh)
sets `ANDROID_ROOT=/usr/local/lib/android` and installs the SDK under that root.
These sources justify the path, not an assumed number of reclaimable bytes.

`research/capital_risk/ephemeral_runner_capacity.py` has no target argument. It
requires actual Linux and Ubuntu 24.04 host facts, GitHub-hosted/x64 image
metadata, the exact repository `flabber1835/stocker`, owner actor, push event,
research branch `refs/heads/codex/capital-risk-research`, valid source/run
identities and run attempt 1. It rejects a container host and production
credentials. The current workspace and temporary/tool-cache directories must be
the normal dedicated hosted-runner scopes and must be disjoint from the Android
tree. The helper itself must be the checked-out module in that workspace.
Invalid context never starts deletion or writes to an untrusted output path.

Before removal, the helper resolves the exact target and each ancestor without
accepting a symbolic-link alias. Non-target ancestors through `/usr/local/lib`
must be root-owned and not group/other writable. The Android target and SDK
markers do not require an undocumented owner or read-only mode: the official
installer deliberately applies `chmod -R a+rwx` to the SDK, and final ownership
is not established by the inspected image source. Its fixed parent namespace,
resolved identity, device/inode and mount fences provide the removal boundary.
The Android root may contain only its `sdk` child, and real SDK manager
and platform-tools markers must be present. The helper rejects a mount point at
or inside the target and on any non-root ancestor, including a bind mount on the
same filesystem. Android,
workspace and staging temporary storage must share the measured filesystem.
The final check repeats the host/path/mount checks immediately before removal
and requires the same target device/inode.

The deletion uses a fixed argument vector for noninteractive `sudo` and GNU
`rm`, with one-filesystem and preserve-root guards, no shell and no constructed
target. The target/ancestor resolution path cannot contain symlinks. Ordinary
symlinks *inside* the installed SDK are unlinked without traversal; they never
authorize access to their targets. The command's own no-follow behavior remains
necessary because Android toolchains can contain such internal links. Every
mount below the target is refused rather than traversed or detached.

The only public receipt is
`artifacts/capital-risk/ephemeral-runner-capacity.json`, written atomically with
flush/fsync and replacement. Its schema is
`research.ephemeral-runner-capacity/1` and authority is
`NONFINANCIAL_HOST_PREPARATION`. It records source/run identity, fixed target,
bounded phase history, actual free bytes before/after, whether removal was
attempted/confirmed, and a static error code. It contains no financial, market,
credential or exception-message payload. `PREPARED` requires confirmed absence
of the target and at least 12 GiB actually free afterward. Failed checks or
removal refuse; a removal timeout remains `UNKNOWN_REMOVAL_OUTCOME`, with no
retry or fallback. Invalid host context emits only a closed refusal code.

This is a separate pre-staging host preparation capability. It does not change
the existing 12 GiB initial or 10 GiB preworker disk gates, 2 CPU/8 GiB worker
fences, source inputs, strategy/controller rules, or any existing workflow.
Workspace/source/input/evidence, Docker data and services, local/WSL systems,
pagefiles and protected cleanup targets are outside its removal scope. The first
integration is a separately reviewed successor to the known failed P11 job;
running jobs remain frozen. Later research workflows require their own explicit
selection of this preparation. Paid runner changes are not part of this design.

Local qualification executes only pure metadata guards and filesystem/process
stubs. It verifies wrong-host/repository/ref/attempt refusals, exact path and
mount/alias protections, literal deletion arguments, durable public phases,
capacity failure and unknown removal outcomes. It never removes an Android
installation locally. Actual preparation evidence can come only from the
selected hosted successor.

The first P11 integration uses a dedicated capacity request and workflow. Its
metadata probe authenticates the helper's `PREPARED` receipt before staging and
then runs the unchanged native orchestration with a P11-only expected request.
All 427 preceding source bytes and the native request are retained; native
horizon 10, the completed REFERENCE artifact and every comparison/resource/stop
guard remain mandatory. The capacity receipt is uploaded even if a later phase
fails. No P10 job is selected by this successor.
