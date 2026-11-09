# Reuse immutable install facts and batch current observations

The November 8 retained successful installation launched 497 processes. Ten
candidate identity checks took 36 seconds, Git launched 167 processes, and Docker
container inspection launched 158. These counts include resumed commands; nested
trace spans are not additional processes. A short drain wait in that installation
does not prove the subsequently installed idle-control correction caused it.

This first installer correction reuses facts whose named inputs are immutable.
It does not cache financial evidence, readiness, configuration files, application
state, or source bytes. Each Host owns its maps for one invocation only. A resumed
command constructs a new Host and independently authenticates its inputs.

## Image and explicit configuration identity

An identity probe still renders the currently selected Compose configuration on
every call. Its immutable result is reusable only for the exact full image ID,
full commit SHA, and canonical JSON of the three explicitly supplied shadow
configuration values. The first probe uses the existing qualified image,
network isolation, resource limits, owned cleanup, and deadline. Validate the
result shape before admitting it; failed or malformed probes are never cached.
Return independent copies. Fresh configuration changes choose another key.
The image-presence/revision check at each mutation boundary remains independent.

## Immutable Git objects and fresh source

Within one Host, reuse ancestry and changed-path results for exact full commit
SHAs and tracked names from the exact committed tree. Immutable predecessor
Compose blobs may use the same explicitly bounded Git-object map. Never cache
HEAD, branch, status, the index, source paths, current file bytes, qualification
reports, or qualification logs. Both preparation source checks remain because
they bound dynamic source import and intervening probes.

Qualification may use the Host's Git reader so its immutable object queries share
that invocation's map. It must still freshly verify exact HEAD, feature branch,
clean status, every current qualified file, safe paths, report bytes, and retained
test logs at the existing boundaries. Enumerating committed names is permitted
only after the existing exact-HEAD and clean-status checks, using that exact full
candidate commit. No working-tree or filesystem result enters the object map.
Every immutable object read, including its first miss, disables Git replacement
objects using process-local command options. Check the actual/common metadata
for grafts afresh at each cache use; a graft file refuses. No Git configuration,
references or installed repository metadata is changed.

## Fresh batched application observations

One bounded Docker container-inspect call observes the six named application
roles at each existing boundary. Map results by exact container name and reject
duplicates, unexpected names, absent required roles, malformed results, and
ambiguous discovery. Where a legacy predecessor legitimately lacks a role,
one exact-name discovery followed by one inspect of the discovered IDs provides
explicit absence. Validate that inspected IDs and names match the discovery.

An observation belongs only to that boundary's local validation. Do not retain a
container map on Host or reuse it across a stop, start, policy update, recovery,
environment installation, proof operation, or later journal stage. The existing
shadow wait and its original deadline remain separate. Postgres identity and
financial, notification, drain-incarnation, UNKNOWN and expiry checks remain
fresh at their existing boundaries.

## Resume an already completed application start

At START_REQUESTED, retain the original proof clocks, shadow wait, preserved-state
checks and fresh environment verification. Observe all six applications freshly.
Skip Compose up only if every role already runs the exact candidate image,
is healthy without restarting or OOM state, and has the exact current candidate
Compose service-configuration hash. Before the fresh container batch, obtain
expected hashes from Compose's own
bounded `config --hash '*'` operation; do not reproduce its hashing algorithm.
Require each exact role and its installed Compose labels to match the expected
project, service and hash. A missing, ambiguous, malformed or unsupported hash
result refuses the optimization, not the original install path.

If that complete positive proof is absent, use the original Compose up/wait path
and its original deadline. A foreign application image still refuses. A freshly
observed missing, foreign, stopped or unhealthy shadow refuses before starting
the other applications; do not ignore a negative fact obtained after its wait.
Freshly observe all applications after a real up; a pre-up batch cannot prove
its result.
The skip only avoids repeating an already completed software start after a lost
acknowledgement; it creates no financial readiness or automatic authority.

## Focused qualification

Tests must prove one immutable identity probe for repeated exact inputs, changes
in image/commit/config selecting distinct probes, malformed/failed results not
being reused, independent results, and fresh instances doing their own work.
Git tests must retain fresh HEAD/branch/status/current-byte refusals while
counting reduced immutable queries. Batch tests must reject missing, duplicate,
foreign, replaced and malformed observations and prove fresh reads after mutations.
Start-resume tests must skip only a complete exact healthy candidate set, preserve
the original path for partial/unhealthy/wrong-config sets, and reject foreign
images. Removed-guard falsifiers must detect broken reuse/admission guards.

An event-driven owned read-only drain/health observer is a separate design and
qualification task. This correction does not introduce helper containers or
change the canonical admission lock API.
