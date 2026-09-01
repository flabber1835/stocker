# Historical metadata reconstruction V2 deployment architecture

Date: 2026-08-31

This decision implements the replacement architecture required by `backtester/reviews/2026-08-31-sec-metadata-reconstruction-code-review.md` without changing strategy economics.

## Source and admission contract

- The frozen canonical PIT dataset remains the candidate universe and is identified by the committed source lock.
- The retained SEC Form 3/4/5 quarterly archives are authenticated and parsed locally before any network request.
- `SEC_UNKNOWN:<security_id>` is never interpreted as a CIK. Only explicit, validated `SEC_CIK:<cik>` values are issuer evidence.
- Vendor numeric ticker suffix removal is disabled unless a separate contemporaneous primary-source alias proof exists. V2 does not auto-create such aliases.
- Form 3/4/5 Table I security titles are supplementary evidence only. They cannot establish the listed security class.
- Listed security type requires an SEC periodic/registration filing in which the exact historical ticker identity proof and class description are tied to the same source filing.
- SIC is joined only after historical ticker/CIK identity has been established. If SIC predates the identity proof, `usable_after` is the later date.
- Economic use remains strict-prior: `filed/usable_after < decision_session`.

## Ticker-reuse / opening-seed guard

The full canonical 2006-2026 ticker/security-episode map is built independently of the unresolved-candidate list.

An identity filing inside a candidate episode may map only to that exact canonical `security_id + ticker` episode. A filing before the candidate's first session may seed opening state only when all of the following hold:

1. it is within the three preceding filing years plus the candidate start year;
2. the SEC symbol exactly equals the canonical historical ticker;
3. any known CIK is compatible with the candidate's observed causal CIK evidence; and
4. no other canonical security episode for that ticker covers the filing date or begins after the filing and before the candidate episode begins.

If more than one candidate remains possible, the event is ambiguous and is not admitted.

## Web fallback acquisition

Network work is partitioned by **stable validated CIK hash shards**, never by calendar year. The plan is built only after local bulk evidence has been derived and is bounded around each episode's earliest unresolved observation.

The workflow uses 32 stable CIK shards and `max-parallel: 1` for SEC-facing jobs. This gives one active SEC client globally while making each shard independently retryable and durable. Each client uses explicit 404/410 terminal-absence handling, 403/429 cooldown with `Retry-After`, and bounded retry for 5xx/transport failures.

Every shard prints live progress in GitHub Actions. Progress includes completed/total CIKs, percentage, HTTP attempts, successes, retries, failures, and retained source-object count.

A small bounded SEC integration probe must pass before any full shard is allowed to start.

## Durability and resume

Each web shard has its own exact checkpoint identity binding:

- reconstruction source SHA;
- canonical dataset SHA-256;
- candidate SHA-256;
- shard plan SHA-256; and
- parser/source-bundle SHA-256.

The shard output and checkpoint are cached between run attempts and uploaded with `always()` semantics. A rerun restores the newest matching checkpoint and refuses mismatched identity or source-cache hashes. A single failed/cancelled shard therefore cannot invalidate already completed shards.

## Merge and package gate

After all shards pass:

1. every expected shard must be present exactly once;
2. every shard checksum manifest is verified;
3. source bytes are merged by content hash with collision checks;
4. normalized identity/type/SIC evidence is deterministically de-duplicated;
5. the guarded 2006-2026 timeline is rebuilt offline from the common source corpus;
6. canonical observation coverage is audited by year; and
7. one immutable GHCR evidence package is published and a small branch pointer records its digest, source SHA, run ID, canonical dataset hash, manifests, coverage, and admission status.

The V2 evidence package is **not** itself permission to call the enriched canonical PIT dataset certified. Metadata admission/materiality review, canonical dataset rebuild, and PIT/economic certification remain subsequent gates.