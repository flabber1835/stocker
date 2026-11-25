# Opening and idle authority proof attribution

Decision: November 25, 2026. The current opening guard already reuses pure
retained-book material within its owned callback and checks automation plus the
concrete PAPER operation in one signed-authority invocation. Its independent
pre-read, post-read and pre-mutation checks remain mandatory. The idle observer
also repeats a complete read-only authority attestation every thirty seconds.
The November 25 trace shows repeated proof work, but the existing timings do
not identify which part of the signed and publication proof consumed the time.

Record bounded, fixed-name elapsed times for current-publication validation,
runtime source/package identity, historical publication rows, authenticated
publication receipts, publication-policy source identity, and the final
certificate/binding check. Attribute broker-read guard work separately from
the idle observer. Emit only phase names, counts and duration; never account,
certificate, source path, SQL values or broker data. Timing failure must never
change an authority refusal, financial result or UNKNOWN outcome.

The signed-root proof may report the count of publication rows already fetched;
this adds no query or payload conversion. These records do not identify the
bytes returned by the initial current-publication validation, the receipt join,
or other database reads. Container network counters therefore remain shared
across processes and cannot be assigned to a specific SQL statement from this
telemetry alone. A later byte-level study should use database query telemetry
outside the authority decision, without logging values or copying payloads in
the critical path.

Do not retain a signed authority verdict or broker permission between checks.
The publication proof reads mutable publication rows, receipt policy and rows,
and ingest-run statuses. The post-chain certificate load detects lifecycle and
revocation changes. A future historical-proof reuse design needs a complete
version witness for those inputs, including rewrites, plus an exact owner and
publication lifetime. Its gain must be established from the new attribution
before changing this boundary. Source-byte rechecks, control/leader/kill,
rollout, account, clock and per-operation guard checks remain fresh.

Qualification must show that the timing records appear for successful and
refused broker guards and idle observations, that timing failures do not affect
refusal, and that source tamper, certificate revocation, publication change and
observer restart retain their current fail-closed outcomes. No telemetry item
serves as execution authority.
