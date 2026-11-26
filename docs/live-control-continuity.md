# LIVE automation lifecycle and closing-data continuity

Decision, November 26, 2026, on the merged PR 642 baseline. The LIVE
foreground control check and scheduler health read the PAPER certificate
tables. An explicitly activated LIVE account could appear fenced and the
first idle wake could engage the kill switch despite a current LIVE certificate.

Use the enrolled public LIVE certificate and trust roots for the LIVE lifecycle
observation. Check the exact configured origin, durable owned account and
takeover epoch, control certificate digest, rollout, execution configuration,
signature, revocations and certificate and issuer clocks. All three readers
share the same verification rules. Scheduler health also requires the current
worker verdict and lease. The idle worker keeps its independent verification of
the full runtime, strategy and current publication before recording its verdict.
Callbacks and broker requests continue to verify their own authority, durable
fencing, original deadlines, strict backup and native funding where required.

The dedicated broker-free shadow service also publishes closing data for LIVE.
After the scheduled close, a verified operational publication exactly one
exchange session behind is an expected wait within that cycle's original
pre-open interval. The existing authenticated publication-to-attestation
handoff may also wait on its original publisher and worker deadlines. The
producer pointer can wake verification early. Once the transition completes,
LIVE still needs its exact current verified shadow with original lineage.
Incompatible data or lineage follows the existing terminal refusal policy.
While fenced, LIVE can read that same shadow status without changing the kill
switch, creating a plan, or writing market data. PAPER's qualified backup
optimization remains PAPER-specific.

The scheduler may reuse its existing read-only resting cycle witness for LIVE
until that cycle's original opening wake. Every reuse requires the same current
control subject, leader and bounded database row evidence already checked for
ordinary PAPER. Changed rows, control or leadership and any elapsed wake take
the full scheduler path. The witness grants no callback or trading permission.

The primary automation worker, authenticated readers and standby select the
same explicit origin. Give the dashboard, verifier and both alert dispatchers
read-only access to the two public lifecycle files. Broker keys, provisioning
and settlement paths stay with their existing owners. The standby worker uses
the same public execution, enrollment and funding paths and strict backup policy
as the primary. Keep the backed PAPER installer check pinned to the exact
reviewed Compose delta. These changes qualify software offline. The existing
LIVE enrollment, pilot and deployment requirements still apply.
