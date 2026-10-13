# Bounded certification read availability

Decision: 2026-10-13. The installed certified release passed fresh financial GO
and read-only lineage verification, but activation stopped when a later GitHub
certification GET returned HTTP 502. The same protected evidence subsequently
verified successfully. Software verification must tolerate a short transport
interruption without accepting stale or unchecked certification.

The existing GET-only certification client retries at most three attempts for
transport I/O errors and HTTP 408, 425, 429, 500, 502, 503 and 504. All attempts
share the original thirty-second read budget. Each opener timeout is at most ten
seconds and is capped by the remaining budget. Retry delays are one and two
seconds, only when that budget permits them. Check the budget after reading the
body too; a result completed after expiry cannot be accepted. The existing socket
timeout still governs each blocking read; this is not a claim of asynchronous
interruption of a continuously streaming body.

Other HTTP failures refuse immediately. A successfully fetched malformed or
contradictory document still reaches the unchanged strict parser and refuses;
it is never retried into different evidence. Exhaustion keeps
`CERT_GITHUB_UNAVAILABLE`. Responses are closed on every attempt, including body
read failures. Requests remain GET-only, with the same original URL, credentials,
TLS checks and authorization-stripping redirect handler. No cached certificate,
local receipt, earlier positive verdict or alternate authority substitutes for
fresh complete protected GitHub evidence.

This is a host read-availability repair. It changes no strategy, execution,
financial preparation, source request, deadline, lease, paper authority or broker
operation. Existing failed requests remain immutable. A new supported activation
still requires all current signed software, book, account and semantic restore
checks. Qualification covers transient recovery, permanent failures, exhaustion,
budget expiry, partial body failures, malformed responses and redirects, plus
the existing certification and installation contracts. The real protected
`c1541982` certificate and its completed Alpaca GO are retained observations;
they do not certify the feature revision. Exact-head CI, protected publication
and the replacement release's supported activation remain required.
