# Main-branch deep-review remediation

**Status: implementation contract, 2026-08-12. Paper trading only.**

This record closes the design questions raised by the post-activation deep
review. It does not activate Sentinel, change the Wealth Core strategy, permit
live trading, or add an autonomous trading path. Where it conflicts with
`sentinel-deployment.md`, `sentinel-architecture.md`, or
`sentinel-execution-contract.md`, those documents remain authoritative unless
this record explicitly tightens a safety boundary.

## 1. Scope and delivery

The findings are repaired as one review-remediation branch with independently
reviewable commits and focused falsifiers. The work is split by ownership, not
by creating parallel state or portfolio implementations:

```text
canonical Wealth Core/controller     strategy and state correctness
Sentinel feed + bt-data              immutable, identified decision inputs
existing execution membrane          migration/recovery correctness
certification/deployment tooling     reproducible evidence and safe operations
```

No fix may weaken the paper URL allowlist, live-trading guards, publication
pin, writer lock, UNKNOWN-submit handling, or the separation between explicit
migration, preparation, and execution.

## 2. Wealth Core and controller decisions

1. Pending Wealth Core OPEN and CLOSE intent is part of the canonical shadow
   state and is transformed by the same split, ticker-identity, and conversion
   terms as the episode it names. Quantity transformation is exact and recorded;
   an inexpressible or terminally extinguished intent is cancelled explicitly,
   never silently retained under stale economics.
2. Production breadth delegates to the certified float32 lag-return primitive.
   There is one numerical rule at both the replay and production boundaries.
3. SPY regime input is a dated XNYS sequence ending on the decision session.
   Missing, duplicate, out-of-order, or stale sessions are unavailable evidence,
   not a shorter synthetic window.
4. Persisted controller state has an exact versioned schema. Missing critical
   severe/ramp/history fields are refused unless an explicit migration defines
   their meaning. All controller and evidence numbers must be finite. JSON state
   serialization rejects NaN and Infinity.
5. Feed and run session streams are strictly increasing and unique. Warm-up
   validates bar/session identity and duplicate corporate-action application
   with the same rigor as ordinary advancement.

## 3. Published corpus decisions

1. A publication identifies every input that can change a decision: bars, SPY,
   actions, universe/identity metadata, and applied repairs. Universe rows carry
   ingest provenance and are filtered through the held publication pin.
2. A repair never edits a visible generation in place. It writes a new stamped
   generation under the exclusive corpus writer lock, proves coherence, and
   publishes atomically. A failed repair leaves the prior generation unchanged.
3. Terminal vendor dates are retained for audit, while effective dates are
   snapped once to the first XNYS session on or after the event. The same mapping
   governs splits, dividends, acquisitions, conversions, and delistings.
4. Readiness requires the frontier cross-section and required benchmark rows to
   be materially complete relative to recent sessions. One valid row cannot
   establish a tradeable frontier.
5. Calendar construction uses explicit certified bounds covering the supported
   1998 seed interval. Vendor pagination refuses repeated cursors and a bounded
   page cap. Reversed date ranges are refused before a run row or write exists.

## 4. Certification-corpus decisions

1. A Wealth Core rehearsal reads one PostgreSQL `REPEATABLE READ`, read-only
   snapshot and records the ready `bt_data_version` obtained inside it.
2. bt-data writers mark the corpus `PUBLISHING` before the first mutation and
   set a new version `READY` only after the final successful mutation. Readers
   refuse `PUBLISHING` or failed generations. The publishing marker is durable,
   so a crash after a data commit cannot leave changed rows carrying an old
   ready identity.
3. A database advisory read/write lock prevents a rehearsal snapshot from
   overlapping a bt-data mutation job. The lock is cross-process and shared by
   every writer endpoint; process-local booleans are telemetry only.
4. Price restatements replace the complete mutable OHLCV row. Fundamental and
   earnings revisions preserve point-in-time pairs: a later value is never
   backdated to an earlier report date, and incremental computations load the
   prior-quarter context they require.
5. Every generation records source mode (`sharadar`, `mock`, or frozen import).
   Mixing modes without an explicit destructive reseed is refused.

## 5. Certification evidence and build decisions

1. The certification image contains only source trees that exist on current
   main. Deleted Stocker services and scheduler mounts are removed from the
   active Compose/build graph, and a clean-context build test checks every COPY
   source.
2. Expected failures are identified by exact pytest node id with strict XPASS
   behavior. A directory-wide failure can never be allowlisted.
3. A file is not authenticated merely because its fields look valid. Rehearsal
   finalization requires a run id and a fresh database read. Offline envelopes
   remain export/audit artifacts but cannot finalize certification unless bound
   by a separately reviewed signature scheme.
4. `--verify-only` binds the current checkout tree and commit to image labels
   and in-image source hashes. A stale image cannot be named as evidence for a
   newer clean checkout.
5. The certification database and HTTP surfaces bind loopback and have no known
   default credential. Operational health is readiness: required database and
   schema probes must pass before a service reports healthy.
6. Dependency installation is hash-checked. A version-only closure remains
   identity evidence but is not accepted as byte-reproducible certification.
7. Pull requests run the complete `tests/sentinel` suite in the pinned Sentinel
   test image with network access disabled. The workflow must be running
   GitHub's synthetic merge commit, not only the feature-branch tip. Changes to
   the production bt-engine boundary are also exercised through a hash-locked
   test lens layered on the freshly built production bt-engine image: the lens
   may copy repository files for inspection, but executable `app` imports must
   resolve from the production image. Both pytest runs retain the complete
   outcome summary (pass, fail, skip, xfail and xpass), and any ordinary skip is
   a failure. The workflow explicitly compiles the executable Python and test
   surfaces, runs `bash -n` over every tracked `*.sh`, resolves Compose, and
   applies whitespace validation to the synthetic merge result. Local matrices
   remain useful evidence, but they are never described as an independent
   repository check until GitHub records that workflow result.
8. `Sentinel safety / certification-and-durability` is a repository workflow
   check, but it is **not currently a required branch-protection check**. No PR
   or document may call it required until a repository administrator changes
   the `main` ruleset. The outstanding administrative action is: in repository
   Settings -> Rules (or the existing `main` branch-protection rule), enable
   "Require status checks to pass before merging", select the exact check name
   `Sentinel safety / certification-and-durability`, require the branch to be up
   to date so the synthetic merge is tested, save the rule, and verify on a new
   pull request that GitHub labels that check `Required`. This implementation
   deliberately does not change repository protection.

The three strict Wealth Core xfails are one certification debt expressed at
three boundaries, not three independent defects: the golden pin itself, the
derived-performance non-interference guard, and the fresh-interpreter guard all
observe the same pending `final_result` hash movement. The movement is caused by
additive terminal reconciliation audit fields. The existing economic hashes,
cash, positions and decisions are unchanged. Removing the xfails or re-pinning
is forbidden until the 2021-2023 authoritative rehearsal proves the documented
episode and $283.04 reconciliation conditions. Until that NAS evidence is
reviewed and a re-pin is separately authorized, Wealth Core remains `NO-GO` and
CI must report the three strict xfails truthfully rather than masking them.

## 6. Legacy migration and recovery decisions

1. Legacy liquidation is explicit and remains administrative, but each close
   has a durable, account-bound client key persisted before send. A send timeout
   is UNKNOWN and must be resolved by exact client-key lookup before retry. A
   position read alone is not sufficient proof that the first order never
   landed.
2. Administrative account observations are complete-or-raise. Positions and
   open orders must be arrays of typed objects with non-empty stable identities,
   symbols, sides, finite Decimal quantities, and recognized transport fields.
   Every row returned by the broker's `status=open` endpoint is conservatively
   working; an impossible terminal row or malformed status refuses the read.
3. Cancellation is by the approved stable broker order ids only. There is no
   cancel-all fallback.
4. Durable commands record the deployment identity and takeover epoch that
   minted their client key. Restored-host adoption may load and reconcile prior
   epochs; it never regenerates their identity under the new epoch. New intent
   uses only the new epoch.

## 7. Durability and exposed surfaces

1. Canonical Postgres durability includes archived WAL to an operator-supplied
   second target, periodic base backups, retention checks, and an automated
   restore drill. A local named volume alone is not a backup. Missing backup
   configuration is a visible readiness failure for deployment certification,
   but never triggers deletion or broker activity.
2. The Sentinel panel and certification services bind loopback unless an
   authenticated reverse proxy is explicitly configured.
3. Destructive filesystem tools resolve and validate their destination as a
   dedicated child before replacement. A broad repository, artifact, home, or
   filesystem-root target is refused even with `--force`.
4. Retired Stocker deployment scripts either point to the current supported
   command or refuse with a precise retirement message; they do not invoke
   deleted services.

## 8. Required falsifiers

The remediation is incomplete without tests that would fail if each guard were
removed: pending OPEN/CLOSE over splits and conversions; float32 breadth
boundary; missing newest/interior SPY session; every critical controller field
deleted; NaN/Infinity; universe/repair publication crash boundaries; tiny
frontier; weekend terminal action; concurrent corpus writer/reader; crash before
ready version; two price and filing vintages; narrow SF1 top-up; mock/real mix;
clean image build; extra Wealth Core test failure; forged envelope; stale image;
accepted-then-timeout migration; malformed positions/orders; pending-cancel and
future open statuses; exact-ID cancellation; prior-epoch terminal and in-flight
commands; WAL restore; repeated pagination cursor; reversed range; and unsafe
split destination.
