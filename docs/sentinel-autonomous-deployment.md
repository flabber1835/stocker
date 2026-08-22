# Autonomous Sentinel deployment

> **Current implementation status:** no arguments retain the conservative
> `DEPLOYED/FENCED` installation. An exact reviewed `DUAL_RUN_GO` bundle may
> run the certified broker-free ledger and reconciled Alpaca PAPER transport in
> parallel. The present two-source evidence remains `PAPER_EXECUTION_NO_GO`, so
> Alpaca account P/L is never promoted to certified strategy performance.

This is the supported one-command fenced installation path for the
risk-contained environment:

```bash
cd /path/to/stocker
bash scripts/sentinel-autonomous-deploy.sh
```

After `bash scripts/sentinel-go-validate.sh` produces a reviewed bundle, the
supported year-end observation activation is:

```bash
bash scripts/sentinel-autonomous-deploy.sh \
  --mode dual \
  --validation-bundle artifacts/<bundle>.zip \
  --confirm-reviewed-go <exact-bundle-sha256>
```

Running `git pull --ff-only` first is harmless but not required. The launcher
requires a clean `main`, performs its own fast-forward-only pull, and re-execs
the freshly pulled launcher if HEAD changed. It never uses `git reset`, never
discards local work, and never changes branches by guessing.

## Normal existing-NAS use

For an already owned Sentinel installation, the bootstrap deliberately reuses
facts that are already authoritative instead of asking the operator to duplicate
them:

- deployment id and Alpaca paper account id are read from canonical PostgreSQL
  `status`; a conflicting configured value refuses;
- the runtime registry repository is recovered from the existing automation
  container image (including stopped containers), or from an immutable local
  authorized-image RepoDigest;
- when no separate test repository is configured, it uses the discovered
  runtime repository name plus `-test`;
- when the signing-key id is omitted, the exact new network-disabled test image
  derives it from the configured private key and requires that public key to be
  a currently valid ACTIVE committed trust root.

The deployer will **not** search arbitrary files for a private key. Set
`SENTINEL_DEPLOY_SIGNING_KEY_FILE` to the already-enrolled Ed25519 private key,
or place exactly one key at one of the documented conventional secret paths:

```text
~/.config/sentinel/signing-key.ed25519
~/.config/sentinel/signing-key.pem
~/.sentinel/signing-key.ed25519
~/.sentinel/signing-key.pem
```

That path is the only deployment secret location the bootstrap cannot safely
infer from durable system state. The key must be outside the Git checkout and is
mounted read-only only into the exact new test image with `--network none`.

For the normal existing owned deployment, therefore, once that key location is
already configured/placed, future deploys are simply the one command above.

## Optional explicit configuration

`.env.example` exposes every discovery result as an override when an operator
wants it pinned explicitly:

- `SENTINEL_DEPLOYMENT_ID`
- `SENTINEL_PAPER_ACCOUNT_ID`
- `SENTINEL_RUNTIME_IMAGE_REPOSITORY`
- `SENTINEL_TEST_IMAGE_REPOSITORY`
- `SENTINEL_AUTHORITY_ARTIFACTS_DIR`
- `SENTINEL_DEPLOY_SIGNING_KEY_FILE`
- `SENTINEL_DEPLOY_SIGNING_KEY_ID`

Existing secrets (PostgreSQL, backup target, Sharadar, and Alpaca PAPER) remain
in `.env`; process environment still overrides file values. The deployer parses
`.env` literally instead of sourcing shell code, so an unquoted database
password containing `#` is not silently truncated.

The deployer does **not** add or rewrite trust roots. To rotate signing keys,
first commit/enroll the new public root as ACTIVE, then point the private-key
setting at the new key (the id may remain omitted and is derived). The new
execution certificate is activated first. If
`SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY=1`, the predecessor signing key is
then durably revoked before automation is enabled; with the default `0`, the old
key remains retained.

For an already owned account leave `SENTINEL_DEPLOY_ALLOW_EMPTY_BIND=0`. A truly
new, known-empty paper account can set it to `1` for first enrollment. That path
still uses a dedicated signed `ADMIN_BIND_EMPTY` certificate and requires a
complete empty-account observation with zero positions and zero working orders.
There is deliberately no automatic inherited-book migration.

## What the deployer does now

The validation command may already have applied the bundle's explicitly
reported, exact-candidate schema migration and bounded Sharadar daily ingest.
That closes the old-schema/BIL-tail upgrade gap before the read-only parity and
readiness evidence is produced. With a reviewed bundle, before disturbing the
running services the deployer verifies the
bundle allowlist, canonical JSON, manifest/checksums, secret scan, freshness,
verdict, zero-mutation counters, clean exact HEAD, all four recorded image IDs,
runtime source identity, current publication/frontier, shadow model digest, and
existing shadow lineage. Those checks are read-only and run before tagging,
pushing, fencing, schema migration, or service changes.

Only then does it enter the fail-closed transition boundary. From that point any
exception or Ctrl-C attempts the minimal emergency kill and directly stops any
running Sentinel automation container. Its current `run()` path then:

1. fences/stops old automation;
2. starts only the preserved behavioral PostgreSQL volume;
3. takes a fresh physical base backup and proves a restore drill **before**
   explicit schema migration;
4. runs schema migration while automation is stopped and requires the durable
   kill fence afterward;
5. while writers remain stopped, rechecks the exact reviewed publication,
   visible frontier, shadow configuration, and lineage; any migration or
   transition-time corpus change refuses;
6. persists the reviewed source/config/data-publication/bundle facts while
   still fenced;
7. starts `sentinel-shadow` with no Alpaca credential/account environment and
   waits for the current decision-close attestation;
8. in dual mode, proves the exact PAPER account, signed observation authority,
   and current plan-to-shadow session/state/data/allocation match, then starts
   automation behind the kill fence and explicitly releases it;
9. persists non-secret Git/image/review facts and a deployment receipt.

The shadow service independently recomputes the reviewed publication subject
inside the held genesis publication pin, closing the final recheck-to-container
start window. It also refuses to trust or ingest a decision-session frontier
before 23:45 `America/New_York`, 15 minutes after the documented second daily
updates for [Sharadar SEP](https://data.nasdaq.com/databases/SEP) and
[Sharadar SFP](https://data.nasdaq.com/databases/SFP), while retaining the
strict following-XNYS-open cutoff.

On no-argument success the terminal ends with:

```text
DEPLOYED/FENCED
```

This is not a financial GO and not active strategy observation. Do not infer
success from container presence alone. The remaining activation transaction is
allowed only after a fresh, reviewed NAS validation bundle for the selected
mode; see `sentinel-nas-go-validation.md`.

On reviewed dual success, PAPER orders, positions, and informational P/L are
visible in the external Snowball iOS app connected to Alpaca, but certified
return remains the broker-free shadow series. Snowball is not Sentinel's status
UI; Sentinel's separate mobile web panel shows certified shadow return, PAPER
reconciliation, and combined operational red/green status. Every execution
cycle separately reconciles expected commands and projected target positions
against Alpaca. A material discrepancy makes operational status red/`BLOCKED`,
queues a critical alert, and prevents subsequent strategy orders until an
explicit review/reactivation. It never auto-liquidates the existing PAPER book.

## Synology and the deployment failure modes this closes

The deployer deliberately reuses the canonical Sentinel Compose resolver rather
than spelling a graph itself. If the host probe selects the Synology-compatible
CPU-free base graph, it generates an automation overlay with only `cpus:` lines
removed; memory and shared-memory limits remain intact. This avoids the
`NanoCPUs can not be set` daemon failure while preserving the resource controls
the host can enforce.

Emergency fencing uses `scripts/sentinel-emergency-kill.sh`, so backup-root
attestation, authorized-runtime variables, broker credentials, and shell-export
of the PostgreSQL password cannot become prerequisites for the risk-reducing
kill operation. Ordinary deployment steps still require and verify the backup
contract.

Runtime startup does not perform hot authority-table DDL. Schema migration is an
explicit deploy phase while automation is stopped, and its lock wait is bounded.
The paper-observation lifecycle clock is captured before its expensive warmup,
so the candidate cannot consume its own `not_before` margin; installation may
stage a future-dated certificate and activation waits for the boundary.

Issuer generation is not a local counter. Both administrative and execution
rotation paths advance past every certificate already installed in PostgreSQL,
including an unactivated STAGED certificate left by an interrupted deploy. The
second invocation therefore converges instead of trying to reuse an already
consumed generation.

## Recovery after a refusal

The deployer is intended to be rerun after the cause is corrected. It does not
roll the database backward, restore an old certificate, reset the book, or
reseed data because those operations would guess about authority-bearing state.
A mid-deployment failure leaves automation killed/stopped. Correct the reported
external problem (registry, backup medium, feed, broker availability, signing
key, etc.) and run the same command again.

The attempt directory under
`$SENTINEL_AUTHORITY_ARTIFACTS_DIR/deployments/` retains command logs, image
build/promotion records, signed candidates/certificates, and—on success—the
final deployment receipt.
