# Close feed stage progress

The November 12 publication retained evidence for 450 successful raw and split
bar responses totaling 350,688,644 bytes across 15 equity partitions. The sum
of the intervals from the first raw response to the last split response in
each partition was 29 minutes 54 seconds. The sum from the last response to
the persisted part was 32 seconds. The final November partition accounted for
7 minutes 55 seconds between its first and last responses, including a
93-second gap between two successful responses. Retained response evidence
does not attribute this gap to network, pacing, retry or local decoding.

The feed already emits elapsed time for acquisition, price pairing and
persistence, along with aggregate request, response byte, retry, rate limit,
pacing, HTTP, decoding and backoff counters. The shared host progress parser
drops those events because it does not recognize the three stages or the
counter fields. Accept the existing stages, and require the complete bounded
integer counters on acquisition events. Retain the existing credential-free
validation and Python 3.8 host compatibility. A passive trace can parse these
records from the shadow service logs without saving provider URLs, headers,
parameters or response payloads. Transport policy, publication, corroboration
and execution remain unchanged.
