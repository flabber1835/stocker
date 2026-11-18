# November 18 close and SHADOW service health

On November 18 the close published version 24 at 21:17:47 UTC. The SHADOW
container was sampled unhealthy from 21:18:57 to 21:23:28 while the same
supervised worker advanced the book. Its probe checked a signed inventory
that included every corpus publication. Appending a single valid close
necessarily invalidated that inventory before the producer could attest the
new session. Docker's last five probe results had rotated by the time of
inspection. Other causes for individual failed probes remain possible.

Archived WAL fixes the timing more precisely. The monitored processed-session
relation had no committed writes between the publication and 21:23:02.460580
UTC. SHADOW then committed its daily observation, followed by its new runtime
authority at 21:24:12.240853. Once any financial cursor moves, an old inventory
can no longer explain the entire difference. The probe then requires the new
signed projection.

For the compose health probe, recognize a bounded wait when the only inventory
change is a single committed operational publication for the signed next
session. Authenticate the new publication receipt against its signed predecessor
and require the current worker to have been armed before that job began.
Reconstruct the previous complete inventory within one repeatable-read
snapshot. Check the exact predecessor version and dates, the published job,
candidate, validation and their native deadline. Require the signed hint's
current configuration and waiting interval, and the same authenticated live
worker and original deadline across the observation. This permits process
health during work. The regular financial reader and activation prerequisite
still require the full current inventory. Any other change needs fresh proof.

On failure emit a bounded diagnostic code to the container log, where it
survives Docker's five-probe history. Keep sensitive exception messages and
latch payloads out of the container event. Use the existing three-second probe
budget and a single nonblocking pipe write. Log delivery has no health effect.

Source comparison for the combined PR must retain the complete inventory of
the locally installed application at `4ce1dc299dd781fb223f5b8b59c3beff0fcddf95`
as well as the already registered PR606 and prior releases. The separately
validated local host verifier is included in the PR. Final qualification
checks the candidate's exact source and the unchanged economic identities.
