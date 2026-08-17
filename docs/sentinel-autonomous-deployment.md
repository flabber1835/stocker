# Autonomous Sentinel ALPACA PAPER deployment

This is the supported one-command deployment path for the risk-contained Alpaca
paper environment:

```bash
cd /path/to/stocker
bash scripts/sentinel-autonomous-deploy.sh
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

## What the deployer does

Before disturbing the running system it verifies Git, performs a read-only
Alpaca paper-account identity/cash check, builds the exact Sentinel ordinary,
authorized, and test images, runs the complete Sentinel test suite with skips
refused, freezes the image build identity, pushes runtime/test images, resolves
immutable registry RepoDigests, and proves the actual private signing key maps
to a valid ACTIVE trust root. A registry/build/test/signing-key failure at this
stage leaves the existing deployment untouched.

Only then does it enter the fail-closed transition boundary. From that point any
exception or Ctrl-C attempts the minimal emergency kill and directly stops any
running Sentinel automation container. The deployer then:

1. fences/stops old automation;
2. starts only the preserved behavioral PostgreSQL volume;
3. takes a fresh physical base backup and proves a restore drill **before**
   explicit schema migration;
4. runs schema migration while automation is stopped and requires the durable
   kill fence afterward;
5. deactivates the prior automation generation if one exists;
6. runs `feed-daily` and the complete data-readiness contract;
7. verifies the canonical PostgreSQL account binding (or performs the opt-in
   strict-empty first enrollment);
8. derives the next issuer generation from the maximum of active authority and
   **all installed certificates**, so an abandoned STAGED certificate from a
   failed earlier deploy cannot trap a rerun;
9. creates the current 253-session `PAPER_OBSERVATION_ONLY` candidate and
   confirms its exact active predecessor;
10. signs inside the exact new test image with `--network none` and the private
    key mounted read-only;
11. installs the new certificate as STAGED, waits for `not_before` only when
    needed, and activates/rotates the exact predecessor;
12. optionally revokes the predecessor signing key only after the new
    certificate is active;
13. prepares the current durable paper plan and re-reads it, requiring the same
    plan id, decision session, and matching database authorities;
14. activates automation while its kill switch is still engaged;
15. starts the digest-pinned unattended service;
16. verifies the service is still behind the expected kill and certificate;
17. releases the kill switch;
18. requires `LEADER_ACTIVE`, current PASS authority, no latched failure or
    dead-letter alert, then waits through another heartbeat and proves the same
    generation/holder/fence has advanced its heartbeat;
19. persists only non-secret Git/image digest facts back to `.env`;
20. takes a post-deployment base backup and retains a JSON deployment receipt.

On PASS the terminal ends with:

```text
DEPLOYMENT PASS: autonomous Alpaca PAPER trading is authorized and operational
```

Anything else is a failed deployment. Do not infer success from container
presence alone.

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
