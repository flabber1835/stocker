# Installation health transitions without periodic inspection

Decision, 2026-11-08, before implementation. Replace only the local delivery
coordinator's fixed three-second shadow-health inspection loop. Keep its original
180-second monotonic allowance, exact candidate image and live running/OOM/
restarting/health predicates, subsequent canonical validation and activation
checks. This changes host observation work, not application health or authority.

Use one host-owned Python standard-library AF_UNIX HTTP connection for Engine
events. Events are wakeups only. Initial, coalesced transition-triggered and one
final fresh inspection decide health; no event record grants it. Pin the full
container ID and exact name on the first observation. Replacement or rename is
a refusal, never implicit adoption of a same-name container. A completed restart
is not newly prohibited: the existing current-state predicates remain decisive.

The qualified Engine29.9.2/API1.56 implementation flushes HTTP200 before calling
SubscribeToEvents. Its global replay is only256 events; live subscribers have a
1024-entry channel and silently drop after100ms backpressure. Headers therefore
are not registration acknowledgement and the stream is not lossless. A first
event record proves registration has occurred but quiet operation cannot depend
on receiving one. Preserve one final fresh reconciliation to cover a quiet lost
wakeup. Detection can be delayed; late or unavailable observations cannot grant
health. Primary sources:
[router ordering](https://github.com/moby/moby/blob/docker-v29.9.2/daemon/server/router/system/system_routes.go#L341),
[event buffer](https://github.com/moby/moby/blob/docker-v29.9.2/daemon/events/events.go#L13),
[silent delivery timeout](https://github.com/moby/moby/blob/docker-v29.9.2/vendor/github.com/moby/pubsub/publisher.go#L105).

Support only the selected native Linux/default Docker context with endpoint
unix:///var/run/docker.sock, whose canonical path is /run/docker.sock. Reject
remote/Desktop/Windows endpoints, TLS material, unsupported API or changed socket
identity. The context read uses the same cleaned environment as lifecycle
commands; do not change context or expose credential configuration. Require a
root-owned Unix socket and root peer credentials, and recheck its inode/device
before each owned connection. Request the explicitly qualified /v1.56 API only
when version metadata admits it and reports Linux. There is no polling fallback
for an unsupported transport, EOF, malformed framing or context/identity loss.
After a complete HTTP handshake, an otherwise open stream may have an incomplete
event/chunk at the final-read admission time: this is an unreliable wakeup, like
silence, and the one final current inspection may still prove health. Complete
malformed framing or truncation followed by EOF remains a refusal. No partial
event is evidence; incomplete HTTP headers are a handshake timeout.

All connection, header, body and event reads use nonblocking sockets and one
remaining monotonic deadline. Cap each metadata/handshake operation at three
seconds within the original180 seconds; reserve the final three seconds for the
single final inspection. Context admission is bounded by that same remaining
allowance and a three-second subprocess bound. A slow byte trickle cannot renew
an allowance. Validate HTTP status, headers, explicit content length or chunked
framing, NDJSON and finite JSON. Bound headers16KiB, metadata2MiB, event lines64KiB
and each coalescing batch256 records. Do not log inspect bodies, environment,
health output, attributes or arbitrary daemon errors.

The event filter selects only the pinned container and health/lifecycle changes;
exclude exec_create/exec_start/exec_die health-probe chatter. Revalidate exact
Actor.ID and type locally. Old or duplicate events only request a fresh
inspection; keep no unbounded event history. Optional bounded retained replay
is a wake optimization, never a completeness proof. Quiet pending operation
performs at most three observations (ID pin, post-header, final), with one for
an already healthy initial observation. A drained transition batch causes at most
one additional inspection. Never sleep periodically to inspect.

Close every owned socket/selector on success, refusal, cancellation or timeout.
Do not reconnect, spawn an acknowledgement child, mutate/create a Docker marker
or mount the Docker socket in any application/helper. EOF and transport errors
are explicit failures, not health. Preserve the coordinator's injected clock
and the separate canonical leadership advancement check.

Qualification uses a private fake Unix Engine to falsify early headers, silent
lost transitions, replay, exec chatter, replacement, current failures, malformed/
partial/chunked input, slow trickles, EOF, unsupported context/version and exact
deadline/cleanup. An isolated actual Engine fixture, if separately authorized,
can qualify transport without production containers or network/DB access. No
test or CPU cohort runs during the owner-controlled passive forensic window.
